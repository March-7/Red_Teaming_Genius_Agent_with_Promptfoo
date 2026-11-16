"""Standing pilot master plan is offline, bounded, and source pinned."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from skill_suite.pilot_plan import dry_run, validate_authorization
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
KWARGS = {"project_root": ROOT, "card_index_path": BASE / "risk-cards/index.json",
    "capability_path": BASE / "capability-registry.json",
    "source_registry_path": BASE / "source-registry.json",
    "source_inventory_path": BASE / "source-inventory.jsonl",
    "source_inventory_summary_path": BASE / "source-inventory-summary.json",
    "relationship_summary_path": BASE / "relationships/summary.json"}


class PilotPlanContract(unittest.TestCase):
    def test_dry_run_reads_no_credentials_and_makes_no_network_calls(self):
        with patch.object(socket, "create_connection") as network, \
             patch.dict(os.environ, {}, clear=True):
            result = dry_run(BASE / "pilot-master-plan.json",
                BASE / "standing-authorization.json", BASE / "risk-shortlist.json", **KWARGS)
        network.assert_not_called()
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["credential_reads"], 0)
        self.assertEqual(result["planned_limits"]["target"], 90)
        self.assertEqual(result["remaining_after_plans"]["target"], 6)
        self.assertEqual((result["generation_calls"], result["judge_calls"]), (0, 0))

    def test_authorization_and_plan_budget_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authorization = json.loads((BASE / "standing-authorization.json").read_text())
            authorization["limits"]["target"] = 97
            auth_path = root / "authorization.json"
            write_json(auth_path, authorization)
            with self.assertRaisesRegex(ValueError, "authorization"):
                validate_authorization(auth_path, BASE / "pilot-cases/index.json",
                                       BASE / "risk-shortlist.json")
            plan = json.loads((BASE / "pilot-master-plan.json").read_text())
            plan["workers"][0]["limits"]["judge"] = 1
            plan_path = root / "plan.json"
            write_json(plan_path, plan)
            with self.assertRaises(ValueError):
                dry_run(plan_path, BASE / "standing-authorization.json",
                        BASE / "risk-shortlist.json", **KWARGS)


if __name__ == "__main__":
    unittest.main()
