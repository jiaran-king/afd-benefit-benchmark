"""Offline validation of the four prefix-on C12 / 128 complete-session runs."""
import argparse
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import statistics

from recompute_results import read_csv, percentile

GROUPS = ('non_ep4', 'non_ep8', 'non_ep16', 'afd_eager')
SET = '2026-10-14-c12-128'


def validate(root, output=None):
    base = root / 'results' / SET
    data = root / 'datasets/frozen-128'
    frozen = json.loads((data / 'manifest.json').read_text())
    assert frozen['sessions'] == 128 and frozen['requests'] == 3725
    assert frozen['request_sha256'] == '65e10b43838be7bdf1f7459a07d34f1a57b64d05fa75fbf2b94f46efed6e86a4'
    index = {r['id']: r for r in read_csv(data / 'request-index.csv.gz')}
    parent = {r['id']: r for r in read_csv(root / 'datasets/frozen-256/request-index.csv.gz')}
    assert set(index) == {rid for rid, r in parent.items() if int(r['session']) < 128}
    assert all(all(index[rid][k] == v for k, v in r.items()) for rid, r in parent.items() if rid in index)
    assert hashlib.sha256((data / 'priorities.json').read_bytes()).hexdigest() == frozen['priorities_sha256']
    priority = json.loads((data / 'priorities.json').read_text())
    assert priority['positions'] == {rid: float(r['priority']) for rid, r in index.items()}
    assert frozen['max_prompt_tokens'] == max(int(r['prompt_tokens']) for r in index.values()) == 216178
    assert frozen['prompt_tokens'] == sum(int(r['prompt_tokens']) for r in index.values()) == 294584470
    maximum = {s: max(int(r['prompt_tokens']) for r in index.values() if int(r['session']) == s) for s in range(128)}
    routes = {}
    for kind, domains in [('afd', 3), ('nonafd', 4)]:
        path = data / f'route-{kind}.json'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen['routes'][kind]['sha256']
        route = json.loads(path.read_text())
        loads = [0] * domains
        expected_route = {}
        for s in sorted(maximum, key=lambda s: (-maximum[s], s)):
            d = min(range(domains), key=lambda d: (loads[d], d))
            expected_route[str(s)] = d
            loads[d] += maximum[s]
        assert route['assignments'] == expected_route
        assert loads == route['per_domain_max_history_sum'] == frozen['routes'][kind]['loads']
        routes[kind] = route['assignments']

    expected = {r['group']: r for r in read_csv(base / 'metrics.csv')}
    assert set(expected) == set(GROUPS)
    memory = read_csv(base / 'per-die-memory.csv')
    capacity = read_csv(base / 'per-domain-capacity.csv')
    audit = json.loads((base / 'audits/complete-runs.json').read_text())
    history = json.loads((base / 'run-history.json').read_text())
    config = json.loads((root / 'experiments' / SET / 'configuration-comparison.json').read_text())
    assert history['model_starts'] == 5 and history['complete_formal_runs'] == 4
    assert history['automatic_retries'] == history['failed_run']['formal_requests'] == 0
    assert history['formal_order'] == ['non_ep8', 'afd_eager', 'non_ep16', 'non_ep4']
    results = []
    requests = {}
    for group in GROUPS:
        rows = read_csv(base / f'requests/{group}.csv.gz')
        requests[group] = by_id = {r['id']: r for r in rows}
        assert len(rows) == len(by_id) == len(index) == 3725
        assert by_id.keys() == index.keys()
        assert {int(r['session']) for r in rows} == set(range(128))
        route = routes['afd' if group == 'afd_eager' else 'nonafd']
        for r in rows:
            assert all(r[k] == v for k, v in index[r['id']].items() if k != 'original_line_sha256')
            assert int(r['domain']) == route[r['session']]
            assert r['status'] == 'success' and r['done_marker'] == 'True' and r['finish_reason'] == 'length'
            assert int(r['output_tokens']) == int(r['observed_output_tokens']) == 1
            assert int(r['preemptions']) == 0
            assert int(r['cached_tokens']) + int(r['actual_prefill_tokens']) == int(r['prompt_tokens'])
            assert 0 <= float(r['ttft_seconds']) <= float(r['e2e_seconds']) + 1e-5
            assert math.isclose(float(r['completed_monotonic']) - float(r['send_started_monotonic']), float(r['e2e_seconds']), abs_tol=1e-6)
            if int(r['turn']):
                prev = by_id[f"source-{int(r['session']):04d}-turn-{int(r['turn'])-1:03d}"]
                assert float(r['send_started_monotonic']) >= float(prev['completed_monotonic'])
        for s in range(128):
            assert sorted(int(r['turn']) for r in rows if int(r['session']) == s) == list(range(sum(int(r['session']) == s for r in rows)))
        ready = [(float(r['priority']), r['id']) for r in rows if int(r['turn']) == 0]
        heapq.heapify(ready)
        active, finished = set(), set()
        peak = 0
        events = read_csv(base / f'events/{group}.csv.gz')
        assert len(events) == 2 * len(rows)
        for event in events:
            rid = event['id']
            assert all(event[k] == by_id[rid][k] for k in ['id', 'session', 'turn', 'domain', 'priority'])
            if event['event'] == 'admitted':
                assert rid not in active | finished
                assert rid == heapq.heappop(ready)[1], 'frozen ready priority differs'
                active.add(rid)
                peak = max(peak, len(active))
                assert peak <= 12
            elif event['event'] == 'finished':
                assert rid in active
                active.remove(rid)
                finished.add(rid)
                r = by_id[rid]
                nxt = f"source-{int(r['session']):04d}-turn-{int(r['turn'])+1:03d}"
                if nxt in by_id:
                    heapq.heappush(ready, (float(by_id[nxt]['priority']), nxt))
            else:
                raise AssertionError('unexpected admission event')
        assert finished == set(by_id) and not active and not ready and peak == 12
        intervals = sorted((float(r[key]), delta) for r in rows for key, delta in [('send_started_monotonic', 1), ('completed_monotonic', -1)])
        count = http_peak = 0
        for _, delta in intervals:
            count += delta
            http_peak = max(http_peak, count)
            assert 0 <= count <= 12
        assert count == 0 and http_peak == 12
        mem = [r for r in memory if r['group'] == group]
        assert len(mem) == 16 and {int(r['die']) for r in mem} == set(range(16))
        domains = [r for r in capacity if r['group'] == group]
        assert {int(r['domain']) for r in domains} == set(range(3 if group == 'afd_eager' else 4))
        kv = sum(float(r['kv_actual_gib'] or 0) for r in mem)
        assert math.isclose(kv, sum(int(r['actual_unique_storage_bytes']) for r in domains) / 2**30, abs_tol=1e-7)
        result = dict(group=group, concurrency=12, sessions=128, requests=len(rows))
        for key in ['prompt_tokens', 'cached_tokens', 'actual_prefill_tokens', 'preemptions']:
            result[key] = sum(int(r[key]) for r in rows)
        result['hit_rate'] = result['cached_tokens'] / result['prompt_tokens']
        result['recompute_tokens'] = result['actual_prefill_tokens'] - (result['prompt_tokens'] - result['cached_tokens'])
        result['duration_seconds'] = max(float(r['completed_monotonic']) for r in rows) - min(float(r['send_started_monotonic']) for r in rows)
        result['duration_minutes'] = result['duration_seconds'] / 60
        result['requests_per_second'] = len(rows) / result['duration_seconds']
        result['actual_unique_kv_gib'] = kv
        for name, condition in [('first_turn_prefill_tokens', lambda r: int(r['turn']) == 0), ('continuation_prefill_tokens', lambda r: int(r['turn']) > 0)]:
            result[name] = sum(int(r['actual_prefill_tokens']) for r in rows if condition(r))
        result['mean_http_inflight'] = sum(float(r['e2e_seconds']) for r in rows) / result['duration_seconds']
        for prefix, field in [('ttft', 'ttft_seconds'), ('e2e', 'e2e_seconds')]:
            values = [float(r[field]) for r in rows]
            result[prefix + '_mean'] = statistics.mean(values)
            for label, q in [('p50', .5), ('p95', .95), ('p99', .99)]:
                result[prefix + '_' + label] = percentile(values, q)
        assert set(result) == set(expected[group])
        for k, v in result.items():
            assert k == 'group' or math.isclose(v, float(expected[group][k]), rel_tol=1e-10, abs_tol=1e-7), (group, k)
        summary = json.loads((base / f'summaries/{group}.json').read_text())
        assert summary['run_id'] == history['formal_runs'][group]
        assert summary['audit_status'] == 'complete' and summary['execution_audit']['status'] == 'passed'
        for k in ['requests', 'prompt_tokens', 'cached_tokens', 'actual_prefill_tokens', 'preemptions']:
            assert summary['native_totals'][k] == result[k]
        assert config[group]['status'] == 'passed' and not config[group]['errors']
        assert all(not x for x in config[group]['normalized_argv_differences'].values())
        assert config[group]['model_files'] == frozen['model_files']
        pre = audit[group]['prepressure']
        assert pre['status'] == 'passed' and pre['workers'] == 16 and pre['captured_before_pressure']
        assert pre['successful_cold_reset_endpoints'] == {'non_ep4': 4, 'non_ep8': 2, 'non_ep16': 1, 'afd_eager': 1}[group]
        assert pre['native_domain_baselines'] == len(domains)
        assert set(pre['scheduler_classes']) == {'CompressorCheckpointAsyncScheduler'}
        results.append(result)
        print(f"{group}: 3725 requests, C12 priority/dependency/route and metrics passed; {result['duration_seconds']:.6f} s")
    paired = json.loads((base / 'simulation-vs-actual.json').read_text())['real_pairwise_vs_afd']
    for g in GROUPS:
        delta = [int(r['cached_tokens']) - int(requests['afd_eager'][rid]['cached_tokens']) for rid, r in requests[g].items()]
        assert paired[g]['different_cache_requests'] == sum(d != 0 for d in delta)
        assert paired[g]['cached_tokens_minus_afd'] == sum(delta)
        if g in ['non_ep8', 'non_ep16']:
            assert not any(delta)
    assert len(memory) == 64 and len(capacity) == 15
    figures = read_csv(base / 'figures/four-arm-figure-data.csv')
    assert [r['group'] for r in figures] == list(GROUPS)
    for figure in figures:
        metric = expected[figure['group']]
        for field, value in {
            'kv_gib': float(metric['actual_unique_kv_gib']),
            'cache_pct': float(metric['hit_rate']) * 100,
            'prefill_tokens': int(metric['actual_prefill_tokens']),
            'prefill_million': int(metric['actual_prefill_tokens']) / 1e6,
            'duration_seconds': float(metric['duration_seconds']),
            'duration_minutes': float(metric['duration_seconds']) / 60,
        }.items():
            assert math.isclose(float(figure[field]), value, rel_tol=1e-10, abs_tol=1e-7)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]))
            w.writeheader()
            w.writerows(results)
    print('PASS: 14,900 requests, 29,800 admission events, exact parent subset, 64 DIE, 15 domains and pairwise cache equality')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    validate(Path(__file__).resolve().parents[1], args.output)
