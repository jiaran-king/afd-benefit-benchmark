"""Portable orchestration for the preserved five-arm experiment. Plan is read-only."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1]
CLIENT=REPO/"scripts/runner"
sys.path.insert(0,str(CLIENT))
from topology import GROUPS, configuration_path, services_for, endpoints_for
from three_arm_topology import TOPOLOGY, PREPARED
from launch_service import redact

UNSET=("HCCL_DETERMINISTIC","BENEFIT_KV_BYTES","AFD_FORCE_BALANCED_TOPK_IDS",
       "AFD_CAM_OP_IO_LOG","AFD_NPU_PROFILE_DIR","AFD_NPU_PROFILE_ROLES",
       "AFD_NPU_PROFILE_MAX_STEPS","AFD_ASYNC_CAM_LAYERED_GMM",
       "CAM_CUST_OPAPI_LIB_PATH","AFD_CUST_OPAPI_LIB_PATH","HCCL_BUFFSIZE")
REQUIRED=("MODEL_DIR","BENEFIT_PYTHON","VLLM_SOURCE_DIR","ASCEND_SOURCE_DIR")

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def build_service(group,index,workspace,name,execute=False):
    role,instance,devices,port,dp_port=services_for(group)[index]
    run=workspace/"runs"/name
    record=json.loads(configuration_path(group).read_text())[f"{group}/{role}-{instance}"]
    env=dict(os.environ)
    forbidden=[k for k in env if k.startswith(("ASYNC_VALIDATION","PREFIX_STAGE_TRACE","PREFIX_OPERATOR_TRACE")) or "PROFILER" in k]
    if forbidden:
        raise ValueError(f"Diagnostic environment must be removed: {forbidden}")
    for key in UNSET:
        env.pop(key,None)
    env.update(record["environment"])
    source_key="FFN_ASCEND_SOURCE_DIR" if role=="ffn" else "ASCEND_SOURCE_DIR"
    ascend=os.environ.get(source_key,"<"+source_key+">")
    vllm=os.environ.get("VLLM_SOURCE_DIR","<VLLM_SOURCE_DIR>")
    plugin=os.environ.get("AFD_SOURCE_DIR","<AFD_SOURCE_DIR>")
    custom=Path(ascend)/"vllm_ascend/_cann_ops_custom/vendors/custom_transformer"
    roots=[str(CLIENT),ascend,vllm]
    if role!="nonafd":
        roots.insert(0,plugin)
    env.update(BENCH_WORK_DIR=str(workspace),BENCH_RUN_NAME=name,BENCH_GROUP=group,
        BENEFIT_ROLE=role,BENEFIT_INSTANCE=str(instance),BENEFIT_RUN=str(run),
        BENEFIT_CLIENT=str(CLIENT),BENEFIT_DEVICES=devices,BENEFIT_PORT=str(port),
        BENEFIT_DP_PORT=str(dp_port),BENEFIT_MBT=str(GROUPS[group]["mbt"]),
        ASCEND_RT_VISIBLE_DEVICES=devices,PROMETHEUS_MULTIPROC_DIR=str(run/f"metrics-{role}-{instance}"),
        PYTHONPATH=":".join(roots)+(":"+env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        ASCEND_CUSTOM_OPP_PATH=str(custom)+(":"+env["ASCEND_CUSTOM_OPP_PATH"] if env.get("ASCEND_CUSTOM_OPP_PATH") else ""),
        LD_LIBRARY_PATH=str(custom/"op_api/lib")+(":"+env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""),
        HCCL_IF_IP=os.environ.get("BENCH_HCCL_IF_IP",socket.gethostbyname(socket.gethostname())))
    if role!="nonafd":
        vendor=Path(plugin)/"afd_plugin/_cann_ops_custom/vendors/afd-plugin"
        env["ASCEND_CUSTOM_OPP_PATH"]=str(vendor)+":"+env["ASCEND_CUSTOM_OPP_PATH"]
        env["LD_LIBRARY_PATH"]=str(vendor/"op_api/lib")+":"+env["LD_LIBRARY_PATH"]
        env["AFD_CUST_OPAPI_LIB_PATH"]=str(vendor/"op_api/lib/libcust_opapi.so")
    for key in ("NO_PROXY","no_proxy"):
        env[key]=",".join(filter(None,[env.get(key),"127.0.0.1","localhost"]))
    replacements={"$"+"{BENEFIT_PYTHON}":env.get("BENEFIT_PYTHON",sys.executable),
                  "$"+"{MODEL_DIR}":env.get("MODEL_DIR","<MODEL_DIR>"),"$"+"{RUN_DIR}":str(run)}
    def expand(s):
        for old,new in replacements.items():
            s=s.replace(old,new)
        if "$"+"{" in s:
            raise ValueError(f"unresolved command placeholder: {s}")
        return s
    argv=[expand(s) for s in record["argv"]]
    config=json.loads(argv[argv.index("--additional-config")+1])
    env["BENEFIT_CONFIG"]=json.dumps(config,separators=(",",":"))
    if execute:
        required=REQUIRED+(("AFD_SOURCE_DIR","FFN_ASCEND_SOURCE_DIR") if group.startswith("afd") else ())
        for k in required:
            if not os.environ.get(k) or not Path(os.environ[k]).exists():
                raise ValueError(f"Set existing {k}")
    return role,instance,argv,env,config

def preflight(group):
    expected=json.loads((REPO/"environment/versions.json").read_text())
    model=Path(os.environ["MODEL_DIR"])
    dataset=json.loads((REPO/"datasets/frozen-256/manifest.json").read_text())
    for name,value in dataset["model_files"].items():
        assert digest(model/name)==value,(name,"model/tokenizer identity mismatch")
    for package,value in expected["python_packages"].items():
        assert importlib.metadata.version(package)==value,(package,"version mismatch")
    assert sys.version.split()[0]==expected["python"],"Use the recorded Python interpreter"
    sources=[("VLLM_SOURCE_DIR","vllm"),("ASCEND_SOURCE_DIR","ascend")]
    if group.startswith("afd"):
        sources.append(("AFD_SOURCE_DIR","afd"))
        sources.append(("FFN_ASCEND_SOURCE_DIR","ascend"))
    for env_name,key in sources:
        src=Path(os.environ[env_name])
        # Exact source exports lack .git: an explicit source identity record is required.
        identity=src/"benchmark-source-identity.json"
        if identity.exists():
            proof=json.loads(identity.read_text())
            assert proof["commit"] in expected["sources"][key]["accepted_commits"]
            assert proof.get("patches_applied")==expected["sources"][key]["patches"]
            assert proof.get("files"),"source identity must include verified changed files"
            for name,value in proof["files"].items():
                assert digest(src/name)==value,(key,name,"source changed after patching")
        else:
            head=subprocess.check_output(["git","-C",str(src),"rev-parse","HEAD"],text=True).strip()
            assert head in expected["sources"][key]["accepted_commits"],(key,head)
            # Apply tool writes identity after checking exact patch state.
            if expected["sources"][key]["patches"]:
                raise ValueError("Run environment/apply_patches.py and retain its source identity record")
    return {"status":"passed","python":sys.version.split()[0],"packages":expected["python_packages"],
            "model_files":dataset["model_files"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("plan","start","record","replay","audit","stop"))
    p.add_argument("--group",choices=GROUPS,required=True)
    p.add_argument("--workspace",type=Path,required=True)
    p.add_argument("--run-name",required=True)
    a=p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}",a.run_name):
        p.error("run-name must be a simple unique directory name")
    work=a.workspace.resolve();run=work/"runs"/a.run_name
    os.environ.update(BENCH_WORK_DIR=str(work),BENCH_RUN_NAME=a.run_name,BENCH_GROUP=a.group)
    if a.action=="plan":
        for i in range(len(services_for(a.group))):
            role,instance,cmd,env,config=build_service(a.group,i,work,a.run_name)
            print(f"{role}-{instance}: {shlex.join(cmd)}")
            print(json.dumps({"performance_environment":{k:env[k] for k in json.loads(configuration_path(a.group).read_text())[f"{a.group}/{role}-{instance}"]["environment"]},
                              "additional_config":config},ensure_ascii=False))
        return
    if a.action=="start":
        assert not run.exists(),"run directory already exists; no implicit retry"
        assert (work/PREPARED/"import-audit.json").exists(),"Import and validate frozen input first"
        identities=preflight(a.group)
        before=subprocess.check_output(["npu-smi","info"],text=True)
        assert all(f"No running processes found in NPU {i}" in before for i in range(8)), "Exclusive idle 16 DIE required"
        plans=[build_service(a.group,i,work,a.run_name,True) for i in range(len(services_for(a.group)))]
        frozen=json.loads((work/PREPARED/"manifest.json").read_text())
        run.mkdir(parents=True)
        (run/"configuration").mkdir()
        (run/"device-before.txt").write_text(before)
        (run/"configuration/dependency-preflight.json").write_text(json.dumps(identities,indent=2))
        manifest={"name":a.run_name,"arm":a.group,"prepared":PREPARED,"request_sha256":frozen["request_sha256"],
            "purpose":"formal_closeout_9078_unified_compressor_host","started":time.time(),
            "total_die":16,"capacity":"natural","max_model_len":262144,"output_tokens":1,
            "checkpoint_ratio":.25,"mbt":GROUPS[a.group]["mbt"],"topology":TOPOLOGY,"services":[]}
        (run/"manifest.json").write_text(json.dumps(manifest,indent=2))
        (run/"endpoints.json").write_text(json.dumps(endpoints_for(a.group),indent=2))
        for i,(role,instance,cmd,env,config) in enumerate(plans):
            folder=run/"services"/f"{role}-{instance}";folder.mkdir(parents=True)
            cfg=run/"configuration"/f"{role}-{instance}";cfg.mkdir()
            for name,value in (("argv",cmd),("environment",redact(env)),("additional-config",config)):
                (cfg/(name+".json")).write_text(json.dumps(value,indent=2))
            (cfg/"launch-command.sh").write_text(shlex.join(cmd)+"\n")
            Path(env["PROMETHEUS_MULTIPROC_DIR"]).mkdir()
            with (folder/"driver.log").open("x") as log:
                process=subprocess.Popen([sys.executable,str(CLIENT/"process_driver.py"),str(folder),*cmd],
                    env=env,cwd=CLIENT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            ticks=Path(f"/proc/{process.pid}/stat").read_text().rsplit(")",1)[1].split()[19]
            _,_,devices,port,dp_port=services_for(a.group)[i]
            manifest["services"].append({"role":role,"instance":instance,"devices":devices,"port":port,
                "dp_port":dp_port,"driver_pid":process.pid,"driver_start_ticks":ticks,"directory":str(folder),
                "additional_config":config})
            (run/"manifest.json").write_text(json.dumps(manifest,indent=2))
        print(json.dumps({"started":str(run),"next":"wait for normal startup, then record"}))
        return
    manifest=json.loads((run/"manifest.json").read_text())
    assert manifest["arm"]==a.group
    script={"record":"capture_prepressure.py","replay":"run_formal.py","audit":"audit_native.py","stop":"stop_owned.py"}[a.action]
    argument=a.group if a.action in ("record","stop") else a.run_name
    subprocess.run([sys.executable,str(CLIENT/script),argument],check=True)
    if a.group.startswith("afd") and a.action in ("record","replay"):
        phase="before" if a.action=="record" else "after"
        subprocess.run([sys.executable,str(CLIENT/"record_ffn_graph_state.py"),a.group,phase],check=True)

if __name__=="__main__":
    main()
