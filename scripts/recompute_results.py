"""Recompute formal metrics and validate every frozen request and admission event offline."""
import argparse
import csv
import gzip
import heapq
import json
import math
from pathlib import Path
import statistics

REPO=Path(__file__).resolve().parents[1]
ORIGINAL_GROUPS=("non_ep4","non_ep8","afd_eager","afd_fgraph")
GROUPS=("non_ep4","non_ep8","non_ep16","afd_eager","afd_fgraph")

def result_dir(group,root=REPO):
    return root/"results"/("2026-10-12-ep16" if group=="non_ep16" else "2026-10-11")

def read_csv(path):
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",newline="") as f:
        return list(csv.DictReader(f))

def percentile(values,q):
    s=sorted(values);x=(len(s)-1)*q;i=int(x)
    return s[i]+(s[min(i+1,len(s)-1)]-s[i])*(x-i)

def validate_group(group, root=REPO):
    base=result_dir(group,root)
    rows=read_csv(base/f"requests/{group}.csv.gz")
    index={r["id"]:r for r in read_csv(root/"datasets/frozen-256/request-index.csv.gz")}
    frozen=json.loads((root/"datasets/frozen-256/manifest.json").read_text())
    route=json.loads((root/f"datasets/frozen-256/route-{'afd' if group.startswith('afd') else 'nonafd'}.json").read_text())["assignments"]
    assert len(rows)==len(index)==9078 and len({r["id"] for r in rows})==len(rows)
    by_id={r["id"]:r for r in rows}
    for r in rows:
        expected=index[r["id"]]
        for key,value in expected.items():
            assert r[key]==value,(group,r["id"],key)
        assert int(r["domain"])==route[r["session"]]
        assert r["status"]=="success" and r["done_marker"]=="True" and r["finish_reason"]=="length"
        assert int(r["observed_output_tokens"])==int(r["output_tokens"])==1
        assert int(r["preemptions"])==0
        assert int(r["cached_tokens"])+int(r["actual_prefill_tokens"])==int(r["prompt_tokens"])
        assert 0<=float(r["ttft_seconds"])<=float(r["e2e_seconds"])+1e-5
        assert math.isclose(float(r["completed_monotonic"])-float(r["send_started_monotonic"]),
                            float(r["e2e_seconds"]),abs_tol=1e-6)
        if int(r["turn"]):
            previous=by_id[f"source-{int(r['session']):04d}-turn-{int(r['turn'])-1:03d}"]
            assert float(r["send_started_monotonic"])>=float(previous["completed_monotonic"])
    ready=[(float(r["priority"]),r["id"]) for r in rows if r["turn"]=="0"]
    heapq.heapify(ready)
    active=set();finished=set();peak=0
    events=read_csv(base/f"events/{group}.csv.gz")
    assert len(events)==2*len(rows)
    for e in events:
        rid=e["id"]
        assert all(e[k]==by_id[rid][k] for k in ("id","session","turn","domain","priority"))
        if e["event"]=="admitted":
            assert rid not in active|finished
            assert rid==heapq.heappop(ready)[1],"frozen ready priority violated"
            active.add(rid);peak=max(peak,len(active));assert peak<=16
        elif e["event"]=="finished":
            assert rid in active
            active.remove(rid);finished.add(rid)
            r=by_id[rid];successor=f"source-{int(r['session']):04d}-turn-{int(r['turn'])+1:03d}"
            if successor in by_id:
                heapq.heappush(ready,(float(by_id[successor]["priority"]),successor))
        else:
            raise AssertionError("unexpected event")
    assert finished==set(by_id) and not active and not ready and peak==16
    # Independently check actual HTTP intervals as well as admission event order.
    intervals=sorted((float(r[key]),delta) for r in rows for key,delta in
        (("send_started_monotonic",1),("completed_monotonic",-1)))
    inflight=0;http_peak=0
    for _,delta in intervals:
        inflight+=delta;http_peak=max(http_peak,inflight)
        assert 0<=inflight<=16
    assert inflight==0 and http_peak==16
    result={"group":group,"sessions":len({r["session"] for r in rows}),"requests":len(rows)}
    for field in ("prompt_tokens","cached_tokens","actual_prefill_tokens","preemptions"):
        result[field]=sum(int(r[field]) for r in rows)
    assert result["prompt_tokens"]==frozen["prompt_tokens"]
    result["hit_rate"]=result["cached_tokens"]/result["prompt_tokens"]
    result["recompute_tokens"]=result["actual_prefill_tokens"]-(result["prompt_tokens"]-result["cached_tokens"])
    result["duration_seconds"]=max(float(r["completed_monotonic"]) for r in rows)-min(float(r["send_started_monotonic"]) for r in rows)
    result["requests_per_second"]=len(rows)/result["duration_seconds"]
    for short,field in (("ttft","ttft_seconds"),("e2e","e2e_seconds")):
        values=[float(r[field]) for r in rows]
        result[short+"_mean"]=statistics.mean(values)
        for label,q in (("p50",.5),("p95",.95),("p99",.99)):
            result[short+"_"+label]=percentile(values,q)
    result["continuation_zero_cached"]=sum(int(r["turn"])>0 and int(r["cached_tokens"])==0 for r in rows)
    memory=[r for r in read_csv(base/"per-die-memory.csv") if r["group"]==group]
    assert len(memory)==16 and {int(r["die"]) for r in memory}==set(range(16))
    result["total_actual_unique_kv_gib"]=sum(int(float(r["kv_actual_bytes"] or 0)) for r in memory)/2**30
    summary=json.loads((base/f"summaries/{group}.json").read_text())
    result["restores"]=sum(d["formal_counters"]["restore_plans"] for d in summary["domains"])
    return result

def validate_five_group_tables(results,root=REPO):
    """Check the merged view and report inputs against the separate original runs."""
    base=root/"results/2026-10-12-ep16"
    merged={r["group"]:r for r in read_csv(base/"metrics.csv")}
    assert set(merged)==set(GROUPS)
    for row in read_csv(root/"results/2026-10-11/metrics.csv"):
        for key,value in row.items():
            assert merged[row["group"]][key]==value,("original metric changed",row["group"],key)
    for name,identity in (("per-die-memory.csv","die"),("per-domain-capacity.csv","domain")):
        new={(r["group"],r[identity]):r for r in read_csv(base/name)}
        assert len(new)==(80 if identity=="die" else 18)
        for old in read_csv(root/"results/2026-10-11"/name):
            assert all(new[(old["group"],old[identity])][k]==v for k,v in old.items()),(name,old["group"],old[identity])
    by_group={r["group"]:r for r in results}
    figures=read_csv(base/"figures/five-arm-figure-data.csv")
    assert [r["group"] for r in figures]==list(GROUPS)
    for fig in figures:
        r=by_group[fig["group"]]
        expected={"prompt_tokens":r["prompt_tokens"],"kv_gib":r["total_actual_unique_kv_gib"],
                  "cached_tokens":r["cached_tokens"],"cache_pct":r["hit_rate"]*100,
                  "prefill_tokens":r["actual_prefill_tokens"],"prefill_million":r["actual_prefill_tokens"]/1e6,
                  "prefill_pct":(r["prompt_tokens"]-r["cached_tokens"])/r["prompt_tokens"]*100,
                  "recompute_tokens":r["recompute_tokens"],"duration_minutes":r["duration_seconds"]/60}
        assert all(math.isclose(float(fig[k]),v,rel_tol=1e-10,abs_tol=1e-7) for k,v in expected.items()),fig["group"]
    ep16={r["id"]:float(r["e2e_seconds"]) for r in read_csv(base/"requests/non_ep16.csv.gz")}
    paired=read_csv(base/"paired-ep16.csv")
    assert {r["base"] for r in paired}==set(ORIGINAL_GROUPS) and len(paired)==4
    for pair in paired:
        other={r["id"]:float(r["e2e_seconds"]) for r in read_csv(result_dir(pair["base"],root)/f"requests/{pair['base']}.csv.gz")}
        assert other.keys()==ep16.keys() and pair["candidate"]=="non_ep16"
        ratios=[ep16[rid]/other[rid] for rid in ep16]
        assert int(pair["ep16_faster_requests"])==sum(ep16[rid]<other[rid] for rid in ep16)
        assert int(pair["ep16_slower_requests"])==sum(ep16[rid]>other[rid] for rid in ep16)
        for key,q in (("paired_e2e_ratio_median",.5),("paired_e2e_ratio_p95",.95)):
            assert math.isclose(float(pair[key]),percentile(ratios,q),rel_tol=1e-10)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path)
    p.add_argument("--result-set",choices=("2026-10-11","2026-10-12-ep16","2026-10-14-c12-128"),default="2026-10-12-ep16",
                   help="The original five-group table remains the default; select 2026-10-14-c12-128 for the new C12 workload.")
    a=p.parse_args()
    if a.result_set=="2026-10-14-c12-128":
        from recompute_c12_128 import validate
        validate(REPO,a.output)
        return
    expected={r["group"]:r for r in read_csv(REPO/"results"/a.result_set/"metrics.csv")}
    results=[]
    for group in ORIGINAL_GROUPS if a.result_set=="2026-10-11" else GROUPS:
        row=validate_group(group)
        for key,value in row.items():
            if key=="group":
                continue
            if key=="recompute_tokens" and not expected[group].get(key):
                assert value==0  # Original four-run metric table omitted this derived field.
                continue
            assert math.isclose(value,float(expected[group][key]),rel_tol=1e-10,abs_tol=1e-7),(group,key,value,expected[group][key])
        results.append(row)
        print(f"{group}: 9078 requests passed; {row['duration_seconds']:.6f} s")
    if a.result_set=="2026-10-12-ep16":
        validate_five_group_tables(results)
        print("Five-group table, original four-run values, figure inputs and EP16 paired latencies passed")
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(results[0]))
            writer.writeheader();writer.writerows(results)
    print(f"PASS: {sum(r['requests'] for r in results):,} requests, frozen identities, domain affinity, session dependencies, C16 ready priority, all recomputed metrics")

if __name__=="__main__":
    main()
