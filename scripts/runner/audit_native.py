"""Join HTTP results to actual cache domains and scheduled prefill work."""
from collections import Counter
import json
import heapq
import os
from pathlib import Path
import re
import sys

assets = Path(os.environ["BENCH_WORK_DIR"])
arm = assets / "runs" / sys.argv[1]
manifest = json.loads((arm / "manifest.json").read_text())
start = json.loads((arm / "formal-start.json").read_text())
http = json.loads((arm / "formal-http/summary.json").read_text())
capacity = json.loads((arm / "actual-capacity.json").read_text())
assert manifest["checkpoint_ratio"] == start["checkpoint_ratio"] == capacity["checkpoint_ratio"] == .25
assert manifest["mbt"] == start["mbt"] == capacity["mbt"] and manifest["mbt"] in (8192, 32768, 65536)
assert http["status"] == "complete" and http["request_sha256"] == start["request_sha256"]
assert http["route_sha256"] == start["route_sha256"] and http["concurrency"] == 16
records = {row["id"]: row for row in map(json.loads, (arm / "formal-http/requests.jsonl").read_text().splitlines())}
prepared_manifest = json.loads((assets / start["prepared"] / "manifest.json").read_text())
assert len(records) == http["requests"] == http["successful"] == prepared_manifest["requests"]
assert len({r["session"] for r in records.values()}) == prepared_manifest["sessions"]
totals = Counter()
seen = set()
domains = []
for domain, observer in start["observers"].items():
    counts, misses, evictions = Counter(), Counter(), Counter()
    final = None
    with (arm / observer["file"]).open() as stream:
        stream.seek(observer["offset"])
        for line in stream:
            row = json.loads(line)
            if row["event"] == "checkpoint_evicted":
                evictions[row["reason"]] += 1
            if row["event"] != "request_finished":
                continue
            match = re.fullmatch(r"cmpl-(source-\d+-turn-\d+)-0-[0-9a-f]+", row["request_id"])
            assert match, row["request_id"]
            rid = match[1]
            assert rid in records and rid not in seen
            seen.add(rid)
            record = records[rid]
            assert record["domain"] == int(domain) and record["status"] == "success"
            assert record["prompt_tokens"] == row["prompt_tokens"]
            assert record["usage"]["prompt_tokens_details"]["cached_tokens"] == row["cached_tokens"]
            assert row["output_tokens"] == record["output_tokens"] == manifest["output_tokens"] == 1
            if row["preemptions"] == 0:
                assert row["actual_prefill_tokens"] == row["prompt_tokens"] - row["cached_tokens"]
            counts["requests"] += 1
            for field in ("prompt_tokens", "cached_tokens", "actual_prefill_tokens", "preemptions"):
                counts[field] += row[field]
            lookup = row.get("lookup") or {}
            if lookup.get("checkpoint_limits_joint_hit"):
                misses["checkpoint_limited_requests"] += 1
                misses["checkpoint_limited_" + str(lookup.get("limiting_checkpoint_evicted_reason"))] += 1
            if lookup.get("ordinary_joint_hit") == 0 and lookup.get("ready_checkpoint_candidate"):
                misses["ready_checkpoint_but_ordinary_miss"] += 1
            if record["turn"] > 0 and row["cached_tokens"] == 0:
                misses["continuation_zero_cached"] += 1
            final = row
    assert final and counts["requests"] > 0
    counts["hit_rate"] = counts["cached_tokens"] / counts["prompt_tokens"]
    baseline = observer["counters"]
    fields = ("ordinary_cached_block_evictions", "checkpoint_created", "restore_plans",
        "admission_allocation_failed_attempts", "lookup_observation_microseconds")
    counter_delta = {field: final["counters"].get(field, 0) - baseline.get(field, 0) for field in fields}
    assert all(value >= 0 for value in counter_delta.values())
    for key in ("requests", "prompt_tokens", "cached_tokens", "actual_prefill_tokens", "preemptions"):
        totals[key] += counts[key]
    domains.append({"domain": int(domain), "totals": dict(counts), "miss_evidence": dict(misses),
        "checkpoint_evictions": dict(evictions), "formal_counters": counter_delta,
        "pool_min_free_in_process": final["min_free_blocks"], "pool_peak_in_process": final["peak"]})
assert seen == set(records)
ready = [(r['priority'], rid) for rid, r in records.items() if r['turn'] == 0]
heapq.heapify(ready)
inflight, finished, peak_concurrency = set(), set(), 0
for event in map(json.loads, (arm / 'formal-http/events.jsonl').open()):
    rid = event['id']
    if event['event'] == 'admitted':
        assert rid not in inflight | finished and rid == heapq.heappop(ready)[1]
        inflight.add(rid)
        peak_concurrency = max(peak_concurrency, len(inflight))
        assert len(inflight) <= 16
    elif event['event'] == 'finished':
        assert event['success'] and rid in inflight and rid not in finished
        inflight.remove(rid)
        finished.add(rid)
        row = records[rid]
        successor = f"source-{row['session']:04d}-turn-{row['turn'] + 1:03d}"
        if successor in records:
            heapq.heappush(ready, (records[successor]['priority'], successor))
assert finished == set(records) and not inflight and not ready
totals["hit_rate"] = totals["cached_tokens"] / totals["prompt_tokens"]
result = {"arm": manifest["arm"], "status": "complete", "actual_dp_and_work_audit": "passed",
    "requests": http["requests"], "totals": dict(totals), "domains": domains,
    "timing": {key: http[key] for key in ("duration_seconds", "ttft_p95", "e2e_p95", "concurrency")},
    "request_sha256": http["request_sha256"], "route_sha256": http["route_sha256"],
    "prepared": start["prepared"], "checkpoint_ratio": .25, "mbt": manifest["mbt"],
    "capacity": json.loads((arm / "actual-capacity.json").read_text()),
    "execution_audit": {"status": "passed", "peak_inflight_requests": peak_concurrency,
        "request_limit": 16, "dependency_order_and_ready_priority": "passed"}}
(arm / "formal-audit.json").write_text(json.dumps(result, indent=2))
print(json.dumps({key: value for key, value in result.items() if key not in ("domains", "capacity")}))
