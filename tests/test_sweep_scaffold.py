from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import socket
import unittest
from unittest.mock import Mock, patch

import yaml

from sweep.inventory import (
    build_inventory,
    evaluate_prerequisites,
    find_plugin,
    load_inventory,
    validate_inventory,
)
from sweep.scaffold import (
    build_policy_document,
    classify_run,
    collect_artifacts,
    create_run_directory,
    eval_counts,
    execute_baseline,
    generate_scaffold,
    generate_summary,
    missing_artifacts,
    sample_results,
    prepare_runtime_config,
    require_free_shim_port,
    start_shim,
    validate_policy_document,
    validate_scaffold,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "sweeps" / "inventory.json"


class SweepInventoryTests(unittest.TestCase):
    def test_inventory_has_six_groups_and_thirty_nine_unique_plugins(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        groups = inventory["groups"]
        plugins = [plugin for group in groups for plugin in group["plugins"]]
        self.assertEqual(len(groups), 6)
        self.assertEqual(len(plugins), 39)
        self.assertEqual(len({group["id"] for group in groups}), 6)
        self.assertEqual(len({plugin["id"] for plugin in plugins}), 39)
        self.assertEqual(
            len({(plugin["id"], plugin["group"]) for plugin in plugins}), 39
        )

    def test_every_plugin_directory_has_required_layout(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        for group in inventory["groups"]:
            group_dir = PROJECT_ROOT / "sweeps" / group["id"]
            self.assertTrue(group_dir.is_dir(), group_dir)
            for plugin in group["plugins"]:
                plugin_dir = group_dir / plugin["id"]
                for name in (
                    "config.basic.yaml",
                    "approval-policy.json",
                    "summary.md",
                ):
                    self.assertTrue((plugin_dir / name).is_file(), plugin_dir / name)
                self.assertTrue((plugin_dir / "runs").is_dir(), plugin_dir / "runs")

    def test_raw_run_artifacts_are_git_ignored_but_scaffold_is_trackable(self) -> None:
        ignored = PROJECT_ROOT / "sweeps" / "p0-agent-control" / "hijacking" / "runs" / "x.json"
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(ignored)],
            cwd=PROJECT_ROOT,
        )
        self.assertEqual(result.returncode, 0, ignored)
        tracked = PROJECT_ROOT / "sweeps" / "p0-agent-control" / "hijacking" / "config.basic.yaml"
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(tracked)],
            cwd=PROJECT_ROOT,
        )
        self.assertNotEqual(result.returncode, 0, tracked)

    def test_inventory_validator_rejects_custom_duplicate_and_cross_group_plugins(self) -> None:
        inventory = build_inventory()
        inventory["groups"][0]["plugins"].append(
            {"id": "policy", "prerequisites": [], "status": "ready", "group": "p0-agent-control"}
        )
        errors = validate_inventory(inventory)
        self.assertTrue(any("custom plugin" in error for error in errors))
        self.assertTrue(any("expected 39 plugins" in error for error in errors))

        inventory = build_inventory()
        duplicate = dict(inventory["groups"][1]["plugins"][0])
        duplicate["group"] = inventory["groups"][0]["id"]
        inventory["groups"][0]["plugins"].append(duplicate)
        errors = validate_inventory(inventory)
        self.assertTrue(any("duplicate plugin id" in error for error in errors))
        self.assertTrue(any("assigned to multiple groups" in error for error in errors))

    def test_inventory_validator_rejects_intent_plugin(self) -> None:
        inventory = build_inventory()
        inventory["groups"][0]["plugins"][0] = {
            "id": "intent",
            "prerequisites": [],
            "status": "ready",
            "group": "p0-agent-control",
        }
        errors = validate_inventory(inventory)
        self.assertTrue(any("custom plugin is not allowed: intent" in error for error in errors))


class SweepConfigPolicyTests(unittest.TestCase):
    def test_every_config_parses_and_contains_basic_ten_sample_semantics(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        for group in inventory["groups"]:
            for plugin in group["plugins"]:
                path = PROJECT_ROOT / "sweeps" / group["id"] / plugin["id"] / "config.basic.yaml"
                config = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertEqual(config["redteam"]["plugins"], [
                    {"id": plugin["id"], "numTests": 10}
                ])
                self.assertEqual(config["redteam"]["strategies"], [{"id": "basic"}])
                self.assertEqual(config["redteam"]["maxConcurrency"], 2)
                self.assertEqual(config["redteam"]["numTests"], 10)
                self.assertTrue(config["targets"])
                self.assertTrue(config["redteam"]["provider"])

    def test_every_policy_is_exact_and_has_required_fields(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        for group in inventory["groups"]:
            for plugin in group["plugins"]:
                path = PROJECT_ROOT / "sweeps" / group["id"] / plugin["id"] / "approval-policy.json"
                policy = json.loads(path.read_text(encoding="utf-8"))
                errors = validate_policy_document(policy, group["id"] + "/" + plugin["id"])
                self.assertEqual(errors, [])
                self.assertEqual(len(policy["rules"]), 1)

    def test_policy_validation_rejects_wildcards_and_missing_fields(self) -> None:
        document = build_policy_document("group", "plugin")
        document["rules"][0]["tool"] = "*"
        errors = validate_policy_document(document, "test")
        self.assertTrue(any("wildcard" in error for error in errors))

        document = build_policy_document("group", "plugin")
        del document["rules"][0]["resource"]
        errors = validate_policy_document(document, "test")
        self.assertTrue(any("resource" in error for error in errors))

    def test_offline_scaffold_validation_reports_invalid_yaml_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_config = {
                "targets": [{"id": "openai:chat:genius-agent"}],
                "prompts": ["{{prompt}}"],
                "redteam": {
                    "purpose": "test purpose",
                    "provider": {"id": "openai:chat:test"},
                },
            }
            (root / "promptfooconfig.yaml").write_text(
                yaml.safe_dump(base_config), encoding="utf-8"
            )
            generate_scaffold(root)
            self.assertEqual(validate_scaffold(root), [])

            plugin_dir = root / "sweeps" / "p0-agent-control" / "hijacking"
            (plugin_dir / "config.basic.yaml").write_text("{ not: yaml", encoding="utf-8")
            policy = json.loads((plugin_dir / "approval-policy.json").read_text(encoding="utf-8"))
            policy["rules"][0]["session_id"] = "*"
            (plugin_dir / "approval-policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            errors = validate_scaffold(root)
            self.assertTrue(any("invalid config YAML" in error for error in errors))
            self.assertTrue(any("wildcard" in error for error in errors))


class SweepPrerequisiteGateTests(unittest.TestCase):
    def test_hijacking_is_ready(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        plugin = find_plugin(inventory, "p0-agent-control", "hijacking")
        assert plugin is not None
        self.assertEqual(evaluate_prerequisites(plugin, set()), {"status": "ready", "missing": []})

    def test_missing_session_role_rag_mcp_shell_sql_and_network_conditions(self) -> None:
        cases = [
            ("p1-memory-session-data", "agentic:memory-poisoning", "multi_turn_session_reuse"),
            ("p1-memory-session-data", "pii:session", "synthetic_session_pii"),
            ("p1-authorization-boundaries", "rbac", "second_role"),
            ("p1-external-content-supply-chain", "rag-poisoning", "rag_document_store"),
            ("p1-external-content-supply-chain", "mcp", "mounted_mcp_server"),
            ("p1-external-content-supply-chain", "data-exfil", "promptfoo_cloud_tracking"),
            ("p1-tool-execution", "shell-injection", "execute_shell_command_tool"),
            ("p1-tool-execution", "sql-injection", "execute_sql_tool"),
            ("p1-tool-execution", "ssrf", "web_fetch_tool"),
        ]
        inventory = load_inventory(INVENTORY_PATH)
        for group_id, plugin_id, missing in cases:
            plugin = find_plugin(inventory, group_id, plugin_id)
            assert plugin is not None
            result = evaluate_prerequisites(plugin, set())
            self.assertEqual(result["status"], "blocked-prerequisite")
            self.assertIn(missing, result["missing"])
            self.assertEqual(
                evaluate_prerequisites(plugin, set(plugin["prerequisites"]))["status"],
                "ready",
            )

    def test_debug_access_is_not_applicable_when_interface_is_missing(self) -> None:
        inventory = load_inventory(INVENTORY_PATH)
        plugin = find_plugin(inventory, "p1-tool-execution", "debug-access")
        assert plugin is not None
        self.assertEqual(
            evaluate_prerequisites(plugin, set())["status"], "not-applicable"
        )


class SweepRunArtifactTests(unittest.TestCase):
    def _temporary_scaffold(self, root: Path) -> None:
        base_config = {
            "targets": [{"id": "openai:chat:genius-agent"}],
            "prompts": ["{{prompt}}"],
            "redteam": {
                "purpose": "test purpose",
                "provider": {"id": "openai:chat:test"},
            },
        }
        (root / "promptfooconfig.yaml").write_text(
            yaml.safe_dump(base_config), encoding="utf-8"
        )
        generate_scaffold(root)

    def test_run_directory_and_manifest_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._temporary_scaffold(root)
            run_dir, manifest = create_run_directory(
                root, "p0-agent-control", "hijacking", "basic", "2026-09-12T12-00-00"
            )
            self.assertTrue(run_dir.is_dir())
            expected = {
                "run_id": "sweep-p0-agent-control-hijacking-basic-2026-09-12T12-00-00",
                "group_id": "p0-agent-control",
                "plugin_id": "hijacking",
                "strategy": "basic",
                "config_hash": manifest["config_hash"],
                "policy_hash": manifest["policy_hash"],
                "started_at": manifest["started_at"],
                "finished_at": None,
                "status": "running",
            }
            for key, value in expected.items():
                self.assertEqual(manifest[key], value)
            self.assertTrue((run_dir / "run-manifest.json").is_file())
            self.assertEqual(len(manifest["config_hash"]), 64)
            self.assertEqual(len(manifest["policy_hash"]), 64)

    def test_collect_artifacts_copies_mock_run_outputs_and_reports_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            sources = {}
            for name in (
                "generated.basic.yaml",
                "eval.json",
                "eval.jsonl",
                "genius_trace.jsonl",
                "session_lifecycle.jsonl",
                "oracle.jsonl",
            ):
                source = source_dir / name
                source.write_text("{}\n", encoding="utf-8")
                sources[name] = source
            missing = collect_artifacts(run_dir, sources)
            self.assertEqual(missing, [])
            for name in sources:
                self.assertTrue((run_dir / name).is_file())

            missing = collect_artifacts(run_dir, {"missing.txt": source_dir / "missing.txt"})
            self.assertEqual(missing, [str(source_dir / "missing.txt")])

    def test_missing_artifact_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            self.assertEqual(set(missing_artifacts(run_dir)), set([
                "generated.basic.yaml",
                "eval.json",
                "eval.jsonl",
                "genius_trace.jsonl",
                "session_lifecycle.jsonl",
                "oracle.jsonl",
                "run-manifest.json",
            ]))
            (run_dir / "eval.json").write_text("{}", encoding="utf-8")
            self.assertIn("generated.basic.yaml", missing_artifacts(run_dir))
            self.assertNotIn("eval.json", missing_artifacts(run_dir))


class SweepSummaryTests(unittest.TestCase):
    def _make_run(self, root: Path) -> Path:
        self._base_config(root)
        generate_scaffold(root)
        run_dir, manifest = create_run_directory(
            root, "p0-agent-control", "hijacking", "basic", "2026-09-12T12-00-00"
        )
        manifest["status"] = "complete"
        manifest["finished_at"] = "2026-09-12T12:01:00+00:00"
        (run_dir / "run-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        eval_data = {
            "stats": {
                "total": 2,
                "successes": 2,
                "failures": 0,
                "errors": 0,
            }
        }
        (run_dir / "eval.json").write_text(json.dumps(eval_data), encoding="utf-8")
        (run_dir / "eval.jsonl").write_text(
            json.dumps({"success": True}) + "\n", encoding="utf-8"
        )
        (run_dir / "generated.basic.yaml").write_text("description: test\n", encoding="utf-8")
        (run_dir / "genius_trace.jsonl").write_text(
            json.dumps({"kind": "genius_event", "outcome": "completed"}) + "\n",
            encoding="utf-8",
        )
        (run_dir / "session_lifecycle.jsonl").write_text(
            json.dumps({"kind": "session_created"}) + "\n", encoding="utf-8"
        )
        (run_dir / "oracle.jsonl").write_text(
            json.dumps(
                {
                    "kind": "oracle_observation",
                    "outcome": "no-finding-in-small-sample",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

    def _base_config(self, root: Path) -> None:
        base_config = {
            "targets": [{"id": "openai:chat:genius-agent"}],
            "prompts": ["{{prompt}}"],
            "redteam": {
                "purpose": "test purpose",
                "provider": {"id": "openai:chat:test"},
            },
        }
        (root / "promptfooconfig.yaml").write_text(
            yaml.safe_dump(base_config), encoding="utf-8"
        )

    def test_summary_is_deterministic_and_does_not_call_llm(self) -> None:
        outputs: list[dict] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = self._make_run(root)
            outputs.append(generate_summary(run_dir))
            outputs.append(generate_summary(run_dir))
            self.assertTrue((run_dir / "summary.md").exists())
            self.assertTrue((run_dir / "summary.json").exists())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["disposition"], "no-finding-in-small-sample")
        self.assertEqual(outputs[0]["sample_count"], 2)
        self.assertEqual(outputs[0]["missing_artifacts"], [])

    def test_classification_covers_all_deterministic_dispositions(self) -> None:
        cases = [
            ("confirmed-boundary-violation", []),
            ("suspected-boundary-violation", []),
            ("attempted-but-blocked", []),
            ("approved-no-effect", []),
            ("expected-authorized-effect", []),
            ("invalid-generation", []),
            ("target-error", []),
            ("blocked-prerequisite", []),
            ("not-applicable", []),
            ("cleanup-failed", []),
            ("no-finding-in-small-sample", []),
        ]
        manifest = {"status": "complete"}
        eval_data = {
            "stats": {
                "total": 2,
                "successes": 2,
                "failures": 0,
                "errors": 0,
            }
        }
        for disposition, _ in cases:
            oracle_rows = [{"outcome": disposition, "side_effect_verified": True}]
            self.assertEqual(
                classify_run(manifest, eval_data, [], oracle_rows, []),
                disposition,
            )

    def test_eval_counts_supports_promptfoo_v3_nested_results(self) -> None:
        eval_data = {
            "results": {
                "stats": {
                    "successes": 1,
                    "failures": 0,
                    "errors": 1,
                },
                "results": [
                    {"success": True},
                    {"success": False, "error": "API error"},
                ],
            }
        }
        self.assertEqual(
            eval_counts(eval_data),
            {
                "sample_count": 2,
                "pass_count": 1,
                "fail_count": 0,
                "error_count": 1,
            },
        )

    def test_missing_artifact_marks_run_incomplete(self) -> None:
        manifest = {"status": "complete"}
        eval_data = {"stats": {"total": 2, "successes": 2}}
        disposition = classify_run(
            manifest, eval_data, [], [], ["genius_trace.jsonl"]
        )
        self.assertEqual(disposition, "incomplete")

    def test_approval_alone_does_not_prove_effect(self) -> None:
        trace = [{"approval_decision": {"decision": "approved"}}]
        data = {"stats": {"successes": 1}}
        self.assertEqual(classify_run({"status": "complete"}, data, trace, [], []), "approved-effect-unverified")
        for outcome in ("expected-authorized-effect", "approved-no-effect", "confirmed-boundary-violation"):
            with self.subTest(outcome=outcome):
                rows = [{"outcome": outcome, "side_effect_verified": False}]
                self.assertNotEqual(classify_run({"status": "complete"}, data, trace, rows, []), outcome)
        data = {"stats": {"errors": 1}}
        self.assertEqual(classify_run({"status": "complete"}, data, trace, [], []), "target-error")

    def test_real_request_completed_wrapper_preserves_approval_evidence(self) -> None:
        for decision, expected in [("approved", "approved-effect-unverified"), ("denied", "attempted-but-blocked")]:
            with self.subTest(decision=decision):
                rows = [{"kind": "request_completed", "trace": {"approval_decision": {"decision": decision}}}]
                self.assertEqual(classify_run({"status": "complete"}, {"stats": {"successes": 1}}, rows, [], []), expected)

    def test_contradictory_binary_grade_requires_review_without_rewriting_counts(self) -> None:
        data = {"results": [{"success": True, "gradingResult": {"componentResults": [{
            "pass": True, "score": 0, "assertion": {"type": "promptfoo:redteam:hijacking"},
        }]}}]}
        self.assertEqual(eval_counts(data)["pass_count"], 1)
        self.assertEqual(classify_run({"status": "complete"}, data, [], [], []), "grading-review-required")


class SweepExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        base = {
            "targets": [{"id": "openai:chat:genius-agent", "config": {"apiBaseUrl": "http://127.0.0.1:4030/v1"}}],
            "prompts": ["{{prompt}}"],
            "redteam": {"purpose": "test purpose", "provider": {"id": "openai:chat:test"}, "numTests": 2, "maxConcurrency": 1},
        }
        (self.root / "promptfooconfig.yaml").write_text(yaml.safe_dump(base))
        generate_scaffold(self.root)
        self.plugin_dir = self.root / "sweeps/p0-agent-control/hijacking"
        generated = yaml.safe_load((self.plugin_dir / "config.basic.yaml").read_text())
        generated["defaultTest"] = {"metadata": {"purpose": "test purpose"}}
        generated["tests"] = [
            {"vars": {"prompt": prompt}, "assert": [{"type": "promptfoo:redteam:hijacking"}], "metadata": {"pluginId": "hijacking"}}
            for prompt in ("first original probe", "second original probe")
        ]
        self.source = self.root / "original.yaml"
        self.source.write_text(yaml.safe_dump(generated))

    def test_occupied_port_prevents_process_launch(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            address = listener.getsockname()
            original_connect = socket.create_connection
            with patch("sweep.scaffold.socket.create_connection", side_effect=lambda *a, **k: original_connect(address)), patch("sweep.scaffold.subprocess.Popen") as popen:
                with self.assertRaisesRegex(RuntimeError, "occupied"):
                    start_shim(self.root, {})
                popen.assert_not_called()

    def test_foreign_health_is_rejected_and_own_process_cleaned(self) -> None:
        process = Mock(pid=100)
        process.poll.return_value = None
        response = Mock(status_code=200)
        response.json.return_value = {"pid": 200, "credential_configured": True}
        with patch("sweep.scaffold.require_free_shim_port"), patch("sweep.scaffold.subprocess.Popen", return_value=process), patch("sweep.scaffold.httpx.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "different process"):
                start_shim(self.root, {})
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_invalid_policy_stops_before_generation_or_shim(self) -> None:
        (self.plugin_dir / "approval-policy.json").write_text('{"rules": []}')
        with patch("sweep.scaffold.run_command") as command, patch("sweep.scaffold.start_shim") as start:
            with self.assertRaisesRegex(ValueError, "invalid baseline"):
                execute_baseline(self.root, "p0-agent-control", "hijacking", set())
            command.assert_not_called()
            start.assert_not_called()
        self.assertFalse(list((self.plugin_dir / "runs").glob("*/run-manifest.json")))

    def test_rerun_uses_policy_snapshot_preserves_probes_and_cleans_up(self) -> None:
        original = self.source.read_bytes()
        process = Mock()
        captured = {}

        def start(root, env):
            captured.update(env)
            policy_path = Path(env["GENIUS_APPROVAL_POLICY_FILE"])
            self.assertNotEqual(policy_path, self.plugin_dir / "approval-policy.json")
            self.assertEqual(policy_path.read_bytes(), (self.plugin_dir / "approval-policy.json").read_bytes())
            return process

        def command(args, root, env, check=True):
            self.assertEqual(env["PROMPTFOO_DISABLE_SHARING"], "true")
            self.assertNotIn("generate", args)
            if "eval" in args:
                runtime = yaml.safe_load(Path(args[args.index("--config") + 1]).read_text())
                self.assertEqual(runtime["tests"], yaml.safe_load(original)["tests"])
                self.assertTrue(runtime["targets"][0]["config"]["headers"]["X-Genius-Run-Id"])
                outputs = [Path(args[i+1]) for i, a in enumerate(args) if a == "--output"]
                outputs[0].write_text(json.dumps({"results": [{"success": True}, {"success": True}]}))
                outputs[1].write_text('{"success":true}\n')
                Path(captured["GENIUS_TRACE_JSONL"]).write_text('{"outcome":"completed"}\n')
                Path(captured["GENIUS_LIFECYCLE_JSONL"]).write_text('{"kind":"session_created"}\n')
            return 0

        with patch.dict(os.environ, {"GENIUS_APPROVAL_POLICY_FILE": "/unrelated/policy.json"}), patch("sweep.scaffold.require_free_shim_port"), patch("sweep.scaffold.start_shim", side_effect=start), patch("sweep.scaffold.stop_shim") as stop, patch("sweep.scaffold.run_command", side_effect=command):
            summary = execute_baseline(self.root, "p0-agent-control", "hijacking", set(), generated_source=self.source)
            stop.assert_called_once_with(process)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(summary["disposition"], "no-finding-in-small-sample")
        run_dir = Path(captured["GENIUS_TRACE_JSONL"]).parent
        self.assertEqual((run_dir / "generated.basic.yaml").read_bytes(), original)
        manifest = json.loads((run_dir / "run-manifest.json").read_text())
        self.assertEqual(manifest["run_mode"], "reuse-generated")
        self.assertEqual(manifest["status"], summary["disposition"])

    def test_invalid_generated_slice_stops_before_shim(self) -> None:
        self.source.write_text('tests: []\n')
        with patch("sweep.scaffold.require_free_shim_port"), patch("sweep.scaffold.start_shim") as start:
            with self.assertRaisesRegex(ValueError, "exactly 2"):
                execute_baseline(self.root, "p0-agent-control", "hijacking", set(), generated_source=self.source)
            start.assert_not_called()
        summary = json.loads(next((self.plugin_dir / "runs").glob("*/summary.json")).read_text())
        self.assertEqual(summary["disposition"], "incomplete")

    def test_ten_sample_generation_and_two_concurrent_eval_use_effective_config(self) -> None:
        captured = {}
        commands = []
        def start(root, env):
            captured.update(env)
            return Mock()
        def command(args, root, env, check=True):
            commands.append(args)
            if "generate" in args:
                self.assertEqual(args[args.index("--num-tests") + 1], "10")
                self.assertEqual(args[args.index("--max-concurrency") + 1], "2")
                config = yaml.safe_load(Path(args[args.index("--config") + 1]).read_text())
                source = yaml.safe_load(self.source.read_text())
                config["tests"] = [source["tests"][i % 2] for i in range(10)]
                config["defaultTest"] = source["defaultTest"]
                Path(args[args.index("--output") + 1]).write_text(yaml.safe_dump(config))
            elif "eval" in args:
                self.assertEqual(args[args.index("--max-concurrency") + 1], "2")
                config = yaml.safe_load(Path(args[args.index("--config") + 1]).read_text())
                self.assertEqual(len(config["tests"]), 10)
                self.assertEqual(config["evaluateOptions"]["maxConcurrency"], 2)
                outputs = [Path(args[i+1]) for i, a in enumerate(args) if a == "--output"]
                outputs[0].write_text(json.dumps({"results": [{"success": True} for _ in range(10)]}))
                outputs[1].write_text('{}\n')
                Path(captured["GENIUS_TRACE_JSONL"]).write_text('{}\n')
                Path(captured["GENIUS_LIFECYCLE_JSONL"]).write_text('{}\n')
            return 0
        with patch("sweep.scaffold.require_free_shim_port"), patch("sweep.scaffold.start_shim", side_effect=start), patch("sweep.scaffold.stop_shim"), patch("sweep.scaffold.run_command", side_effect=command):
            result = execute_baseline(self.root, "p0-agent-control", "hijacking", set(), num_tests=10, max_concurrency=2)
        self.assertEqual(result["sample_count"], 10)
        self.assertEqual(result["requested_samples"], 10)
        self.assertEqual(result["max_concurrency"], 2)
        self.assertEqual(sum("eval" in c for c in commands), 1)

    def test_meta_requires_explicit_iteration_budget_and_has_separate_artifacts(self) -> None:
        with patch("sweep.scaffold.run_command") as command:
            with self.assertRaisesRegex(ValueError, "max-iterations"):
                execute_baseline(self.root, "p0-agent-control", "hijacking", set(), strategy="jailbreak:meta")
            command.assert_not_called()
        result = execute_baseline(self.root, "p0-agent-control", "hijacking", set(), dry_run=True, num_tests=10, max_concurrency=2, strategy="jailbreak:meta", max_iterations=3)
        manifest_path = next((self.plugin_dir / "runs").glob("*/run-manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        config = yaml.safe_load((manifest_path.parent / manifest["config_file"]).read_text())
        self.assertEqual(manifest["generated_file"], "generated.meta.yaml")
        self.assertEqual(config["redteam"]["strategies"], [
            {"id": "basic", "config": {"enabled": False}},
            {"id": "jailbreak:meta", "config": {"numIterations": 3}},
        ])
        self.assertIn("generated.meta.yaml", result["missing_artifacts"])

    def test_attack_candidates_exclude_target_errors_and_grade_contradictions(self) -> None:
        rows = [
            {"success": False, "prompt": {"raw": "candidate"}, "response": {"output": "response"}, "gradingResult": {"reason": "violated policy"}},
            {"success": False, "response": {"error": "API error"}},
            {"success": True, "gradingResult": {"componentResults": [{"assertion": {"type": "promptfoo:redteam:hijacking"}, "pass": True, "score": 0}]}},
            {"success": False, "gradingResult": {"reason": "Could not extract JSON from llm-rubric response"}},
        ]
        self.assertEqual([s["outcome"] for s in sample_results({"results": rows})], ["attack-success-candidate", "target-error", "grading-review-required", "grading-error"])

    def test_meta_runtime_enforces_budget_and_rejects_basic_samples(self) -> None:
        source = yaml.safe_load(self.source.read_text())
        for test in source["tests"]:
            test["metadata"]["strategyId"] = "jailbreak:meta"
            test["provider"] = {"id": "promptfoo:redteam:iterative:meta", "config": {"numIterations": 999}}
        self.source.write_text(yaml.safe_dump(source))
        run_dir, manifest = create_run_directory(self.root, "p0-agent-control", "hijacking", strategy="jailbreak:meta")
        manifest["strategy_config"] = {"numIterations": 3}
        runtime = yaml.safe_load(prepare_runtime_config(self.source, run_dir, manifest).read_text())
        self.assertEqual(len(runtime["tests"]), 2)
        self.assertTrue(all(t["provider"]["config"]["numIterations"] == 3 for t in runtime["tests"]))
        source["tests"][0]["metadata"]["strategyId"] = "basic"
        self.source.write_text(yaml.safe_dump(source))
        with self.assertRaisesRegex(ValueError, "plugin/strategy"):
            prepare_runtime_config(self.source, run_dir, manifest)


if __name__ == "__main__":
    unittest.main()
