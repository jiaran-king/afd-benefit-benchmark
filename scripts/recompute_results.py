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
GROUPS=("non_ep4","non_ep8","afd_eager","afd_fgraph")

def read_csv(path):
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",newline="") as f:
        return list(csv.DictReader(f))

def percentile(values,q):
    s=sorted(values);x=(len(s)-1)*q;i=int(x)
    return s[i]+(s[min(i+1,len(s)-1)]-s[i])*(x-i)

def validate_group(group, root=REPO):
    base=root/"results/2026-10-11"
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
    result={"group":group,"sessions":len({r["session"] for r in rows}),"requests":len(rows)}
    for field in ("prompt_tokens","cached_tokens","actual_prefill_tokens","preemptions"):
        result[field]=sum(int(r[field]) for r in rows)
    assert result["prompt_tokens"]==frozen["prompt_tokens"]
    result["hit_rate"]=result["cached_tokens"]/result["prompt_tokens"]
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

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    expected={r["group"]:r for r in read_csv(REPO/"results/2026-10-11/metrics.csv")}
    results=[]
    for group in GROUPS:
        row=validate_group(group)
        for key,value in row.items():
            if key=="group":
                continue
            assert math.isclose(value,float(expected[group][key]),rel_tol=1e-10,abs_tol=1e-7),(group,key,value,expected[group][key])
        results.append(row)
        print(f"{group}: 9078 requests passed; {row['duration_seconds']:.6f} s")
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(results[0]))
            writer.writeheader();writer.writerows(results)
    print("PASS: 36,312 requests, frozen identities, domain affinity, session dependencies, C16 ready priority, all published metrics")

if __name__=="__main__":
    main()
