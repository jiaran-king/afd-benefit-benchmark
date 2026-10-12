"""Apply frozen patches to a clean pinned checkout; emit a verifiable source record."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--component",choices=("ascend","afd"),required=True)
    p.add_argument("--source",type=Path,required=True)
    a=p.parse_args();src=a.source.resolve()
    def git(*args):
        return subprocess.check_output(["git","-C",str(src),*args],text=True).strip()
    versions=json.loads((HERE/"versions.json").read_text())
    spec=versions["sources"][a.component]
    commit=git("rev-parse","HEAD")
    assert commit in spec["accepted_commits"],"wrong baseline commit"
    assert not git("status","--porcelain"),"use an isolated clean checkout"
    patches=spec["patches"][:]
    if a.component=="ascend" and commit=="5cfb1697cf570b3bae2e30f9cc76d9e4e8bb5f46":
        patches.remove("prefixcache-async-pr4.patch")
    for name in patches:
        git("apply","--check",str(HERE/"patches"/name))
        git("apply",str(HERE/"patches"/name))
    # Include new files as well as modified tracked files.
    files=set(git("diff","--name-only").splitlines())|set(git("ls-files","--others","--exclude-standard").splitlines())
    hashes={n:hashlib.sha256((src/n).read_bytes()).hexdigest() for n in sorted(files) if (src/n).is_file()}
    proof={"component":a.component,"commit":commit,"patches_applied":spec["patches"],
           "applied_now":patches,"files":hashes,
           "native_compilation":"not performed; build with the pinned toolchain and verify actual worker maps"}
    (src/"benchmark-source-identity.json").write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps({"source":str(src),"component":a.component,"files":len(hashes),"native_compilation":False}))

if __name__=="__main__":
    main()
