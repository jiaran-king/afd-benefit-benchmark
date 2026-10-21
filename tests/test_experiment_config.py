"""Offline guards for model/source substitutions and MoE configuration drift."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/run-dsv4-benchmark/scripts/check_experiment_config.py"
spec = importlib.util.spec_from_file_location("experiment_config", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def recorded_fixture():
    """Use archived identities for the comparator fixture, not a live-device claim."""
    evidence = ROOT / "diagnostics/nonafd-ep4-moe-2026-10-20"
    source = json.loads((evidence / "source-versions.json").read_text())
    config = json.loads((evidence / "recorded-configuration.json").read_text())
    return {
        "sources": {
            "vllm": {"commit": source["vllm"]["commit"], "patches_sha256": {}},
            "vllm_ascend": {"commit": source["vllm_ascend"]["commit"], "patches_sha256": {
                p["path"]: p["sha256"] for p in source["vllm_ascend"]["patches"]}},
        },
        "model": {"name": config["model"], "architecture": "DeepseekV4ForCausalLM",
                  "quantization": "W4A8", "metadata_sha256": config["model_metadata_sha256"]},
        "runtime": {**source["environment"], "runner": config["runner"],
                    "soc": config["environment"]["SOC_VERSION"], "native_sha256": {
                        p: h for p, h in source["loaded_runtime_file_sha256"].items() if p.endswith(".so")}},
        "moe": {"mode": "nonafd", "enable_expert_parallel": True, "dp": config["DP"],
                "tp": config["TP"], "ep": config["EP"], "requested_fused_mc2": 1,
                "effective_fused_mc2": 1, "enable_prefill_mc2": True,
                "cann_mega_moe_available": True, "implementation": "MegaMoE",
                "selection_sources_sha256": {f["path"]: f["sha256"] for f in source["source_files"]
                                             if f["path"] in check.SELECTORS}},
        "parameters": {"prefix_cache": False, "cws": True, "max_num_batched_tokens": 8192,
                       "graph": "Eager", "multistream_overlap_shared_expert": False},
        "deployment": {"port": 18080},
    }


class ExperimentConfigTests(unittest.TestCase):
    def setUp(self):
        self.expected = recorded_fixture()

    def changed(self, section, key, value):
        actual = deepcopy(self.expected)
        actual[section][key] = value
        result, code = check.compare(self.expected, actual)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "needs_review")
        return result

    def test_matching_identity_and_deployment_only_changes(self):
        actual = deepcopy(self.expected)
        actual["deployment"] = {"port": 9999, "output_directory": "another-run"}
        actual["evidence"] = {"configuration": "independent-startup-record.json"}
        result, code = check.compare(self.expected, actual)
        self.assertEqual(code, 0, result)
        self.assertFalse(result["operator_execution_verified"])

    def test_model_architecture_quantization_and_metadata_substitution(self):
        for key, value in [("name", "DeepSeek-V2-Lite"), ("architecture", "DeepseekV2ForCausalLM"),
                           ("name", "DeepSeek-V4-Pro"), ("quantization", "W8A8")]:
            with self.subTest(key=key, value=value):
                self.changed("model", key, value)
        metadata = dict(self.expected["model"]["metadata_sha256"])
        metadata["config.json"] = "0" * 64
        self.changed("model", "metadata_sha256", metadata)

    def test_exact_source_and_patch_identity(self):
        actual = deepcopy(self.expected)
        actual["sources"]["vllm_ascend"]["commit"] = "2bcf08d67968567ae7a41cf60aaa229f1e863d27"
        self.assertEqual(check.compare(self.expected, actual)[1], 1)
        actual = deepcopy(self.expected)
        actual["sources"]["vllm_ascend"]["patches_sha256"] = {}
        self.assertEqual(check.compare(self.expected, actual)[1], 1)
        actual["sources"]["vllm"]["commit"] = "0.26.0"
        self.assertEqual(check.compare(self.expected, actual)[1], 2)

    def test_moe_switches_layout_component_and_effective_path(self):
        for key, value in [("requested_fused_mc2", 0), ("requested_fused_mc2", 2),
                           ("effective_fused_mc2", 0), ("enable_prefill_mc2", False),
                           ("cann_mega_moe_available", False), ("implementation", "dispatch_ffn_combine"),
                           ("enable_expert_parallel", False), ("ep", 8), ("tp", 2)]:
            with self.subTest(key=key):
                self.changed("moe", key, value)

    def test_same_switch_different_selector_or_runner_is_not_equivalent(self):
        hashes = dict(self.expected["moe"]["selection_sources_sha256"])
        hashes[check.SELECTORS[0]] = "0" * 64
        self.changed("moe", "selection_sources_sha256", hashes)
        self.changed("runtime", "runner", "MRv2")

    def test_silent_fallback_and_extra_parameters(self):
        self.changed("parameters", "cws", False)
        actual = deepcopy(self.expected)
        actual["parameters"]["enable_force_load_balance"] = True
        self.assertEqual(check.compare(self.expected, actual)[1], 1)

    def test_unknown_missing_and_incomplete_inputs_do_not_pass(self):
        self.assertEqual(check.compare({}, {})[1], 2)
        for value in (None, "unknown", "not_applicable"):
            actual = deepcopy(self.expected)
            actual["moe"]["implementation"] = value
            self.assertEqual(check.compare(actual, actual)[1], 2)
        for section, key in [("moe", "enable_prefill_mc2"), ("model", "quantization")]:
            actual = deepcopy(self.expected)
            del actual[section][key]
            self.assertEqual(check.compare(actual, actual)[1], 2)
        self.changed("runtime", "native_sha256", {})
        actual = deepcopy(self.expected)
        actual["parameters"]["cws"] = None
        self.assertEqual(check.compare(actual, actual)[1], 2)
        actual = deepcopy(self.expected)
        actual["misspelled_critical_section"] = {"fused_mc2": 0}
        self.assertEqual(check.compare(actual, actual)[1], 2)

    def test_bool_and_integer_values_are_not_interchangeable(self):
        self.changed("moe", "effective_fused_mc2", True)
        actual = deepcopy(self.expected)
        actual["parameters"]["cws"] = 1
        self.assertEqual(check.compare(self.expected, actual)[1], 1)
        self.assertTrue(check.differences([True], [1]))

    def test_afd_requires_plugin_identity_and_does_not_infer_path_from_zero(self):
        actual = deepcopy(self.expected)
        actual["moe"].update(mode="afd", requested_fused_mc2=0, effective_fused_mc2=0,
                             implementation="AFD/CAM", enable_prefill_mc2="not_applicable",
                             cann_mega_moe_available="not_applicable")
        self.assertEqual(check.compare(actual, actual)[1], 2)
        versions = json.loads((ROOT / "environment/versions.json").read_text())
        patch = ROOT / "environment/patches/afd-asymmetric-startup.patch"
        actual["sources"]["afd"] = {"commit": versions["sources"]["afd"]["accepted_commits"][0],
                                    "patches_sha256": {patch.name: hashlib.sha256(patch.read_bytes()).hexdigest()}}
        self.assertEqual(check.compare(actual, actual)[1], 2)
        actual["moe"]["selection_sources_sha256"]["afd_plugin/selector_fixture.py"] = hashlib.sha256(b"AFD test fixture").hexdigest()
        self.assertEqual(check.compare(actual, actual)[1], 0)

    def test_cli_is_read_only_and_rejects_duplicate_or_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            expected, actual = [Path(directory) / name for name in ("expected.json", "actual.json")]
            expected.write_text(json.dumps(self.expected))
            actual.write_bytes(expected.read_bytes())
            command = [sys.executable, str(SCRIPT), "--expected", str(expected), "--actual", str(actual)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(expected.read_bytes(), actual.read_bytes())
            for bad in ['{"sources":{},"sources":{}}', '{"parameters":{"value":NaN}}']:
                actual.write_text(bad)
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
