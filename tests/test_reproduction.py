"""Offline protocol and configuration tests; no device or real HTTP calls."""
import asyncio
import csv
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

bench=load("bench","scripts/benchmark.py")
dataset=load("dataset","scripts/import_dataset.py")
sse=load("sse","scripts/runner/replay_sse.py")

class ReproductionTests(unittest.TestCase):
    def test_topology_and_affinity(self):
        for group in bench.GROUPS:
            services=bench.services_for(group)
            dies=[int(x) for service in services for x in service[2].split(",")]
            self.assertEqual(sorted(dies),list(range(16)))
            endpoints=bench.endpoints_for(group)
            self.assertEqual(len(endpoints),3 if group.startswith("afd") else 4)
        ep8=bench.endpoints_for("non_ep8")
        self.assertEqual([(v["instance"],v["dp_rank"]) for v in ep8.values()],[(0,0),(0,1),(1,0),(1,1)])

    def test_graph_scope_and_no_diagnostics(self):
        with patch.dict(os.environ,{},clear=True):
            for group in bench.GROUPS:
                for i in range(len(bench.services_for(group))):
                    role,_,cmd,env,config=bench.build_service(group,i,Path("/tmp/check"),"test")
                    graph=group=="afd_fgraph" and role=="ffn"
                    self.assertEqual("--no-enforce-eager" in cmd,graph)
                    self.assertEqual("--enforce-eager" in cmd,not graph)
                    self.assertIn("--async-scheduling",cmd)
                    self.assertNotIn("HCCL_DETERMINISTIC",env)
                    self.assertEqual(config["compressor_checkpoint_budget_ratio"],.25)
                    self.assertFalse(any("PROFILER" in key for key in env))
                    if role!="nonafd":
                        extra=config["afd"]["connector_extra_config"]
                        self.assertEqual(extra["async_moe_num_ubatches"],2)
                        self.assertEqual(extra["async_moe_split"],"token")
                        self.assertEqual(extra["hccl_buffer_size"],4096 if role=="ffn" else 1024)

    def test_old_diagnostic_environment_is_rejected(self):
        with patch.dict(os.environ,{"AFD_NPU_FFN_PROFILER_ENABLE":"1"},clear=True):
            with self.assertRaises(ValueError):
                bench.build_service("afd_fgraph",0,Path("/tmp/check"),"test")

    def test_sse_requires_done_and_matching_token_count(self):
        state=sse.CompletionState()
        with self.assertRaises(ValueError):
            state.validate()
        state.observe(json.dumps({"id":"r","choices":[{"token_ids":[42],"finish_reason":"length"}],
                                  "usage":{"completion_tokens":1}}))
        state.observe("[DONE]")
        self.assertEqual(state.evidence()["output_token_count"],1)
        with self.assertRaises(ValueError):
            state.observe("[DONE]")
        bad=sse.CompletionState()
        bad.observe(json.dumps({"choices":[{"token_ids":[42],"finish_reason":"length"}],
                                "usage":{"completion_tokens":2}}))
        with self.assertRaises(ValueError):
            bad.observe("[DONE]")

    def test_truncated_sse_fails(self):
        async def lines():
            yield 'data: {"choices":[]}'
        async def consume():
            return [x async for x in sse.sse_events(lines())]
        with self.assertRaises(ValueError):
            asyncio.run(consume())

    def test_exact_dataset_import_and_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=root/"meta";meta.mkdir()
            body={"prompt":[1,2,3],"max_tokens":1,"min_tokens":1,"temperature":0,"ignore_eos":True}
            row={"id":"source-0000-turn-000","session":0,"turn":0,"priority":.5,
                 "prompt_tokens":3,"output_tokens":1,
                 "prompt_sha256":hashlib.sha256(b"[1,2,3]").hexdigest(),"body":body}
            raw=(json.dumps(row)+"\n").encode();source=root/"requests.jsonl";source.write_bytes(raw)
            routes={}
            for arm in ("afd","nonafd"):
                data=b'{"assignments":{"0":0}}'
                (meta/f"route-{arm}.json").write_bytes(data)
                routes[arm]={"sha256":hashlib.sha256(data).hexdigest()}
            manifest={"selected_source_ids":[0],"prompt_tokens":3,"request_sha256":hashlib.sha256(raw).hexdigest(),"routes":routes}
            (meta/"manifest.json").write_text(json.dumps(manifest))
            index={k:v for k,v in row.items() if k!="body"}
            with gzip.open(meta/"request-index.csv.gz","wt",newline="") as f:
                w=csv.DictWriter(f,fieldnames=list(index));w.writeheader();w.writerow(index)
            with patch.object(dataset,"DATA",meta):
                destination=dataset.install(source,root/"good")
                self.assertEqual((destination/"requests.jsonl").read_bytes(),raw)
                with self.assertRaises(FileExistsError):
                    dataset.install(source,root/"good")
                row["priority"]=.6;source.write_text(json.dumps(row)+"\n")
                with self.assertRaises(AssertionError):
                    dataset.install(source,root/"bad")
                self.assertFalse((root/"bad/prepared256k-256sessions-v24").exists())

if __name__=="__main__":
    unittest.main()
