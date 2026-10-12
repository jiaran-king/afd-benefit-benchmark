import hashlib
import json
import os
from pathlib import Path
import sys

from layout_identity import layout_identity
from three_arm_topology import TOPOLOGY as PAIR_TOPOLOGY, domain_worker

assets = Path(os.environ["BENCH_WORK_DIR"])
run = assets / "runs" / sys.argv[1]
manifest = json.loads((run / "manifest.json").read_text())
assert manifest["topology"] == PAIR_TOPOLOGY
assert manifest["purpose"] == "formal_closeout_9078_unified_compressor_host"
assert manifest["mbt"] == PAIR_TOPOLOGY[manifest["arm"]]["mbt"]
assert manifest["checkpoint_ratio"] == .25 and manifest["mbt"] in (8192, 32768, 65536)
assert manifest["total_die"] == 16 and manifest["capacity"] == "natural"
expected_domains = PAIR_TOPOLOGY[manifest["arm"]]["cache_domains"]
domains = []
for domain in range(expected_domains):
    role, instance, dp = domain_worker(manifest["arm"], domain)
    workers = [json.loads((run / f"{role}-{instance}-capacity-{dp}-{tp}.json").read_text()) for tp in range(4)]
    for worker in workers:
        assert worker["prefix_cache"] and worker["shared_compressor_workspace"]
        assert worker["async_scheduling"] and not worker["speculative"] and not worker["kv_transfer"]
        assert worker["checkpoint_ratio"] == .25 and worker["checkpoint_page_groups"]
        assert worker['flashcomm1_effective'] and worker['shared_expert_dp_effective']
        assert worker["max_model_len"] == manifest["max_model_len"] and worker["mbt"] == manifest["mbt"] and worker["max_num_seqs"] == 8
    identity = layout_identity(workers[0]["groups"])
    assert all(worker["N"] == workers[0]["N"] and worker["stride"] == workers[0]["stride"]
        and layout_identity(worker["groups"]) == identity for worker in workers)
    with (run / f"{role}-{instance}-domain-{dp}.jsonl").open() as stream:
        scheduler = json.loads(next(stream))
    assert scheduler["event"] == "capacity" and scheduler["N"] == workers[0]["N"]
    assert scheduler["B"] == int(scheduler["N"] * .25) and scheduler["R"] > 0 and scheduler["alignment"] == 4096
    assert scheduler["capacity"] == scheduler["B"] // scheduler["R"]
    domains.append({"domain": domain, "N": scheduler["N"], "B": scheduler["B"], "R": scheduler["R"],
        "max_checkpoints": scheduler["capacity"], "alignment": scheduler["alignment"],
        "planned_backing_bytes": workers[0]["planned_backing_bytes"], "stride": workers[0]["stride"],
        "layout_identity": identity, "runner": workers[0]["runner"],
        "actual_unique_storage_bytes_per_tp": [worker["actual_unique_storage_bytes"] for worker in workers]})
model = Path(os.environ["MODEL_DIR"])
files = {name: hashlib.sha256((model / name).read_bytes()).hexdigest()
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json")}
assert files == json.loads((assets / manifest["prepared"] / "manifest.json").read_text())["model_files"]
result = {"arm": manifest["arm"], "capacity_source": "measured allocation with matching worker/scheduler identity",
    "domains": domains, "topology": PAIR_TOPOLOGY, "model_files": files, "model_resolved_path": str(model.resolve()),
    "max_model_len": manifest["max_model_len"], "mbt": manifest["mbt"], "checkpoint_ratio": .25,
    "memory_gib": [domain["planned_backing_bytes"] / 2**30 for domain in domains]}
(run / "actual-capacity.json").write_text(json.dumps(result, indent=2))
print(json.dumps({k: value for k, value in result.items() if k != "domains"} | {"domains": [{k: value for k, value in domain.items() if k != "layout_identity"} for domain in domains]}))
