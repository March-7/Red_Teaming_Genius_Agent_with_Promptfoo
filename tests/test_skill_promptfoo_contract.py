"""Installed Promptfoo custom plugin QA with a local provider and blocked network."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from skill_suite import campaign
from skill_suite.generation_pipeline import normalize_fixture
from sweep.inventory import load_inventory, validate_inventory
from sweep.runtime import sha256_file


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "skill-suites/skill-task-scope-write/promptfoo/offline-config.yaml"
MATRIX_CONFIG = CONFIG.parent / "offline-matrix-config.yaml"
NETWORK_GUARD = CONFIG.parent / "no-network.cjs"
PROMPTFOO = ROOT / "node_modules/.bin/promptfoo"


class SkillPromptfooContract(unittest.TestCase):
    def test_custom_plugin_generates_skill_payload_with_candidate_grader_only(self):
        if not PROMPTFOO.is_file():
            self.skipTest("pinned Promptfoo installation unavailable")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "generated.yaml"
            audit = base / "provider-calls.jsonl"
            env = {**os.environ, "PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION": "1",
                "PROMPTFOO_DISABLE_UPDATE": "true", "PROMPTFOO_DISABLE_TELEMETRY": "1",
                "SKILL_OFFLINE_PROVIDER_AUDIT": str(audit),
                "NODE_OPTIONS": f"--require={NETWORK_GUARD}"}
            command = [str(PROMPTFOO), "redteam", "generate", "-c", str(CONFIG), "-o", str(output),
                       "--no-cache", "--force", "--no-progress-bar", "--strict"]
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout[-1600:] + result.stderr[-1600:])
            calls = [json.loads(line) for line in audit.read_text().splitlines()]
            self.assertEqual(len(calls), 1, "hidden generator retries or extraction calls are not allowed")
            generated = yaml.safe_load(output.read_text())
            self.assertEqual(len(generated["tests"]), 1)
            test = generated["tests"][0]
            self.assertEqual(set(test["vars"]), {"skill_payload"})
            payload = json.loads(test["vars"]["skill_payload"])
            self.assertEqual(set(payload), {"skill_key", "effect_artifact_name", "normal", "attack", "tasks"})
            self.assertEqual(len(payload["tasks"]), 10)
            self.assertNotIn(payload["effect_artifact_name"], payload["normal"])
            self.assertIn(payload["effect_artifact_name"], payload["attack"])
            self.assertIn(";", payload["normal"])
            self.assertTrue(all(payload["effect_artifact_name"] not in task["user_task_template"]
                                for task in payload["tasks"]))
            self.assertEqual(test["assert"][0]["type"], "llm-rubric")
            self.assertEqual(test["assert"][0]["metric"], "skill-write-candidate")
            self.assertIn("independent artifact readback", test["assert"][0]["value"])
            self.assertEqual(test["metadata"]["pluginId"], "file://./custom-skill-plugin.yaml")
            self.assertEqual(generated["targets"][0]["label"], "offline-generation-only")

    def test_custom_plugin_remains_outside_old_builtin_inventory(self):
        inventory = load_inventory(ROOT / "sweeps/inventory.json")
        self.assertEqual(validate_inventory(inventory), [])
        changed = copy.deepcopy(inventory)
        changed["groups"][0]["plugins"].append({"id": "file://./custom-skill-plugin.yaml",
                                                  "prerequisites": [], "status": "ready"})
        self.assertTrue(any("unsupported plugin id" in error for error in validate_inventory(changed)))

    def test_ten_skill_raw_promptfoo_export_normalizes_to_400_without_live_evidence(self):
        if not PROMPTFOO.is_file():
            self.skipTest("pinned Promptfoo installation unavailable")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            generated, audit, normalized = (base / name for name in
                ("generated.yaml", "provider-calls.jsonl", "normalized"))
            env = {**os.environ, "PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION": "1",
                "PROMPTFOO_DISABLE_UPDATE": "true", "PROMPTFOO_DISABLE_TELEMETRY": "1",
                "SKILL_OFFLINE_PROVIDER_AUDIT": str(audit),
                "NODE_OPTIONS": f"--require={NETWORK_GUARD}"}
            command = [str(PROMPTFOO), "redteam", "generate", "-c", str(MATRIX_CONFIG),
                       "-o", str(generated), "--no-cache", "--force", "--no-progress-bar", "--strict"]
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout[-1600:] + result.stderr[-1600:])
            self.assertEqual(len(audit.read_text().splitlines()), 1)
            outcome = normalize_fixture(generated, audit, normalized, "reading-c-fixture-a124")
            self.assertEqual((outcome["skill_count"], outcome["combination_count"],
                              outcome["matrix_rows"], outcome["formal_ready"]), (10, 100, 400, False))
            plan = json.loads((normalized / "campaign-plan.json").read_text())
            cases = campaign.validate_plan(plan, normalized)
            rows = [json.loads(line) for line in (normalized / "formal-matrix-preview.jsonl").read_text().splitlines()]
            campaign.validate_matrix(plan, cases, rows)
            self.assertEqual(plan["generation"]["origin"], "offline-fixture")
            self.assertEqual(len({case["effect_artifact_name"] for case in cases}), 10)
            self.assertTrue(all(row["locators"]["record_id"] not in row["user_task"] for row in rows))
            review = json.loads((normalized / "campaign-review-template.json").read_text())
            self.assertEqual(len(review["records"]), 100)
            self.assertTrue(all(row["decision"] == "pending" for row in review["records"]))
            source = json.loads((normalized / "source-manifest.json").read_text())
            self.assertEqual(source["actual_calls"], {"target": 0, "generation_live": 0,
                                                      "judge": 0, "management": 0})
            self.assertTrue(all(sha256_file(normalized / name) == digest
                                for name, digest in source["artifact_hashes"].items()))
            changed = json.loads(audit.read_text().strip())
            changed["response_output"] = changed["response_output"].replace(
                "reading-note-00-a124b5c6.md", "reading-note-other.md")
            tampered = base / "tampered-audit.jsonl"
            tampered.write_text(json.dumps(changed) + "\n")
            with self.assertRaisesRegex(ValueError, "differ"):
                normalize_fixture(generated, tampered, base / "rejected", "reading-c-fixture-a124")
            self.assertFalse((base / "rejected").exists())


if __name__ == "__main__":
    unittest.main()
