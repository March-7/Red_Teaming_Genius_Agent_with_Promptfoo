"""Public benchmark source registry contracts; fixture files are metadata only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.benchmark_registry import validate_inventory, validate_registry
from sweep.runtime import sha256_file, write_json


class BenchmarkRegistryContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = []
        dispositions = {
            "aig-skilljack": ("research-only", "pattern-only"),
            "skill-inject": ("ambiguous-attribution", "metadata-only"),
            "malskillbench": ("academic-research-only", "pattern-only"),
            "skillsbench": ("confirmed-open", "minimal-adaptation"),
            "malicious-agent-skills": ("confirmed-open", "minimal-adaptation"),
            "skillleakbench": ("confirmed-open", "minimal-adaptation"),
            "skillfortifybench": ("confirmed-open", "minimal-adaptation"),
            "oasb": ("confirmed-open", "pattern-only"),
            "agent-skill-security": ("ambiguous-attribution", "metadata-only"),
            "scr-bench": ("confirmed-open", "minimal-adaptation"),
            "skilllifebench": ("ambiguous-attribution", "metadata-only"),
            "harmfulskillbench": ("confirmed-open", "pattern-only"),
        }
        for index, (source_id, (license_disposition, ceiling)) in enumerate(dispositions.items()):
            commit = f"{index + 1:040x}"
            self.sources.append({"source_id": source_id,
                "repository_url": f"https://github.com/example/{source_id}",
                "pinned_commit": commit, "pinned_ref": "fixture",
                "pinned_url": f"https://github.com/example/{source_id}/tree/{commit}",
                "tree_hash": f"{index + 101:040x}",
                "root_license": {"path": "LICENSE",
                    "sha256": hashlib.sha256(source_id.encode()).hexdigest()},
                "license_expression": "fixture", "license_observation": "fixture evidence",
                "license_disposition": license_disposition,
                "content_reuse_ceiling": ceiling, "third_party_note": "fixture",
                "relevant_roots": ["README.md"],
                "upstream_claims": [{"kind": "count", "value": 1,
                    "evidence_path": "README.md", "genius_ground_truth": False}]})
        self.registry = {"schema_version": 1, "kind": "skill-benchmark-source-registry",
                         "checked_at": "2026-10-05", "sources": self.sources}
        self.registry_path = self.root / "registry.json"
        write_json(self.registry_path, self.registry)

    def test_license_limits_and_upstream_claims_fail_closed(self):
        self.assertEqual(len(validate_registry(self.registry_path)["sources"]), 12)
        for mutate in (
            lambda value: value["sources"][1].update(content_reuse_ceiling="direct-reuse"),
            lambda value: value["sources"][0]["upstream_claims"][0].update(
                genius_ground_truth=True),
            lambda value: value["sources"][2].update(pinned_commit="main"),
            lambda value: value["sources"][3].update(
                pinned_url="https://github.com/example/skillsbench/tree/main"),
            lambda value: value["sources"][3].update(
                root_license={"path": None, "sha256": None}),
            lambda value: value["sources"][0].update(third_party_note=""),
            lambda value: value["sources"][2].pop("license_observation"),
        ):
            changed = copy.deepcopy(self.registry)
            mutate(changed)
            write_json(self.registry_path, changed)
            with self.assertRaises(ValueError):
                validate_registry(self.registry_path)
        write_json(self.registry_path, self.registry)

    def test_inventory_hash_and_metadata_only_contract(self):
        inventory = self.root / "inventory.jsonl"
        rows = []
        for source in self.sources:
            rows.append({"schema_version": 1, "kind": "skill-benchmark-source-asset",
                "source_id": source["source_id"], "path": "README.md",
                "hash_algorithm": "sha256", "content_hash": "a" * 64,
                "size_bytes": 10, "asset_kind": "documentation",
                "executable_content": False, "archive_not_expanded": False,
                "content_stored": False, "genius_ground_truth": False})
        inventory.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        summary = self.root / "summary.json"
        write_json(summary, {"schema_version": 1,
            "kind": "skill-benchmark-source-inventory-summary",
            "registry_file": str(self.registry_path),
            "registry_sha256": sha256_file(self.registry_path),
            "inventory_file": str(inventory), "inventory_sha256": sha256_file(inventory),
            "source_count": 12, "asset_count": 12, "sources": [],
            "scripts_executed": 0, "archives_expanded": 0,
            "network_actions": "none", "genius_ground_truth": False})
        self.assertTrue(validate_inventory(self.registry_path, inventory, summary)["valid"])
        rows[0]["content_stored"] = True
        inventory.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        with self.assertRaises(ValueError):
            validate_inventory(self.registry_path, inventory, summary)


if __name__ == "__main__":
    unittest.main()
