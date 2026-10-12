"""Original AgentInfer planner/graph/streaming transport with frozen-token adapters.

No simulator is imported. No model tokenizer is called. The upstream graph owns
send/context dependencies; a reused request-admission adapter supplies C16 and
the already frozen priorities. Original HTTP/native result IDs remain usable.
"""
from __future__ import annotations

import argparse
import asyncio
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib.abc
import json
from pathlib import Path
import sys
import time
from typing import Literal


def load_client_sources(source_root: Path):
    """Import the old client without enabling its optional vLLM engine patch."""
    sys.path[:0] = [str(source_root), str(source_root / 'vendor')]

    class ClientOnly(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'vllm':
                raise ModuleNotFoundError('Client replay does not load the inference engine', name='vllm')

    blocker = ClientOnly()
    sys.meta_path.insert(0, blocker)
    try:
        import agentinfer
    finally:
        sys.meta_path.remove(blocker)


def prepare_trace(rows, path: Path):
    """Encode only ordering/count metadata for AgentInfer's existing analyzer.

    The dataset has no original clock. These synthetic ordinal timestamps solely
    reconstruct each linear conversation; scale=0 removes all replay waits.
    Payloads continue to come from the unchanged frozen request records.
    """
    origin = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with path.open('x') as stream:
        for row in rows:
            start = origin + timedelta(seconds=2 * row['turn'])
            value = {'session_id': str(row['session']), 'request_id': row['id'],
                     'actor_id': 'lead', 'actor_role': 'lead', 'status': 'success',
                     'started_at': start.isoformat(), 'finished_at': (start + timedelta(seconds=1)).isoformat(),
                     'input_tokens': row['prompt_tokens'], 'output_tokens': row['output_tokens'],
                     'cached_tokens': 0, 'request_purpose': 'lead_main' if row['turn'] == 0 else 'continuation'}
            stream.write(json.dumps(value) + '\n')


def make_config(source_root, trace, destination, base_url, task_num, output_tokens=1):
    load_client_sources(source_root)
    from agentinfer.agentbench.replay.config import ReplayBackendConfig, ReplayBenchConfig

    class FrozenBackend(ReplayBackendConfig):
        # The prior frozen payloads use token-ID /completions, not chat messages.
        endpoint: Literal['/v1/completions'] = '/v1/completions'

    class FrozenConfig(ReplayBenchConfig):
        backend: FrozenBackend

    return FrozenConfig.model_validate({
        'experiment': {'task_num': task_num, 'result_dir': str(destination), 'max_concurrency': task_num,
                       'task_timeout_seconds': 86400, 'run_timeout_seconds': 86400},
        'backend': {'base_url': base_url, 'model': 'dsv4-benefit', 'endpoint': '/v1/completions'},
        'replay': {'trace_path': str(trace), 'trace_type': 'agentinfer', 'sample_seed': 20260928,
                   'interval_mode': 'trace', 'trace_same_agent_gap_scale': 0,
                   'context_adjustment_mode': 'strict', 'max_input_tokens': None,
                   'max_output_tokens': output_tokens, 'request_timeout_seconds': 1800}})


def bind_plan(config, rows):
    from agentinfer.agentbench.replay.analyzer import analyze_replay_trace
    from agentinfer.agentbench.replay.planner import build_replay_plan
    analysis = analyze_replay_trace(config.replay.trace_path)
    plan = build_replay_plan(config, analysis)
    by_id = {row['id']: row for row in rows}
    source_ids = {request.key: request.source_request_id for session in analysis.sessions for request in session.requests}
    mapped, dependencies, identities = {}, {}, []
    for task in plan.tasks:
        for node in task.requests:
            row = by_id[source_ids[node.source_key]]
            assert int(task.source_session_id) == row['session'] and node.node_type == 'request'
            assert node.planned_input_tokens == row['prompt_tokens'] and node.planned_output_tokens == row['output_tokens']
            assert node.effective_interval_seconds == 0
            previous = None if row['turn'] == 0 else f"source-{row['session']:04d}-turn-{row['turn'] - 1:03d}"
            assert (source_ids.get(node.send_after), source_ids.get(node.context_after)) == (previous, previous)
            mapped[node.runtime_request_id] = row
            dependencies[node.runtime_request_id] = set()
            identities.append({'id': row['id'], 'session': row['session'], 'turn': row['turn'],
                'runtime_request_id': node.runtime_request_id, 'runtime_session_id': task.runtime_session_id,
                'source_key': node.source_key, 'send_after': node.send_after, 'context_after': node.context_after,
                'priority': row['priority'], 'domain': row['domain']})
        by_key = {node.source_key: node.runtime_request_id for node in task.requests}
        for node in task.requests:
            dependencies[node.runtime_request_id] = {by_key[value] for value in (node.send_after, node.context_after) if value}
    assert len(mapped) == len(by_id) == len(rows) and len(plan.tasks) == len({r['session'] for r in rows})
    ranked = sorted(mapped, key=lambda rid: (mapped[rid]['priority'], mapped[rid]['id']))
    return plan, mapped, dependencies, {rid: rank for rank, rid in enumerate(ranked)}, identities


async def execute(config, source_root, rows, endpoints, output, mock_handler=None):
    import httpx
    from agentinfer.agentbench.replay import runner
    from agentinfer.agentbench.replay.prompt import SyntheticPrompt
    from agentinfer.agentbench.replay.transport import ReplayTransport
    from deterministic_runtime import ConcurrentReplayExecutor
    from random_priority_admission import PriorityAdmission

    plan, mapped, dependencies, ranks, identities = bind_plan(config, rows)
    (output / 'request-identity-map.json').write_text(json.dumps(identities, indent=2))
    context = ContextVar('frozen_agentinfer_request')
    event_stream = (output / 'events.jsonl').open('x', buffering=1)
    result_stream = (output / 'requests.jsonl').open('x', buffering=1)
    facts = []

    def record_event(value):
        rid = value.get('request_id')
        row = mapped[rid] if rid is not None else None
        event_stream.write(json.dumps({**value, 'time': time.time(),
            **({'id': row['id'], 'session': row['session'], 'turn': row['turn'], 'domain': row['domain'],
                'priority': row['priority'], 'agentinfer_runtime_request_id': rid} if row else {})}) + '\n')

    class PlanAdmission(PriorityAdmission):
        """Reuse legacy C16 admission; consider all graph-ready priorities.

        Waiting on the minimum planner-ready request prevents coroutine/prompt
        preparation order from silently changing the frozen admission policy.
        This controls transport slots, never executes or releases graph nodes.
        """
        def __init__(self, *args):
            super().__init__(*args)
            self.ordered_ids = sorted(self.ranks, key=self.ranks.get)
            self.revision, self.cached_revision, self.cached_next = 0, -1, None

        def next_ready(self):
            if self.cached_revision != self.revision:
                self.cached_next = next((rid for rid in self.ordered_ids
                    if rid not in self.active and rid not in self.finished
                    and dependencies[rid] <= self.finished), None)
                self.cached_revision = self.revision
            return self.cached_next

        async def run(self, session_id, request_id, send):
            queued, admitted = time.monotonic(), False
            try:
                async with self.condition:
                    if request_id not in self.ranks or request_id in self.pending or request_id in self.active or request_id in self.finished:
                        raise ValueError('Unknown or duplicate request: ' + request_id)
                    self.pending[request_id] = self.ranks[request_id]
                    self.condition.notify_all()
                    await self.condition.wait_for(lambda: self.fatal or
                        (len(self.active) < self.limit and request_id == self.next_ready()))
                    if self.fatal:
                        raise RuntimeError(self.fatal)
                    del self.pending[request_id]
                    self.active.add(request_id)
                    self.revision += 1
                    admitted = True
                    self.record({'event': 'admitted', 'request_id': request_id, 'session_id': session_id,
                        'queued_monotonic': queued, 'admitted_monotonic': time.monotonic(), 'active': len(self.active)})
                    self.condition.notify_all()
                result = await send()
                if not result.success:
                    raise RuntimeError(f'{request_id}: transport failed: {result.error}')
                self.finished.add(request_id)
                self.revision += 1
                self.record({'event': 'finished', 'request_id': request_id, 'session_id': session_id,
                    'finished_monotonic': time.monotonic(), 'success': True})
                return result
            except BaseException as exc:
                await self.abort(f'{request_id}: {type(exc).__name__}: {exc}')
                self.record({'event': 'finished', 'request_id': request_id, 'session_id': session_id,
                    'finished_monotonic': time.monotonic(), 'success': False, 'error': self.fatal})
                raise
            finally:
                async with self.condition:
                    self.pending.pop(request_id, None)
                    if admitted:
                        self.active.remove(request_id)
                    self.condition.notify_all()

    class FrozenPrompts:
        def __init__(self, *args):
            pass

        async def build(self, task, node, exchange):
            # Upstream executor already awaits context_after before calling us.
            assert bool(exchange is not None) == bool(node.context_after)
            assert mapped[node.runtime_request_id]['session'] == int(task.source_session_id)
            return SyntheticPrompt('', (), (), None, preparation_seconds=0)

    class CaptureWriter:
        def __init__(self, original):
            self.original = original

        def submit(self, fact):
            state = context.get()
            row = state['row']
            evidence = fact.stream_evidence or {}
            raw = evidence.get('raw_usage', {})
            failure = None
            if fact.status == 'success':
                if not (fact.input_tokens == row['prompt_tokens'] and fact.output_tokens == row['output_tokens']
                        and evidence.get('done_marker') and evidence.get('token_ids_observed')
                        and evidence.get('output_token_count') == row['output_tokens'] and evidence.get('finish_reasons') == ['length']):
                    failure = 'Frozen input/output or complete streaming evidence mismatch'
            fact = replace(fact, upstream=endpoints[str(row['domain'])]['url'],
                           status='error' if failure else fact.status, error=failure or fact.error)
            self.original.submit(fact)
            state['fact'], state['validation_error'] = fact, failure
            value = {k: row[k] for k in ('id', 'session', 'turn', 'domain', 'priority', 'prompt_tokens', 'output_tokens', 'prompt_sha256')}
            value.update(status='success' if fact.status == 'success' else 'failed', usage=raw,
                response_id=(evidence.get('backend_response_ids') or [None])[0],
                agentinfer_runtime_request_id=fact.request_id, agentinfer_runtime_session_id=fact.session_id,
                started=fact.started_at, finished=fact.finished_at,
                ttft_seconds=fact.ttft_seconds, e2e_seconds=fact.latency_seconds,
                http_status=fact.status_code, error=fact.error,
                finish_reason=(evidence.get('finish_reasons') or [None])[-1],
                send_started_monotonic=evidence.get('send_started_monotonic'),
                completed_monotonic=evidence.get('send_finished_monotonic'), stream_evidence=evidence)
            result_stream.write(json.dumps(value) + '\n')
            facts.append(value)

    class FrozenTransport(ReplayTransport):
        def __init__(self, cfg, run_id, writer):
            super().__init__(cfg, run_id, CaptureWriter(writer))
            self.admission = PlanAdmission(ranks, 16, record_event)
            self.unused_client = None
            if mock_handler is not None:
                self.unused_client = self.client
                self.client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), trust_env=False)

            async def route(request):
                row = context.get()['row']
                endpoint = endpoints[str(row['domain'])]
                request.url = httpx.URL(endpoint['url'].rstrip('/') + cfg.backend.endpoint)
                request.headers['host'] = request.url.netloc.decode()
                request.headers.update(endpoint.get('headers', {}))
            self.client.event_hooks['request'].append(route)

        def _body(self, task, node, prompt):
            return dict(mapped[node.runtime_request_id]['body'], request_id=mapped[node.runtime_request_id]['id'],
                        seed=7, return_token_ids=True)

        async def send(self, task, node, prompt):
            state = {'row': mapped[node.runtime_request_id]}
            token = context.set(state)
            async def send_original():
                result = await super(FrozenTransport, self).send(task, node, prompt)
                if state.get('validation_error'):
                    result = replace(result, success=False, error=state['validation_error'])
                return result
            try:
                return await self.admission.run(task.runtime_session_id, node.runtime_request_id, send_original)
            finally:
                context.reset(token)

        async def abort(self, reason):
            await self.admission.abort(reason)

        async def close(self):
            await super().close()
            if self.unused_client is not None:
                await self.unused_client.aclose()

    originals = runner.ReplayTransport, runner.ReplayExecutor, runner.PromptBuilder, runner.capture_vllm_metrics
    runner.ReplayTransport = FrozenTransport
    runner.ReplayExecutor = ConcurrentReplayExecutor
    runner.PromptBuilder = FrozenPrompts
    if mock_handler is not None:
        from agentinfer.agentbench.benchkit.metrics.schema import EvidenceCapture
        async def mock_metrics(url):
            return EvidenceCapture('vllm', None, False, 'Offline migration check, no NPU/network', {})
        runner.capture_vllm_metrics = mock_metrics
    try:
        await runner._run_replay(config, {'actual_runner': 'agentinfer.agentbench.replay.runner._run_replay',
            'graph_executor': 'deterministic_runtime.ConcurrentReplayExecutor -> agentinfer ReplayExecutor graph',
            'actual_stream_send': 'agentinfer.agentbench.replay.transport.ReplayTransport.send',
            'frozen_token_inputs': True, 'concurrency': 'global 16 in-flight requests',
            'simulation_started': False, 'payload_endpoint': '/v1/completions'})
    finally:
        runner.ReplayTransport, runner.ReplayExecutor, runner.PromptBuilder, runner.capture_vllm_metrics = originals
        event_stream.close()
        result_stream.close()
    assert len(facts) == len(rows) and all(row['status'] == 'success' for row in facts)
    def percentile(values, q):
        values = sorted(values)
        index = (len(values) - 1) * q
        lower = int(index)
        return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (index - lower)
    summary = {'status': 'complete', 'requests': len(facts), 'successful': len(facts), 'concurrency': 16,
        'ttft_p95': percentile([row['ttft_seconds'] for row in facts], .95),
        'e2e_p95': percentile([row['e2e_seconds'] for row in facts], .95),
        'duration_seconds': max(row['completed_monotonic'] for row in facts) - min(row['send_started_monotonic'] for row in facts),
        'actual_runner': 'agentinfer.agentbench.replay.runner._run_replay',
        'ttft_definition': 'AgentInfer send start before body serialization to first generated token; dependency/admission waits excluded',
        'e2e_definition': 'same AgentInfer send start to complete stream',
        'http_transport': 'upstream httpx streaming with no connection reuse and no automatic retries',
        'input_history': 'original frozen token IDs; live generated answers never enter later payloads'}
    summary['output_tokens'] = 1
    for field, prefix in (('ttft_seconds', 'ttft'), ('e2e_seconds', 'e2e')):
        values = [row[field] for row in facts]
        summary[prefix + '_mean'] = sum(values) / len(values)
        for label, quantile in (('p50', .5), ('p99', .99)):
            summary[prefix + '_' + label] = percentile(values, quantile)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--requests', type=Path, required=True)
    p.add_argument('--route', type=Path, required=True)
    p.add_argument('--endpoints', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    rows = [json.loads(line) for line in a.requests.open()]
    routes = json.loads(a.route.read_text())['assignments']
    for row in rows:
        row['domain'] = routes[str(row['session'])]
    endpoints = json.loads(a.endpoints.read_text())
    a.output.mkdir(parents=True, exist_ok=False)
    trace = a.output / 'agentinfer-ordering-trace.jsonl'
    prepare_trace(rows, trace)
    cfg = make_config(a.sources, trace, a.output / 'agentinfer', next(iter(endpoints.values()))['url'], len({r['session'] for r in rows}))
    summary = asyncio.run(execute(cfg, a.sources, rows, endpoints, a.output))
    # Reuse the already recorded identities; no new input hash gate or retokenization.
    manifest = json.loads((a.requests.parent / 'manifest.json').read_text())
    arm = 'afd' if len(endpoints) == 3 else 'nonafd'
    summary.update(request_sha256=manifest['request_sha256'], route_sha256=manifest['routes'][arm]['sha256'])
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
