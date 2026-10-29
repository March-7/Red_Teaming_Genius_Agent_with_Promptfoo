"""Evidence-linked candidate revisions preserve the standing budget and risk meaning."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.revised_pilot import validate_master


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
MASTER = BASE / "pilot-master-plan-v2.json"
AUTH = BASE / "standing-authorization-extension.json"


class RevisedPilotContract(unittest.TestCase):
    def test_real_revision_master_validates(self):
        result = validate_master(ROOT, MASTER, AUTH)
        self.assertTrue(result["valid"])
        self.assertEqual(result["worker_count"], 4)
        self.assertEqual(result["candidate_iterations_total"], 14)
        self.assertEqual(result["candidate_iteration_cap"], 22)
        self.assertEqual(result["planned_limits"]["target"], 24)
        self.assertFalse(result["formal_asr_eligible"])

    def _validate_mutated(self, *, master_change=None, auth_change=None):
        master = json.loads(MASTER.read_text())
        auth = json.loads(AUTH.read_text())
        if master_change:
            master_change(master)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master_path = root / "master.json"
            auth_path = root / "auth.json"
            master_path.write_text(json.dumps(master))
            from sweep.runtime import sha256_file
            auth["revision_master_sha256"] = sha256_file(master_path)
            if auth_change:
                auth_change(auth)
            auth_path.write_text(json.dumps(auth))
            return validate_master(ROOT, master_path, auth_path)

    def test_rejects_budget_and_cap_drift(self):
        with self.assertRaisesRegex(ValueError, "master boundary drift"):
            self._validate_mutated(master_change=lambda value:
                value["planned_limits"].update(target=25))
        with self.assertRaisesRegex(ValueError, "user authorization drift"):
            self._validate_mutated(auth_change=lambda value:
                value.update(candidate_iteration_cap=14))

    def test_rejects_parent_hash_and_risk_semantics_drift(self):
        source = json.loads(MASTER.read_text())
        worker = copy.deepcopy(source["workers"][0])
        revision_path = Path(worker["revision_file"])
        revision = json.loads(revision_path.read_text())
        case_path = Path(worker["case_file"])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            changed_revision = td / "revision.json"
            revision["risk_semantics_changed"] = True
            changed_revision.write_text(json.dumps(revision))
            from sweep.runtime import sha256_file
            worker["revision_file"] = str(changed_revision)
            worker["revision_sha256"] = sha256_file(changed_revision)
            source["workers"][0] = worker
            master_path = td / "master.json"
            master_path.write_text(json.dumps(source))
            auth = json.loads(AUTH.read_text())
            auth["revision_master_sha256"] = sha256_file(master_path)
            auth_path = td / "auth.json"
            auth_path.write_text(json.dumps(auth))
            with self.assertRaisesRegex(ValueError, "revision scope invalid"):
                validate_master(ROOT, master_path, auth_path)

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            changed_revision = td / "revision.json"
            revision = json.loads(revision_path.read_text())
            revision["parent_case_ref"]["sha256"] = "0" * 64
            changed_revision.write_text(json.dumps(revision))
            worker = copy.deepcopy(json.loads(MASTER.read_text())["workers"][0])
            worker["revision_file"] = str(changed_revision)
            worker["revision_sha256"] = sha256_file(changed_revision)
            master = json.loads(MASTER.read_text())
            master["workers"][0] = worker
            master_path = td / "master.json"
            master_path.write_text(json.dumps(master))
            auth = json.loads(AUTH.read_text())
            auth["revision_master_sha256"] = sha256_file(master_path)
            auth_path = td / "auth.json"
            auth_path.write_text(json.dumps(auth))
            with self.assertRaisesRegex(ValueError, "parent ref drift"):
                validate_master(ROOT, master_path, auth_path)


if __name__ == "__main__":
    unittest.main()
