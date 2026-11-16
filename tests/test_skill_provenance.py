"""Asset lineage contracts; all imports/service receipts here are fixtures."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from skill_suite.audit import source_audit
from skill_suite.provenance import snapshot_asset, validate_asset, validate_index, validate_runtime_asset
from skill_suite.registry import validate_skill
from skill_suite.report import summarize
from skill_suite.runner import call_bound_case
from sweep.runtime import sha256_file, write_json
from tests import test_skill_suite as suite_fixtures

ASSETS = suite_fixtures.PROJECT / "skill-suites/skill-task-scope-write/assets"


class AssetProvenanceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / "source"; self.root.mkdir()
        path = self.root / "notes.md"; path.write_text("Read only and summarize.")
        self.ref = {"file": "notes.md", "sha256": sha256_file(path)}
        self.record = {"schema_version": 1, "kind": "skill-asset-provenance", "asset_id": "notes-a124",
            "origin": {"kind": "local-original", "author": "Codex", "source_format": "Markdown",
                "source_locator": None, "commit": None, "license_status": "project-original",
                "license_note": "Original text", "authoring_note": "Authored for this local fixture"},
            "material_kind": "skill-artifact", "intended_use": "runtime-skill", "files": [self.ref],
            "adaptation": None, "genius_ground_truth": False}

    def proof(self):
        path = self.root / "provenance.json"; write_json(path, self.record)
        return {"file": path.name, "sha256": sha256_file(path)}

    def test_actual_prepared_normal_assets_have_exact_original_files_and_no_ground_truth(self):
        result = validate_index(ASSETS / "asset-provenance.json")
        self.assertEqual(result["asset_count"], 2); self.assertFalse(result["genius_ground_truth"])
        for asset in result["assets"]:
            self.assertEqual(asset["origin"], "local-original")
            self.assertEqual(len(asset["runtime_files"]), 2)
        with patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("httpx.Client", side_effect=AssertionError("provider")):
            self.assertEqual(validate_index(ASSETS / "asset-provenance.json")["actual_calls"]["target"], 0)

    def test_live_skill_requires_provenance_and_byte_identity_without_newline_normalization(self):
        row = {"environment": "live", "artifact_file": "notes.md", "asset_hash": self.ref["sha256"]}
        with self.assertRaises(ValueError): validate_runtime_asset(self.root, row)
        row["provenance_ref"] = self.proof()
        self.assertEqual(validate_runtime_asset(self.root, row)["asset_id"], "notes-a124")
        (self.root / "notes.md").write_bytes(b"Read only and summarize.\r\n")
        with self.assertRaises(ValueError): validate_runtime_asset(self.root, row)

    def test_research_trajectory_scanner_and_mock_cannot_become_runtime_or_ground_truth(self):
        for kind in ("research-seed", "trajectory", "scanner-template", "mock"):
            value = copy.deepcopy(self.record); value.update(material_kind=kind, intended_use="offline-fixture")
            self.assertFalse(validate_asset(value, self.root)["genius_ground_truth"])
            with self.assertRaises(ValueError): validate_asset(value, self.root, runtime=True)
            value["intended_use"] = "runtime-skill"
            with self.assertRaises(ValueError): validate_asset(value, self.root)
        value = copy.deepcopy(self.record); value["genius_ground_truth"] = True
        with self.assertRaises(ValueError): validate_asset(value, self.root)

    def test_external_material_needs_pin_license_and_adaptation_hashes(self):
        commit = "a" * 40
        value = copy.deepcopy(self.record)
        value["origin"].update(kind="external", source_locator=f"https://upstream.invalid/repo/blob/{commit}/notes.md",
                               commit=commit, license_status="confirmed")
        value.update(material_kind="trajectory", intended_use="generation-seed")
        validate_asset(value, self.root)
        for change in ({"commit": "main"}, {"license_status": "unverified"}, {"source_locator": "https://upstream.invalid/repo/main"}):
            altered = copy.deepcopy(value); altered["origin"].update(change)
            with self.assertRaises(ValueError): validate_asset(altered, self.root)
        path = self.root / "adapted.md"; path.write_text("Use read-state to summarize the designated record.")
        output_ref = {"file": path.name, "sha256": sha256_file(path)}
        value.update(intended_use="runtime-skill", adaptation={"method": "manual-skill-conversion",
            "input_hashes": [self.ref["sha256"]], "output_files": [output_ref], "notes": "Trajectory labels removed; authored a Skill carrier"})
        result = validate_asset(value, self.root, runtime=True)
        self.assertFalse(result["genius_ground_truth"]); self.assertIn("adapted.md", result["runtime_files"])
        value["adaptation"]["input_hashes"] = ["0" * 64]
        with self.assertRaises(ValueError): validate_asset(value, self.root)

    def test_snapshot_preserves_original_and_revalidates_copied_hashes(self):
        ref = self.proof(); before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        target = self.base / "snapshot"; snapshot_asset(self.root, ref, target)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})
        with self.assertRaises(ValueError): snapshot_asset(self.root, ref, target)
        with self.assertRaises(ValueError): snapshot_asset(self.root, ref, self.root / "inside")

    def test_snapshot_inside_run_resolves_bundle_files_and_enforces_run_boundary(self):
        ref = self.proof(); run = self.base / "run"; run.mkdir()
        copied = snapshot_asset(self.root, ref, run / "lineage")
        row = {"environment": "live", "artifact_file": "lineage/notes.md", "asset_hash": self.ref["sha256"],
            "provenance_ref": {"file": "lineage/" + copied["file"], "sha256": copied["sha256"]}}
        self.assertEqual(validate_runtime_asset(run, row)["asset_id"], "notes-a124")
        row["provenance_ref"]["file"] = "../source/provenance.json"
        with self.assertRaises(ValueError): validate_runtime_asset(run, row)

    def test_source_audit_does_not_promote_a_mock_asset_even_after_successful_import(self):
        row = suite_fixtures.case(suite_fixtures.suite()); skill, refs = suite_fixtures.source_fixture(self.root, row)
        self.record.update(material_kind="mock", intended_use="offline-fixture", files=[{"file": "original.md", "sha256": row["asset_hash"]}])
        skill["provenance_ref"] = self.proof()
        with self.assertRaises(ValueError): validate_skill(skill, self.root, row)
        audit = source_audit(row, skill, refs, self.root)
        self.assertFalse(audit["source_verified"]); self.assertFalse(audit["behavior_followed"])

    def test_research_label_cannot_enter_judge_or_independent_oracle_denominator(self):
        for kind in ("trajectory", "mock", "scanner-template"):
            row = {"case_id": "notes-1", "model_profile": "default", "variant": "attack", "evidence_kind": kind,
                "environment": "live", "source_verified": True, "control_valid": True, "state_verified": True,
                "boundary_violation": True, "judge": {"pass": False, "score": 0}}
            result = summarize({"run_id": "notes-1", "phase": "C"}, [row], self.root)["models"]["default"]
            self.assertEqual(result["raw_judge"]["fail"], 1)
            self.assertEqual(result["judge"]["denominator"], 0); self.assertEqual(result["oracle"]["denominator"], 0)
            self.assertIn("research-label-is-not-Genius-evidence", result["excluded"][0]["oracle"])


class ProvenanceExecutionGate(unittest.TestCase):
    def test_wrong_asset_role_blocks_service_factory(self):
        fixture = suite_fixtures.OfflineContracts(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run, row = fixture.prepared_case()
        data = {"schema_version": 1, "kind": "skill-asset-provenance", "asset_id": "notes-1",
            "origin": {"kind": "local-original", "author": "Codex", "source_format": "Markdown", "source_locator": None,
                "commit": None, "license_status": "project-original", "license_note": "Original fixture", "authoring_note": "Fixture"},
            "material_kind": "mock", "intended_use": "offline-fixture", "files": [{"file": "original.md", "sha256": row["asset_hash"]}],
            "adaptation": None, "genius_ground_truth": False}
        path = run / "provenance.json"; write_json(path, data)
        skill = json.loads((run / "skill-registry.jsonl").read_text()); skill["provenance_ref"] = {"file": path.name, "sha256": sha256_file(path)}
        (run / "skill-registry.jsonl").write_text(json.dumps(skill) + "\n")
        factory = Mock()
        with self.assertRaises(ValueError): call_bound_case(fixture.root, run, (row["case_id"], row["model_profile"], row["variant"]), factory, live=False)
        factory.assert_not_called()
        self.assertEqual(json.loads((run / "call-ledger.json").read_text())["counts"]["target"], 0)


if __name__ == "__main__": unittest.main()
