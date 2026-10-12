"""Validate and install exact frozen input bytes, with bounded memory and no retokenization."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

REPO=Path(__file__).resolve().parents[1]
DATA=REPO/"datasets/frozen-256"

def install(source, workspace, parent=False):
    manifest=json.loads((DATA/"manifest.json").read_text())
    with gzip.open(DATA/"request-index.csv.gz","rt") as f:
        catalog={r["id"]:r for r in csv.DictReader(f)}
    destination=workspace/"prepared256k-256sessions-v24"
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    workspace.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix=".dataset-",dir=workspace))
    source_sha=hashlib.sha256(); selected_sha=hashlib.sha256()
    seen=set(); tokens=0; counts={}
    try:
        with source.open("rb") as src,(temporary/"requests.jsonl").open("xb") as dst:
            for line in src:
                source_sha.update(line); row=json.loads(line)
                if parent and row["session"] not in manifest["selected_source_ids"]:
                    continue
                rid=row["id"]; ref=catalog[rid]
                assert rid not in seen, "duplicate request"
                assert row["turn"]==counts.get(row["session"],0), "source turn order changed"
                counts[row["session"]]=row["turn"]+1
                for key in ("session","turn","prompt_tokens","output_tokens"):
                    assert row[key]==int(ref[key]), (rid,key)
                assert row["priority"]==float(ref["priority"])
                body=row["body"]
                assert len(body["prompt"])==row["prompt_tokens"]
                assert body["max_tokens"]==body["min_tokens"]==1
                assert body["temperature"]==0 and body["ignore_eos"] is True
                assert body.get("seed",7)==7
                token_sha=hashlib.sha256(json.dumps(body["prompt"],separators=(",",":")).encode()).hexdigest()
                assert row["prompt_sha256"]==ref["prompt_sha256"]==token_sha
                seen.add(rid);tokens+=row["prompt_tokens"]
                dst.write(line);selected_sha.update(line)
        assert seen==set(catalog) and tokens==manifest["prompt_tokens"]
        expected_source=manifest["frozen_parent_request_sha256"] if parent else manifest["request_sha256"]
        assert source_sha.hexdigest()==expected_source, "source file bytes do not match frozen identity"
        assert selected_sha.hexdigest()==manifest["request_sha256"], "selected bytes differ"
        for name in ("route-afd.json","route-nonafd.json"):
            arm=name[6:-5]
            assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==manifest["routes"][arm]["sha256"]
            shutil.copyfile(DATA/name,temporary/name)
        (temporary/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        (temporary/"import-audit.json").write_text(json.dumps({
            "requests":len(seen),"sessions":len(counts),"prompt_tokens":tokens,
            "request_sha256":selected_sha.hexdigest(),"exact_bytes":True},indent=2)+"\n")
        os.rename(temporary,destination)
        return destination
    except BaseException:
        shutil.rmtree(temporary)
        raise

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True,help="exact frozen requests.jsonl, not original conversation JSON")
    p.add_argument("--workspace",type=Path,required=True)
    p.add_argument("--parent",action="store_true",help="extract original lines from the frozen 609-session parent")
    a=p.parse_args()
    print(install(a.source,a.workspace.resolve(),a.parent))
