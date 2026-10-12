"""Record all live workers and verify loaded native identities before cold replay."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

from agentinfer_frozen_replay import make_config
from launch_service import redact
from live_environment import read_environment

CLIENT=Path(__file__).resolve().parent
REPO=CLIENT.parents[1]
work=Path(os.environ["BENCH_WORK_DIR"])
run=work/"runs"/os.environ["BENCH_RUN_NAME"]
group=sys.argv[1]
manifest=json.loads((run/"manifest.json").read_text())
assert manifest["arm"]==group and not (run/"formal-start.json").exists()
assert not (run/"configuration/prepressure-capture.json").exists(), "Do not replace an existing capture"
versions=json.loads((REPO/"environment/versions.json").read_text())
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert read_environment(os.getpid())==dict(os.environ), "effective environment reader self-check failed"
processes={}
for p in Path("/proc").glob("[0-9]*"):
    try:
        st=(p/"stat").read_text().rsplit(")",1)[1].split()
        if st[0]!="Z":
            processes[int(p.name)]={"ppid":int(st[1]),"start_ticks":st[19]}
    except (OSError,ValueError):
        pass
workers=[]
for service in manifest["services"]:
    root=service["driver_pid"]
    assert processes[root]["start_ticks"]==service["driver_start_ticks"],"driver identity changed"
    selected={root}
    while True:
        children={pid for pid,v in processes.items() if v["ppid"] in selected}
        if children<=selected:
            break
        selected|=children
    role=service["role"]
    folder=run/"configuration"/f"{role}-{service['instance']}"
    launch=json.loads((folder/"environment.json").read_text())
    records=[]
    for pid in sorted(selected):
        p=Path("/proc")/str(pid)
        try:
            maps=sorted({s.split()[-1] for s in (p/"maps").read_text().splitlines()
                         if ".so" in s and s.split()[-1].startswith("/")})
            inherited=dict(s.split("=",1) for s in (p/"environ").read_bytes().decode(errors="replace").split("\0") if "=" in s)
            row={"pid":pid,**processes[pid],"maps":maps,"environment":redact(inherited),
                "argv":(p/"cmdline").read_bytes().decode(errors="replace").strip("\0").split("\0"),
                "cwd":str((p/"cwd").resolve()),"executable":str((p/"exe").resolve()),
                "status":(p/"status").read_text()}
            if any("vllm_ascend_C" in s for s in maps):
                effective=read_environment(pid)
                keys={k for k in launch if k.startswith(("VLLM_","AFD_","HCCL_","OMP_","PYTORCH_"))}
                assert all(effective.get(k)==launch.get(k) for k in keys),(role,pid,"effective environment mismatch")
                assert "HCCL_DETERMINISTIC" not in effective
                row["effective_environment"]=redact(effective)
                identities={}
                for kind,fragment,suffix in (
                    ("compressor_host","/custom_transformer/","/libcust_opmaster_rt2.0.so"),
                    ("compressor_api","/custom_transformer/","/libcust_opapi.so"),
                    ("afd_host","/afd-plugin/","/libcust_opmaster_rt2.0.so"),
                    ("afd_api","/afd-plugin/","/libcust_opapi.so")):
                    paths=[s for s in maps if fragment in s and s.endswith(suffix)]
                    if kind.startswith("afd") and role=="nonafd":
                        continue
                    if kind.startswith("compressor") and role=="ffn":
                        if kind=="compressor_host":
                            assert all(digest(s)==versions["native"]["unused_ffn_compressor_host"] for s in paths)
                        continue
                    assert paths,(role,pid,kind,"not actually loaded")
                    assert all(digest(s)==versions["native"][kind] for s in paths),(role,pid,kind,"native bytes changed")
                    identities[kind]=[{"path":s,"sha256":digest(s)} for s in paths]
                row["native_identity"]=identities
                workers.append({"pid":pid,"role":role,"identities":identities})
            records.append(row)
        except FileNotFoundError:
            continue
    (folder/"actual-processes.json").write_text(json.dumps(records,indent=2)+"\n")
    # Both A and F services must have completed startup. A server-info error is explicit.
    url=f"http://127.0.0.1:{service['port']}"
    with urlopen(url+"/health",timeout=15) as response:
        assert response.status==200
    with urlopen(url+"/server_info",timeout=15) as response:
        (folder/"actual-server-info.json").write_bytes(response.read())
assert len(workers)==16
assert sum(x["role"]!="ffn" for x in workers)==(12 if group.startswith("afd") else 16)
kernel=Path(os.environ["ASCEND_SOURCE_DIR"])/"vllm_ascend/_cann_ops_custom/vendors/custom_transformer/op_impl/ai_core/tbe/kernel/ascend910_93/compressor/Compressor_5d0f45757e9591d6e00196bb7912baa5.o"
assert digest(kernel)==versions["native"]["compressor_kernel"],"Compressor device kernel bytes changed"
(run/"device-after-profile.txt").write_text(subprocess.check_output(["npu-smi","info"],text=True))
subprocess.run([sys.executable,str(CLIENT/"collect_capacity.py"),run.name],check=True)
for path in run.glob("*domain-*.jsonl"):
    with path.open() as f:
        first=json.loads(next(f))
    assert "Async" in first["scheduler_class"],"synchronous scheduler observed"
replay=run/"configuration/replay-client";replay.mkdir()
endpoints=json.loads((run/"endpoints.json").read_text())
config=make_config(CLIENT,run/"formal-http/agentinfer-ordering-trace.jsonl",
                   run/"formal-http/agentinfer",next(iter(endpoints.values()))["url"],256)
for name,value in (
    ("environment",redact(dict(os.environ))),
    ("agentinfer-config",config.model_dump(mode="json")),
    ("argv",[sys.executable,str(CLIENT/"run_formal.py"),run.name])):
    (replay/(name+".json")).write_text(json.dumps(value,indent=2)+"\n")
copied=run/"configuration/client-sources";copied.mkdir()
for path in CLIENT.glob("*.py"):
    shutil.copyfile(path,copied/path.name)
proof={"status":"passed","time_ns":time.time_ns(),"workers":len(workers),
       "group":group,"native_identity":workers,
       "scope":"effective environments, loaded native identities, measured capacity, async schedulers and replay configuration"}
(run/"configuration/prepressure-capture.json").write_text(json.dumps(proof,indent=2)+"\n")
print(json.dumps({"status":"passed","workers":16,"next":"replay performs all-endpoint cold reset and baseline capture"}))
