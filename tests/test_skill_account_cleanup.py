"""Tracked project-owned Genius Skill cleanup evidence remains exact."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.account_skill_cleanup import validate_summary
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "skill-suites/benchmark-multi-risk/account-skill-cleanup/summary.json"


class AccountSkillCleanupContract(unittest.TestCase):
    def test_real_cleanup_deleted_only_project_owned_skills(self):
        result = validate_summary(ROOT, SUMMARY)
        self.assertEqual((result["deleted_skills"], result["verified_404"]), (133, 133))
        self.assertEqual(result["remaining_project_owned"], 0)
        self.assertEqual(result["unowned_preserved"], 21)
        self.assertEqual((result["target_calls"], result["generation_calls"],
                          result["judge_calls"]), (0, 0, 0))

    def test_cleanup_overclaim_fails_closed(self):
        value = json.loads(SUMMARY.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.json"
            value["project_owned_deleted"] = 134
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "boundary drift"):
                validate_summary(ROOT, path)


if __name__ == "__main__":
    unittest.main()
