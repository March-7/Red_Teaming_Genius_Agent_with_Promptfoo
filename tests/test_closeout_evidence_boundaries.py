"""Self-contained checks for evidence gates without private run artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.dual_gate_taxonomy import _ref as taxonomy_ref
from skill_suite.risk_cards import validate_capabilities


class EvidenceBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence.txt"
        self.evidence.write_bytes(b"synthetic evidence fixture\n")
        self.ref = {"file": "evidence.txt", "sha256": hashlib.sha256(self.evidence.read_bytes()).hexdigest()}
        self.registry = self.root / "registry.json"
        self.data = {
            "schema_version": 1,
            "kind": "genius-capability-registry",
            "target_context": "global-general",
            "checked_at": "2026-11-16",
            "capabilities": [{"capability_id": "fixture-capability", "status": "verified",
                              "evidence_refs": [self.ref], "limits": "Synthetic fixture only."}],
        }
        self.registry.write_text(json.dumps(self.data))

    def test_matching_fixture_is_accepted_by_both_gates(self):
        self.assertEqual(validate_capabilities(self.registry, self.root)["capabilities"][0]["status"], "verified")
        self.assertEqual(taxonomy_ref(self.root, self.ref, "fixture"), self.evidence.resolve())

    def test_missing_evidence_is_rejected_by_both_gates(self):
        self.evidence.unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            validate_capabilities(self.registry, self.root)
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            taxonomy_ref(self.root, self.ref, "fixture")

    def test_changed_evidence_is_rejected_by_both_gates(self):
        self.evidence.write_bytes(b"changed fixture\n")
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            validate_capabilities(self.registry, self.root)
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            taxonomy_ref(self.root, self.ref, "fixture")

    def test_outside_root_is_rejected(self):
        ref = {"file": "../evidence.txt", "sha256": self.ref["sha256"]}
        self.data["capabilities"][0]["evidence_refs"] = [ref]
        self.registry.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            validate_capabilities(self.registry, self.root)
        with self.assertRaises(ValueError):
            taxonomy_ref(self.root, ref, "fixture")


if __name__ == "__main__":
    unittest.main()
