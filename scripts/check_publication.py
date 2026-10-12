"""Check curated public artifacts, source hashes, local links and high-risk byte patterns."""
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
    if failures:
        print(json.dumps({"status":"failed","findings":failures},indent=2))
        return 1
    print(json.dumps({"status":"passed","files":len(files),"bytes":sum(p.stat().st_size for p in files),
                      "scope":"curated fields, supported secret patterns, local links and source map; not a universal privacy proof"}))
    return 0

if __name__=="__main__":
    sys.exit(check())
