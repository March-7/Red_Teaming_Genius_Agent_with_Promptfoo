"""Tracked benchmark relationships remain source-bound and claim-only."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skill_suite.benchmark_extraction import validate_relationships
from sweep.runtime import sha256_file, write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


class BenchmarkExtractionContract(unittest.TestCase):
    def validate(self, output=BASE / "relationships"):
        return validate_relationships(BASE / "source-registry.json",
            BASE / "source-inventory.jsonl", BASE / "source-inventory-summary.json", output)

    def test_tracked_relationships_have_expected_counts_and_no_promoted_claims(self):
        result = self.validate()
        self.assertEqual(result["counts"]["malskillbench_malware_packages"], 3944)
        self.assertEqual(result["counts"]["malskillbench_benign_packages"], 4000)
        self.assertEqual(result["counts"]["skillsbench_tasks"], 87)
        self.assertEqual(result["counts"]["skill_inject_missing_task_file_links"], 6)
        self.assertEqual((result["scripts_executed"], result["content_copied"]), (0, False))

    def test_hash_rewrite_cannot_promote_upstream_label_to_genius_finding(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "relationships"
            shutil.copytree(BASE / "relationships", output)
            document_path = output / "aig-skilljack.json"
            document = json.loads(document_path.read_text())
            document["trajectories"][0]["genius_ground_truth"] = True
            write_json(document_path, document)
            summary_path = output / "summary.json"
            summary = json.loads(summary_path.read_text())
            next(row for row in summary["relationships"]
                 if row["source_id"] == "aig-skilljack")["sha256"] = sha256_file(document_path)
            write_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "promoted"):
                self.validate(output)


if __name__ == "__main__":
    unittest.main()
