"""AgentInfer executor/transport adaptations for frozen per-P admission.

These classes keep the upstream planner, prompt builder, ReplayExecutor graph,
ReplayTransport streaming HTTP, and request writer in the execution path.
They do not configure authorization or perform network calls on import.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Awaitable, Callable, TypeVar

from agentinfer.agentbench.replay.executor import ReplayExecutor
from agentinfer.agentbench.replay.transport import ReplayTransport

T = TypeVar('T')


class FrozenOrderAdmission:
    """One deterministic queue and one complete-response slot per P domain."""

    def __init__(self, rank_map: dict[str, int], order: dict[str, list[str]], record=None):
        if not rank_map or set(order) != {'0', '1', '2', '3'}:
            raise ValueError('four P ranks and an explicit session affinity map are required')
        all_ids = [request_id for sequence in order.values() for request_id in sequence]
        if not all_ids or len(all_ids) != len(set(all_ids)):
            raise ValueError('frozen order must contain globally unique requests')
        if any(not sequence for sequence in order.values()):
            raise ValueError('every P rank needs a nonempty order')
        if any(type(rank) is not int or rank not in range(4) for rank in rank_map.values()):
            raise ValueError('invalid session rank')
        self.rank_map = dict(rank_map)
        self.order = {rank: tuple(sequence) for rank, sequence in order.items()}
        self.members = {rank: frozenset(sequence) for rank, sequence in self.order.items()}
        self.next_index = {rank: 0 for rank in self.order}
        self.conditions = {rank: asyncio.Condition() for rank in self.order}
        self.active = {rank: False for rank in self.order}
        self.fatal: str | None = None
        self.record = record

    async def abort(self, reason: str) -> None:
        if self.fatal is None:
            self.fatal = reason
        for condition in self.conditions.values():
            async with condition:
                condition.notify_all()

    async def run(self, session_id: str, request_id: str, send: Callable[[], Awaitable[T]]) -> T:
        if session_id not in self.rank_map:
            raise ValueError(f'session missing affinity: {session_id}')
        rank = str(self.rank_map[session_id])
        if request_id not in self.members[rank]:
            raise ValueError(f'request {request_id} missing from rank {rank} order')
        condition = self.conditions[rank]
        queued_at = time.monotonic()
        async with condition:
            while True:
                if self.fatal:
                    raise RuntimeError('admission aborted: ' + self.fatal)
                if self.next_index[rank] >= len(self.order[rank]):
                    raise RuntimeError(f'rank {rank} order exhausted')
                if self.order[rank][self.next_index[rank]] == request_id and not self.active[rank]:
                    self.active[rank] = True
                    break
                await condition.wait()
        admitted_at = time.monotonic()
        success = False
        try:
            if self.record is not None:
                self.record({'event': 'admitted', 'request_id': request_id, 'session_id': session_id,
                             'rank': int(rank), 'queued_monotonic': queued_at,
                             'admitted_monotonic': admitted_at, 'order_index': self.next_index[rank]})
            result = await send()
            success = bool(getattr(result, 'success', False))
            if not success:
                await self.abort(f'{request_id}: unsuccessful transport result')
            return result
        except BaseException as exc:
            await self.abort(f'{request_id}: {type(exc).__name__}: {exc}')
            raise
        finally:
            finished_at = time.monotonic()
            async with condition:
                self.active[rank] = False
                if success:
                    self.next_index[rank] += 1
                condition.notify_all()
            if self.record is not None:
                try:
                    self.record({'event': 'finished', 'request_id': request_id, 'session_id': session_id,
                                 'rank': int(rank), 'finished_monotonic': finished_at,
                                 'success': success})
                except BaseException as exc:
                    await self.abort(f'{request_id}: finished audit failed: {type(exc).__name__}: {exc}')
                    raise

    def verify_complete(self) -> None:
        if self.fatal:
            raise RuntimeError('admission aborted: ' + self.fatal)
        incomplete = {rank: (self.next_index[rank], len(sequence))
                      for rank, sequence in self.order.items()
                      if self.next_index[rank] != len(sequence) or self.active[rank]}
        if incomplete:
            raise RuntimeError(f'frozen order incomplete: {incomplete}')


class OrderedReplayTransport(ReplayTransport):
    """Use the original AgentInfer streaming send after frozen admission."""

    frozen_order: dict[str, list[str]] | None = None
    admission_record = None

    def __init__(self, config, run_id, writer):
        super().__init__(config, run_id, writer)
        if self.frozen_order is None or config.backend.dp_rank_map is None:
            raise ValueError('frozen order and dp_rank_map are required')
        self.admission = FrozenOrderAdmission(config.backend.dp_rank_map,
                                              self.frozen_order, self.admission_record)

    async def send(self, task, node, prompt):
        return await self.admission.run(
            task.runtime_session_id, node.runtime_request_id,
            lambda: super(OrderedReplayTransport, self).send(task, node, prompt))

    async def abort(self, reason):
        await self.admission.abort(reason)


class ConcurrentReplayExecutor(ReplayExecutor):
    """Let all sessions enter the original dependency graph; bound only build work."""

    prompt_preparation_limit = 8
    progress_watchdog = None

    async def execute(self):
        if self.prompt_preparation_limit < 1:
            raise ValueError('prompt_preparation_limit must be positive')
        semaphore = asyncio.Semaphore(self.prompt_preparation_limit)
        original_build = self.prompts.build

        async def bounded_build(task, node, exchange):
            async with semaphore:
                return await original_build(task, node, exchange)

        self.prompts.build = bounded_build

        async def one_task(task):
            enqueued = time.monotonic()
            result = await self._execute_task(task)
            return replace(result, enqueued_clock=enqueued,
                           permit_acquired_clock=enqueued,
                           finished_clock=time.monotonic(), permit_wait_seconds=0.0)

        group = asyncio.gather(*(one_task(task) for task in self.plan.tasks))
        watchdog = (asyncio.create_task(self.progress_watchdog.monitor())
                    if self.progress_watchdog is not None else None)
        try:
            if watchdog is None:
                results = tuple(await group)
            else:
                done, _ = await asyncio.wait((group, watchdog), return_when=asyncio.FIRST_COMPLETED)
                if watchdog in done:
                    # A watchdog failure must cancel the actual AgentInfer
                    # graph, not merely write an alert while it keeps running.
                    error = watchdog.exception()
                    if error is None:
                        raise RuntimeError('watchdog exited before replay completed')
                    raise error
                results = tuple(group.result())
            if any(result.status != 'completed' for result in results):
                raise RuntimeError('one or more AgentInfer sessions failed')
            self.transport.admission.verify_complete()
            return results
        except BaseException as exc:
            await self.transport.abort(f'executor failed: {type(exc).__name__}: {exc}')
            raise
        finally:
            group.cancel()
            if watchdog is not None:
                watchdog.cancel()
            await asyncio.gather(group, *( (watchdog,) if watchdog is not None else ()), return_exceptions=True)
            self.prompts.build = original_build

    async def _execute_node(self, task, node, task_started, root_prompts, completions, results):
        before = len(results)
        await super()._execute_node(task, node, task_started, root_prompts, completions, results)
        # The parent converts ordinary node failures to result rows. Detect
        # them here, including failures before transport.send is ever reached.
        for result in results[before:]:
            if result.runtime_request_id == node.runtime_request_id and result.status != 'success':
                await self.transport.abort(f'node {node.runtime_request_id}: {result.status}: {result.error}')
