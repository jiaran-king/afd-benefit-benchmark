"""Frozen four-arm topology; service parameters are loaded from recorded evidence."""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "experiments/2026-10-11-async/recorded-configuration.json"
GROUPS = {
    "non_ep4": {"mbt":8192,"domains":4,"dp":1},
    "non_ep8": {"mbt":8192,"domains":4,"dp":2},
    "afd_eager": {"mbt":32768,"domains":3},
    "afd_fgraph": {"mbt":32768,"domains":3},
}
RUN_NAMES = {g:os.environ.get("BENCH_RUN_NAME",g+"-reproduction") for g in GROUPS}

def services_for(group):
    if group == "non_ep4":
        return [("nonafd",i,",".join(map(str,range(i*4,i*4+4))),8500+i,8600+i) for i in range(4)]
    if group == "non_ep8":
        return [("nonafd",i,",".join(map(str,range(i*8,i*8+8))),8500+i,8600+i) for i in range(2)]
    return [("ffn",0,"12,13,14,15",8511,8611),
            ("attention",0,",".join(map(str,range(12))),8510,8610)]

def endpoints_for(group):
    result={}
    for d in range(GROUPS[group]["domains"]):
        inst=d if group=="non_ep4" else d//2 if group=="non_ep8" else 0
        rank=d%2 if group=="non_ep8" else d if group.startswith("afd_") else 0
        port=8510 if group.startswith("afd_") else 8500+inst
        result[str(d)]={"url":f"http://127.0.0.1:{port}",
            "headers":{"X-data-parallel-rank":str(rank)},"instance":inst,"dp_rank":rank}
    return result

def additional_config(role, run, instance, group=None):
    group=group or os.environ["BENCH_GROUP"]
    value=json.loads(CONFIG.read_text())[f"{group}/{role}-{instance}"]["additional_config"]
    return json.loads(json.dumps(value).replace("$"+"{RUN_DIR}",str(run)))
