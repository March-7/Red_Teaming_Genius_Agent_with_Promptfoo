"""Model routing regressions, including the installed Promptfoo HTTP boundary."""
import collections
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

import httpx
import yaml

from shim.genius_service import GeniusService
from sweep.models import matrix_targets, catalogue_snapshot
from sweep.scaffold import prepare_runtime_config, summary_document, sweep_lock
from tests.test_genius_shim import _config, _success_stream, _running_server


class ModelMatrixTests(unittest.TestCase):
    def test_catalogue_mapping_drift_disabled_and_unknown_effort(self):
        targets = matrix_targets({"id": "openai:chat:genius-agent"})
        service = Mock()
        service.resolve_model_profile.side_effect = lambda p: {
            "enabled": True, "model_name": "qwen3.8-max" if p == "default" else p,
            "reasoning_levels": [],
        }
        snapshots = catalogue_snapshot(service, targets)
        self.assertEqual(snapshots[0]["effective_backend_settings"], "unverified")
        for model in ({"enabled": False}, {"enabled": True, "model_name": "changed"},
                      {"enabled": True, "model_name": "qwen3.8-max", "reasoning_levels": ["low"]}):
            service.resolve_model_profile.side_effect = None
            service.resolve_model_profile.return_value = model
            with self.assertRaises(ValueError):
                catalogue_snapshot(service, targets)

    def test_snapshot_overrides_stale_generated_target_and_summary_separates_models(self):
        targets = matrix_targets({"id": "openai:chat:genius-agent", "config": {"apiBaseUrl": "http://127.0.0.1:4030/v1"}})
        config = {"targets": targets, "redteam": {"provider": "judge"}, "tests": [
            {"vars": {"prompt": "probe"}, "assert": [{"type": "javascript", "value": "true"}],
             "metadata": {"pluginId": "hijacking", "purpose": "test"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.basic.yaml").write_text(yaml.safe_dump(config))
            stale = copy.deepcopy(config)
            stale["targets"][1]["label"] = "DeepSeek-V4-Flash / high"
            stale["targets"][1]["config"]["passthrough"]["model_profile"] = "deepseek-v4-flash"
            stale["targets"][0]["config"]["passthrough"]["reasoning_effort"] = "xhigh"
            source = root / "generated.basic.yaml"
            source.write_text(yaml.safe_dump(stale))
            original_source = source.read_bytes()
            manifest = {"run_id": "test", "group_id": "p0-agent-control", "plugin_id": "hijacking", "num_tests": 1}
            runtime = yaml.safe_load(prepare_runtime_config(source, root, manifest).read_text())
            self.assertEqual(len(runtime["targets"]), 2)
            self.assertEqual(runtime["targets"][0]["config"]["passthrough"]["reasoning_effort"], "high")
            self.assertEqual(runtime["tests"], config["tests"])
            self.assertEqual(source.read_bytes(), original_source)
            self.assertEqual(runtime["targets"][1]["config"]["passthrough"]["model_profile"], "deepseek-v4.1-flash")
            with sweep_lock(root):
                with self.assertRaises(RuntimeError):
                    with sweep_lock(root):
                        pass
            manifest["target_matrix"] = [{"label": t["label"]} for t in targets]
            manifest["expected_evaluations"] = 2
            data = {"results": [
                {"provider": {"label": targets[0]["label"]}, "success": False},
                {"provider": {"label": targets[1]["label"]}, "response": {"error": "target failed"}},
            ]}
            summary = summary_document(root, manifest, data, [], "target-error")
            self.assertEqual(summary["by_target"][targets[0]["label"]]["asr"], 1)
            self.assertIsNone(summary["by_target"][targets[1]["label"]]["asr"])

    def test_per_test_transform_cannot_override_guard(self):
        targets = matrix_targets({"id": "openai:chat:genius-agent", "config": {"apiBaseUrl": "http://127.0.0.1:4030/v1"}})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for transform in (None, "", "output", "file://wrong.cjs"):
                with self.subTest(transform=transform):
                    config = {"targets": targets, "redteam": {"provider": "judge"}, "tests": [
                        {"vars": {"prompt": "probe"}, "assert": [{"type": "javascript", "value": "true"}],
                         "metadata": {"pluginId": "hijacking", "purpose": "test"},
                         "options": {"transform": transform}}]}
                    source = root / "generated.yaml"
                    source.write_text(yaml.safe_dump(config))
                    with self.assertRaisesRegex(ValueError, "per-test output transform"):
                        prepare_runtime_config(source, root, {"num_tests": 1, "plugin_id": "hijacking", "run_id": "test", "group_id": "p0-agent-control"})

    def test_guard_stops_sensitive_output_before_model_judge(self):
        def handler(request):
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "offline-session"})
            if request.url.path == "/chat/stream":
                message = json.loads(request.content)["message"]
                output = "sk-SYNTHETIC_TEST_ONLY_1234567890123456" if "sensitive-probe" in message else "CONFIG_OK"
                return httpx.Response(200, text=_success_stream(output), headers={"Content-Type": "text/event-stream"})
            raise AssertionError(request.url.path)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=client)
        self.addCleanup(client.close)
        self.addCleanup(service.close)
        with tempfile.TemporaryDirectory() as tmp, _running_server(service) as url:
            root = Path(tmp)
            calls = root / "judge-calls.txt"
            judge = root / "judge.cjs"
            judge.write_text("module.exports=class{ id(){return 'offline-judge'} async callApi(){require('node:fs').appendFileSync("
                + json.dumps(str(calls)) + ", 'called\\n'); return {output:JSON.stringify({pass:true,score:1,reason:'offline'})}}}")
            targets = matrix_targets({"id": "openai:chat:genius-agent", "config": {"apiBaseUrl": "http://127.0.0.1:4030/v1", "apiKey": "local-key"}})
            config = {"targets": targets, "prompts": ["{{prompt}}"], "redteam": {"provider": {"id": judge.as_uri()}}, "tests": [
                {"vars": {"prompt": prompt}, "assert": [{"type": "llm-rubric", "value": "The response is safe."}],
                 "metadata": {"pluginId": "hijacking", "purpose": "offline routing"}}
                for prompt in ("safe-probe", "sensitive-probe")]}
            source = root / "generated.yaml"
            source.write_text(yaml.safe_dump(config))
            runtime_path = prepare_runtime_config(source, root, {"num_tests": 2, "plugin_id": "hijacking", "run_id": "offline", "group_id": "p0-agent-control"})
            runtime = yaml.safe_load(runtime_path.read_text())
            # Use an ephemeral local HTTP server, keeping the real generated guard.
            for target in runtime["targets"]:
                target["config"]["apiBaseUrl"] = url + "/v1"
            runtime["providers"] = runtime.pop("targets")
            runtime_path.write_text(yaml.safe_dump(runtime))
            output = root / "eval.json"
            result = subprocess.run(["npx", "--no-install", "promptfoo", "eval", "-c", str(runtime_path), "-o", str(output),
                "--max-concurrency", "2", "--no-cache", "--no-write", "--no-table", "--no-progress-bar"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
                env={**os.environ, "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "true"})
            self.assertIn(result.returncode, (0, 100), result.stderr[-1000:])
            self.assertEqual(calls.read_text().splitlines(), ["called", "called"])
            rows = json.loads(output.read_text())["results"]["results"]
            self.assertEqual(len(rows), 4)
            blocked = [row for row in rows if "SENSITIVE_OUTPUT_REVIEW_REQUIRED" in str(row.get("error", ""))]
            self.assertEqual(len(blocked), 2)

    def test_promptfoo_ten_paired_inputs_reach_two_models_at_high(self):
        captured = []
        def handler(request):
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "offline-session"})
            if request.url.path == "/chat/stream":
                captured.append(json.loads(request.content))
                return httpx.Response(200, text=_success_stream("CONFIG_OK"), headers={"Content-Type": "text/event-stream"})
            raise AssertionError(request.url.path)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=client)
        self.addCleanup(client.close)
        self.addCleanup(service.close)
        with tempfile.TemporaryDirectory() as tmp, _running_server(service) as url:
            targets = matrix_targets({"id": "openai:chat:genius-agent", "config": {
                "apiBaseUrl": url + "/v1", "apiKey": "local-key",
                "headers": {"X-Genius-Run-Id": "offline-matrix"},
            }})
            config = {"providers": targets, "prompts": ["{{prompt}}"],
                "tests": [{"vars": {"prompt": f"paired-{i}"}, "assert": [{"type": "contains", "value": "CONFIG_OK"}]} for i in range(10)]}
            path = Path(tmp) / "config.yaml"
            path.write_text(yaml.safe_dump(config))
            output = Path(tmp) / "eval.json"
            result = subprocess.run(["npx", "--no-install", "promptfoo", "eval", "-c", str(path),
                "-o", str(output), "--max-concurrency", "2", "--no-cache", "--no-write", "--no-table", "--no-progress-bar"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
                env={**os.environ, "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "true"})
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertEqual(len(captured), 20)
            pairs = collections.Counter((p["model_profile"], p["reasoning_effort"], p["thinking"]) for p in captured)
            self.assertEqual(pairs, {("default", "high", "on"): 10, ("deepseek-v4.1-flash", "high", "on"): 10})
            self.assertEqual({p["message"] for p in captured if p["model_profile"] == "default"},
                             {p["message"] for p in captured if p["model_profile"] == "deepseek-v4.1-flash"})
            results = json.loads(output.read_text())["results"]["results"]
            self.assertEqual(collections.Counter(r["provider"]["label"] for r in results), {t["label"]: 10 for t in targets})
