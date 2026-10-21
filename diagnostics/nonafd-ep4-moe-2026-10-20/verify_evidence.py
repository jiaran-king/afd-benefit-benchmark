"""Verify published rank0 operator evidence without launching a model or device job."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert sha(root / name) == expected, name
    selected = json.loads((root / "evidence/selected-events.json").read_text(), parse_float=Decimal)
    assert sha(args.trace) == selected["trace_sha256"], "Trace bytes differ from reviewed original"
    trace = json.loads(args.trace.read_text(), parse_float=Decimal)
    assert isinstance(trace, list)
    for index, expected in selected["selected_events"].items():
        actual = trace[int(index)]
        for key, value in expected.items():
            if key == "ts":
                assert Decimal(str(actual[key])) == Decimal(value), (index, key)
            else:
                assert actual[key] == value, (index, key)
    cpu = [e for e in trace if e.get("ph") == "X" and e.get("cat") == "cpu_op"
           and e.get("name") == "cann_ops_transformer::npu_mega_moe"]
    npu = [e for e in trace if e.get("ph") == "X" and e.get("name") == "MegaMoe"]
    assert len(cpu) == len(npu) == 129
    starts = Counter(str(e["id"]) for e in trace if e.get("cat") == "async_npu" and e.get("ph") == "s")
    ends = Counter(str(e["id"]) for e in trace if e.get("cat") == "async_npu" and e.get("ph") == "f")
    flow = str(selected["selected_events"]["241664"]["id"])
    assert starts[flow] == ends[flow] == 1
    assert trace[241665]["pid"] == trace[137025]["pid"]
    assert trace[241665]["tid"] == trace[137025]["tid"]
    assert trace[241665]["ts"] == trace[137025]["ts"]
    print(json.dumps({"status": "passed", "manifest_files": "SHA256 verified",
        "trace_original_bytes": True, "mega_moe_cpu_calls": len(cpu), "mega_moe_npu_kernels": len(npu),
        "selected_cpu_flow_npu_events": "matched"}))


if __name__ == "__main__":
    main()
