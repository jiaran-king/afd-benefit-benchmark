"""Compare approved and independently collected DSV4 experiment snapshots offline."""
import argparse
import json
from pathlib import Path
import re

SECTIONS = ("sources", "model", "runtime", "moe", "parameters")
SELECTORS = ("vllm_ascend/ascend_forward_context.py", "vllm_ascend/ops/fused_moe/moe_comm_method.py")
UNKNOWN = {"unknown", "unresolved", "auto", "todo", "n/a", "not_applicable", "null", "none", ""}


def validate(snapshot):
    errors = []

    def need(obj, key, kind, path):
        value = obj.get(key) if isinstance(obj, dict) else None
        if type(value) is not kind or (kind is str and value.strip().lower() in UNKNOWN):
            errors.append(f"{path}.{key}: require known {kind.__name__}")
            return None
        return value

    def hashes(value, path, required=(), allow_empty=False):
        if not isinstance(value, dict) or (not value and not allow_empty):
            errors.append(f"{path}: require SHA256 map")
            return
        for name in required:
            if name not in value:
                errors.append(f"{path}.{name}: missing")
        for name, digest in value.items():
            if not name.strip() or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                errors.append(f"{path}.{name}: require SHA256")

    if not isinstance(snapshot, dict):
        return ["snapshot: require object"]
    for name in snapshot.keys() - set(SECTIONS) - {"deployment", "evidence"}:
        errors.append(f"snapshot.{name}: place critical fields inside a compared section")
    for section in SECTIONS:
        need(snapshot, section, dict, "snapshot")
    if errors:
        return errors
    sources, model, runtime, moe = (snapshot[k] for k in SECTIONS[:4])
    mode = need(moe, "mode", str, "moe")
    if mode not in ("nonafd", "afd"):
        errors.append("moe.mode: require nonafd or afd")
    for name in ("vllm", "vllm_ascend") + (("afd",) if mode == "afd" else ()):
        if name not in sources:
            errors.append(f"sources.{name}: missing")
    for name, source in sources.items():
        path = "sources." + name
        commit = need(source, "commit", str, path)
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
            errors.append(path + ".commit: require exact commit SHA")
        hashes(source.get("patches_sha256") if isinstance(source, dict) else None,
               path + ".patches_sha256", allow_empty=True)
    for name in ("name", "architecture", "quantization"):
        value = need(model, name, str, "model")
        if value and name in ("name", "architecture"):
            if "deepseekv4" not in re.sub(r"[^a-z0-9]", "", value.lower()):
                errors.append(f"model.{name}: require actual DeepSeek V4 identity")
        if value and name == "quantization" and value.lower() == "ascend":
            errors.append("model.quantization: ascend does not identify the weight quantization")
    hashes(model.get("metadata_sha256"), "model.metadata_sha256",
           ("config.json", "tokenizer.json", "tokenizer_config.json"))
    for name in ("runner", "soc", "cann", "torch", "torch_npu"):
        need(runtime, name, str, "runtime")
    hashes(runtime.get("native_sha256"), "runtime.native_sha256")
    need(moe, "enable_expert_parallel", bool, "moe")
    for name in ("dp", "tp", "ep", "requested_fused_mc2", "effective_fused_mc2"):
        value = need(moe, name, int, "moe")
        if value is not None and value < (1 if name in ("dp", "tp", "ep") else 0):
            errors.append(f"moe.{name}: invalid count/value")
    for name in ("enable_prefill_mc2", "cann_mega_moe_available"):
        if not (mode == "afd" and moe.get(name) == "not_applicable"):
            need(moe, name, bool, "moe")
    need(moe, "implementation", str, "moe")
    hashes(moe.get("selection_sources_sha256"), "moe.selection_sources_sha256",
           SELECTORS if mode == "nonafd" else ())
    selection = moe.get("selection_sources_sha256")
    if mode == "afd" and isinstance(selection, dict) and not any(p.startswith("afd_plugin/") for p in selection):
        errors.append("moe.selection_sources_sha256: include the AFD/CAM implementation source")

    def known_parameters(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                known_parameters(item, path + "." + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                known_parameters(item, f"{path}[{i}]")
        elif value is None or (isinstance(value, str) and value.strip().lower() in {"unknown", "unresolved", "pending"}):
            errors.append(path + ": unresolved critical parameter")

    known_parameters(snapshot["parameters"], "parameters")
    return errors


def differences(expected, actual, path=""):
    if type(expected) is not type(actual):
        return [{"field": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            field = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                result.append({"field": field, "expected": expected.get(key, "<missing>"),
                               "actual": actual.get(key, "<missing>")})
            else:
                result.extend(differences(expected[key], actual[key], field))
        return result
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [{"field": path, "expected": expected, "actual": actual}]
        return [change for i, (left, right) in enumerate(zip(expected, actual))
                for change in differences(left, right, f"{path}[{i}]")]
    if expected != actual:
        return [{"field": path, "expected": expected, "actual": actual}]
    return []


def compare(expected, actual):
    errors = [f"{side}: {message}" for side, value in (("expected", expected), ("actual", actual))
              for message in validate(value)]
    changed = [] if errors else differences({k: expected[k] for k in SECTIONS},
                                            {k: actual[k] for k in SECTIONS})
    code = 2 if errors else 1 if changed else 0
    return {"status": "config_match" if code == 0 else "needs_review", "errors": errors,
            "differences": changed, "scope": "declared_snapshot_comparison",
            "operator_execution_verified": False}, code


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args()
    try:
        expected, actual = [json.loads(p.read_text(), object_pairs_hook=unique_keys,
                                      parse_constant=reject_constant)
                            for p in (args.expected, args.actual)]
        result, code = compare(expected, actual)
    except (OSError, ValueError) as exc:
        result, code = {"status": "needs_review", "errors": [str(exc)],
                        "operator_execution_verified": False}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
