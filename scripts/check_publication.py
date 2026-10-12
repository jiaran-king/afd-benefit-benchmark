"""Check curated public artifacts, source hashes, local links and high-risk byte patterns."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
def check():
    failures=[];files=[]
    patterns={
        "private key material":rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "GitHub credential":rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b",
        "cloud access key":rb"\bAKIA[A-Z0-9]{16}\b",
        "OpenAI-style key":rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b",
        "internal domain":rb"(?:antgroup-inc\.cn|alipay\.com|hw-a3\.local)",
        "original machine path":rb"(?:/a3_inference/" + rb"itask/workdir/|/home/[^/]+/workspace/|/mnt/c/" + rb"Users/)",
        "private IPv4":rb"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.\d{1,3}\.\d{1,3}\b",
    }
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in (".git","__pycache__",".venv",".pytest_cache")):
            continue
        files.append(p)
        if p.is_symlink():
            failures.append((str(p.relative_to(ROOT)),"symlink not permitted in public export"))
        raw=p.read_bytes()
        if p.suffix==".gz":
            raw=gzip.decompress(raw)
        # Binary image has no text metadata; scan text and decoded archives.
        if p.suffix not in (".png",):
            for name,pattern in patterns.items():
                if re.search(pattern,raw):
                    failures.append((str(p.relative_to(ROOT)),name))
        if p.suffix==".md":
            text=raw.decode()
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)",text):
                if "://" in link or link.startswith("#"):
                    continue
                target=link.split("#",1)[0]
                if not (p.parent/target).exists():
                    failures.append((str(p.relative_to(ROOT)),"broken link: "+link))
    sources=json.loads((ROOT/"results/2026-10-11/sources.json").read_text())
    for row in sources["artifacts"]:
        p=ROOT/row["published_path"]
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=row["published_sha256"]:
            failures.append((row["published_path"],"source map output hash differs"))
    frozen=json.loads((ROOT/"datasets/frozen-256/manifest.json").read_text())
    raw=json.loads((ROOT/"datasets/raw/manifest.json").read_text())
    release=json.loads((ROOT/"datasets/releases/2026-10-12.json").read_text())
    for name,identity in (("raw",raw),("frozen",{
            "sha256":frozen["request_sha256"],"bytes":frozen["request_bytes"]})):
        asset=release["datasets"][name]
        for key in ("sha256","bytes"):
            if asset["uncompressed"][key]!=identity[key]:
                failures.append((name,"Release/original identity mismatch: "+key))
        expected="https://github.com/"+release["repository"]+"/releases/download/"+release["tag"]+"/"+asset["filename"]
        if asset["url"]!=expected:
            failures.append((name,"Release URL differs from pinned repository/tag"))
    if raw["sha256"]!=frozen["source_sha256"]:
        failures.append(("raw","source identity differs from formal frozen manifest"))
    priorities_path=ROOT/"datasets/frozen-256/priorities.json"
    if hashlib.sha256(priorities_path.read_bytes()).hexdigest()!=frozen["priorities_sha256"]:
        failures.append(("priorities.json","frozen file hash differs"))
    priorities=json.loads(priorities_path.read_text())
    with gzip.open(ROOT/"datasets/frozen-256/request-index.csv.gz","rt") as f:
        positions={row["id"]:float(row["priority"]) for row in csv.DictReader(f)}
    if priorities["positions"]!=positions or priorities["seed"]!=frozen["seed"]:
        failures.append(("priorities.json","priorities differ from formal request catalog"))
    provenance=json.loads((ROOT/"datasets/provenance.json").read_text())
    for row in provenance.values():
        expected=row.get("published_sha256",row.get("sha256"))
        if hashlib.sha256((ROOT/row["published_path"]).read_bytes()).hexdigest()!=expected:
            failures.append((row["published_path"],"dataset provenance hash differs"))
    if failures:
        print(json.dumps({"status":"failed","findings":failures},indent=2))
        return 1
    print(json.dumps({"status":"passed","files":len(files),"bytes":sum(p.stat().st_size for p in files),
                      "scope":"curated fields, supported secret patterns, local links and source map; not a universal privacy proof"}))
    return 0

if __name__=="__main__":
    sys.exit(check())
