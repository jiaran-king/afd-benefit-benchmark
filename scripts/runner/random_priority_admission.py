"""Fixed random priorities among ready requests; no per-domain serialization."""
import asyncio
import random
import time


def priorities(request_ids, seed):
    ids = sorted(request_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Request IDs must be nonempty and unique')
    random.Random(seed).shuffle(ids)
    return {rid: rank for rank, rid in enumerate(ids)}


class PriorityAdmission:
    def __init__(self, ranks, concurrency, record):
        if concurrency < 1:
            raise ValueError('Concurrency must be positive')
        self.ranks = ranks
        self.limit = concurrency
        self.record = record
        self.condition = asyncio.Condition()
        self.pending = {}
        self.active = set()
        self.finished = set()
        self.fatal = None

    async def abort(self, reason):
        async with self.condition:
            self.fatal = self.fatal or reason
            self.condition.notify_all()

    async def run(self, session_id, request_id, send):
        queued = time.monotonic()
        admitted = False
        try:
            async with self.condition:
                if request_id not in self.ranks or request_id in self.pending or request_id in self.active or request_id in self.finished:
                    raise ValueError('Unknown or duplicate request: ' + request_id)
                self.pending[request_id] = self.ranks[request_id]
                self.condition.notify_all()
            # Coalesce coroutines already ready in this event-loop turn.
            await asyncio.sleep(0)
            async with self.condition:
                await self.condition.wait_for(lambda: self.fatal or (
                    len(self.active) < self.limit and request_id == min(self.pending, key=self.pending.get)))
                if self.fatal:
                    raise RuntimeError(self.fatal)
                del self.pending[request_id]
                self.active.add(request_id)
                admitted = True
                self.record({'event': 'admitted', 'request_id': request_id, 'session_id': session_id,
                             'priority': self.ranks[request_id], 'queued_monotonic': queued,
                             'admitted_monotonic': time.monotonic(), 'active': len(self.active)})
                self.condition.notify_all()
            result = await send()
            if not result.success:
                raise RuntimeError(f'{request_id}: transport failed: {result.error}')
            self.finished.add(request_id)
            self.record({'event': 'finished', 'request_id': request_id,
                         'finished_monotonic': time.monotonic(), 'success': True})
            return result
        except BaseException as exc:
            await self.abort(f'{request_id}: {type(exc).__name__}: {exc}')
            self.record({'event': 'finished', 'request_id': request_id, 'success': False,
                         'finished_monotonic': time.monotonic(), 'error': self.fatal})
            raise
        finally:
            async with self.condition:
                self.pending.pop(request_id, None)
                if admitted:
                    self.active.remove(request_id)
                self.condition.notify_all()

    def verify_complete(self):
        if self.fatal or self.active or self.pending or self.finished != set(self.ranks):
            raise RuntimeError(f'Incomplete priority replay: {len(self.finished)}/{len(self.ranks)}; {self.fatal}')
