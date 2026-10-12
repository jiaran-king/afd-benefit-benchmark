"""Cold reset -> all-domain baselines -> genuine AgentInfer -> full native audit.

There is no simulator or benefit threshold in this formal entry point.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import runpy
import time
from urllib.request import Request, urlopen

from agentinfer_frozen_replay import execute, make_config, prepare_trace
from three_arm_topology import MAX_LENGTH, OUTPUT_TOKENS, TOPOLOGY, domain_worker, route_key


def snapshot_metrics(endpoints, destination, label, require_idle=False):
    records = []
    destination.mkdir(exist_ok=True)
    for index, url in enumerate(sorted({e['url'] for e in endpoints.values()})):
        with urlopen(url + '/metrics', timeout=30) as response:
            assert response.status == 200
            data = response.read()
        path = destination / f'{label}-endpoint-{index}.prom'
        path.write_bytes(data)
        active = []
        for line in data.decode().splitlines():
            if line.startswith(('vllm:num_requests_running{', 'vllm:num_requests_waiting{')):
                active.append(float(line.rsplit(' ', 1)[1]))
        if require_idle:
            assert all(n == 0 for n in active), (url, active)
        records.append({'url': url, 'file': str(path), 'available': True,
            'domains': [int(d) for d, e in endpoints.items() if e['url'] == url],
            'running_waiting_values': active, 'running_waiting_reported': bool(active)})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    args = parser.parse_args()
    client = Path(__file__).resolve().parent
    assets = Path(os.environ['BENCH_WORK_DIR'])
    run = assets / 'runs' / args.name
    manifest = json.loads((run / 'manifest.json').read_text())
    capacity = json.loads((run / 'actual-capacity.json').read_text())
    assert manifest['topology'] == capacity['topology'] == TOPOLOGY
    assert manifest['checkpoint_ratio'] == capacity['checkpoint_ratio'] == .25
    assert manifest['mbt'] == capacity['mbt'] == TOPOLOGY[manifest['arm']]['mbt']
    # This new run must have pre-pressure process, host and capacity evidence.
    evidence = json.loads((run / 'configuration/prepressure-capture.json').read_text())
    assert evidence['status'] == 'passed' and evidence['workers'] == 16
    if manifest['arm'].startswith('afd'):
        graph = json.loads((run / 'configuration/ffn-0/native-graph-state-before.json').read_text())
        assert graph['status'] == 'passed' and graph['phase'] == 'before'
    prepared = assets / manifest['prepared']
    frozen = json.loads((prepared / 'manifest.json').read_text())
    assert frozen['max_length'] == capacity['max_model_len'] == manifest['max_model_len'] == MAX_LENGTH
    assert frozen['output_tokens'] == manifest['output_tokens'] == OUTPUT_TOKENS
    endpoints = json.loads((run / 'endpoints.json').read_text())
    assert len(endpoints) == len(capacity['domains']) == TOPOLOGY[manifest['arm']]['cache_domains']
    assert not (run / 'formal-start.json').exists() and not (run / 'formal-http').exists()
    # Record the running replay interpreter before reset or formal pressure.
    # This only adds evidence; payloads, scheduling and transport are unchanged.
    from launch_service import redact
    process = Path('/proc/self')
    actual = {'captured_at_ns': time.time_ns(), 'pid': os.getpid(),
        'start_ticks': (process / 'stat').read_text().rsplit(')', 1)[1].split()[19],
        'argv': (process / 'cmdline').read_bytes().decode().strip('\0').split('\0'),
        'environment': redact(dict(os.environ)),
        'executable': str((process / 'exe').resolve()),
        'status': (process / 'status').read_text(), 'cgroup': (process / 'cgroup').read_text(),
        'timing': 'before cold reset and formal-start.json'}
    (run / 'configuration/replay-client/actual-process.json').write_text(json.dumps(actual, indent=2) + '\n')
    start = {'prepared': manifest['prepared'], 'request_sha256': frozen['request_sha256'],
        'route_sha256': frozen['routes'][route_key(manifest['arm'])]['sha256'],
        'checkpoint_ratio': .25, 'concurrency': 16, 'mbt': manifest['mbt'], 'output_tokens': 1,
        'expected_requests': frozen['requests'], 'expected_sessions': frozen['sessions'],
        'reset': {}, 'observers': {}, 'execution_chain':
        'AgentInfer runner -> planner -> native dependency graph -> upstream streaming transport',
        'simulation_required': False,
        'execution_policy': 'Use approved SP/microbatch configuration directly; no separate qualification probes per user instruction',
        'metrics_scope': 'All native cache domains and all unique actual HTTP endpoints',
        'client_source_sha256': {name: hashlib.sha256((client / name).read_bytes()).hexdigest()
            for name in ('run_formal.py', 'agentinfer_frozen_replay.py', 'deterministic_runtime.py',
                         'random_priority_admission.py', 'replay_sse.py', 'three_arm_topology.py')}}
    start['idle_endpoint_metrics'] = snapshot_metrics(endpoints, run / 'all-endpoint-metrics',
                                                       'before-reset', require_idle=True)
    for url in sorted({e['url'] for e in endpoints.values()}):
        with urlopen(url + '/health', timeout=10) as response:
            assert response.status == 200
        with urlopen(Request(url + '/reset_prefix_cache', data=b'', method='POST'), timeout=30) as response:
            assert response.status == 200
            value = json.load(response)
            assert value['success'], value
            start['reset'][url] = value
    for domain in range(len(endpoints)):
        role, instance, dp = domain_worker(manifest['arm'], domain)
        path = run / f'{role}-{instance}-domain-{dp}.jsonl'
        baseline = {}
        for line in path.open():
            value = json.loads(line)
            if value['event'] == 'request_finished':
                baseline = value['counters']
        start['observers'][str(domain)] = {'file': path.name, 'offset': path.stat().st_size,
                                           'counters': baseline}
    start['endpoint_metrics'] = snapshot_metrics(endpoints, run / 'all-endpoint-metrics', 'start',
                                                require_idle=True)
    rows = [json.loads(line) for line in (prepared / 'requests.jsonl').open()]
    assert len(rows) == frozen['requests'] and len({r['session'] for r in rows}) == frozen['sessions']
    routes = json.loads((prepared / f'route-{route_key(manifest["arm"])}.json').read_text())['assignments']
    for row in rows:
        assert row['output_tokens'] == row['body']['max_tokens'] == row['body']['min_tokens'] == 1
        assert row['prompt_tokens'] + 1 <= MAX_LENGTH
        row['domain'] = routes[str(row['session'])]
    output = run / 'formal-http'
    output.mkdir()
    trace = output / 'agentinfer-ordering-trace.jsonl'
    prepare_trace(rows, trace)
    config = make_config(client, trace, output / 'agentinfer',
                         next(iter(endpoints.values()))['url'], frozen['sessions'])
    start['recorded_at'] = time.time()
    (run / 'formal-start.json').write_text(json.dumps(start, indent=2))
    try:
        summary = asyncio.run(execute(config, client, rows, endpoints, output))
        summary.update(request_sha256=frozen['request_sha256'], route_sha256=start['route_sha256'])
        (output / 'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    finally:
        end = {'recorded_at': time.time(), 'endpoints': snapshot_metrics(endpoints,
            run / 'all-endpoint-metrics', 'end')}
        (run / 'formal-end-metrics.json').write_text(json.dumps(end, indent=2))
    import sys
    sys.argv = [str(client / 'audit_native.py'), args.name]
    runpy.run_path(str(client / 'audit_native.py'), run_name='__main__')


if __name__ == '__main__':
    main()
