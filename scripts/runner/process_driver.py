"""Persist process identity and completion; polling never implies completion."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
with (folder / "stdout.log").open("x", buffering=1) as stream:
    proc = subprocess.Popen(sys.argv[2:], stdout=stream, stderr=subprocess.STDOUT)
    (folder / "process.json").write_text(json.dumps({
        "pid": proc.pid, "start_ticks": Path(f"/proc/{proc.pid}/stat").read_text().split()[21],
        "driver_pid": os.getpid(), "started": time.time(), "command": sys.argv[2:],
    }, indent=2))
    code = proc.wait()
    (folder / "completion.json").write_text(json.dumps({"exit_code": code, "finished": time.time()}))
raise SystemExit(code)
