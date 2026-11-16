"""Sealed-result replay contracts; all evidence here is local fixture data."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sweep.runtime import sha256_file, write_json
from skill_suite.formal_prestart_cleanup import execute as execute_prestart_cleanup, LIMITS as CLEANUP_LIMITS
from skill_suite.formal_results import replay_row
from skill_suite.registry import ResourceRegistry
from skill_suite.schema import text_hash
from shim.genius_service import ShimConfig


class FormalReplayContract(unittest.TestCase):
    def test_superseded_prestart_cleanup_never_calls_management_or_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master_dir = root / "master"
            master_dir.mkdir()
            master_path = master_dir / "formal-worker-plan.json"
            write_json(master_path, {"run_id": "reading-formal-a1b2c3d4",
                                     "frozen_manifest_sha256": "a" * 64})
            write_json(master_dir / "formal-worker-authorization.json", {
                "actor": "human-user", "decision": "start-formal-target-collection",
                "plan_sha256": sha256_file(master_path),
                "message_ref": "unit fixture only",
                "bundle_file": str(root / "bundle/formal-start-bundle.json")})
            pilot = root / "pilot-result.json"
            write_json(pilot, {"status": "fixture"})
            items = []
            expected = {}
            for index in range(6):
                owner = "reading-d-a1b2c3d4" if index < 2 else "reading-d-e5f6a7b8"
                registry_path = root / owner / "resource-registry.jsonl"
                registry_path.parent.mkdir(exist_ok=True)
                skill_id = f"skill-a1b2c3d4-{index:02d}"
                name = f"research-notes-a1b2c3d4-{index:02d}"
                registry = ResourceRegistry(registry_path, owner)
                registry.record(skill_id, "skill", name, "created",
                                owner_run_id=owner, shared=False, environment="live")
                binding_path = registry_path.parent / f"binding-{index:02d}.json"
                write_json(binding_path, {"skill_id": skill_id})
                items.append({"name": name, "skill_id": skill_id,
                    "principal_id": "usr_fixture", "skill_version": "1",
                    "owner_run_id": owner,
                    "registry_file": str(registry_path),
                    "registry_sha256": sha256_file(registry_path),
                    "binding_file": str(binding_path),
                    "binding_sha256": sha256_file(binding_path)})
                expected[skill_id] = {"name": name, "live": True}
            output = root / "cleanup"
            output.mkdir()
            packet = {"kind": "skill-formal-prestart-cleanup",
                "status": "not-authorized", "master_plan_file": str(master_path),
                "master_plan_sha256": sha256_file(master_path),
                "source_frozen_manifest_sha256": "a" * 64,
                "api_pilot_ref": {"file": str(pilot), "sha256": sha256_file(pilot)},
                "limits": CLEANUP_LIMITS, "retry": 0,
                "method_sequence": ["GET", "DELETE", "GET"],
                "execution_code_sha256": sha256_file(Path(__file__).parent.parent /
                    "skill_suite/formal_prestart_cleanup.py"), "items": items}
            write_json(output / "cleanup-plan.json", packet)

            class Response:
                def __init__(self, status, body=None):
                    self.status_code, self.body = status, body
                def json(self):
                    return self.body

            class Client:
                def __init__(self):
                    self.calls = []
                def request(self, method, url, *, headers):
                    skill_id = url.rsplit("/", 1)[-1]
                    item = expected[skill_id]
                    self.calls.append((method, skill_id))
                    if method == "DELETE":
                        if not item["live"]:
                            return Response(404)
                        item["live"] = False
                        return Response(200, {"deleted": True})
                    if not item["live"]:
                        return Response(404)
                    return Response(200, {"skill": {"skill_id": skill_id,
                        "name": item["name"], "owner_id": "usr_fixture",
                        "visibility": "private", "version": 1}})

            client = Client()
            class Service:
                def __init__(self, config):
                    self._client = client
                def _headers(self):
                    return {"Authorization": "Bearer fixture-only"}
                def close(self):
                    pass

            config = ShimConfig(upstream_base_url="https://fixture.invalid",
                                upstream_authorization="Bearer fixture-only")
            with patch("sweep.runtime.require_free_shim_port"), \
                 patch("skill_suite.formal_prestart_cleanup.load_dotenv"), \
                 patch("shim.genius_service.ShimConfig.from_env", return_value=config), \
                 patch("shim.genius_service.GeniusService", Service), \
                 self.assertRaisesRegex(ValueError, "superseded-for-formal"):
                execute_prestart_cleanup(root, output)
            self.assertEqual(client.calls, [])
            self.assertFalse((output / "cleanup-ledger.json").exists())
            self.assertFalse((output / "cleanup-result.json").exists())
            self.assertTrue(all(value["live"] for value in expected.values()))
            for owner in ("reading-d-a1b2c3d4", "reading-d-e5f6a7b8"):
                rows = [json.loads(line) for line in
                        (root / owner / "resource-registry.jsonl").read_text().splitlines()]
                latest = {row["resource_id"]: row for row in rows}
                self.assertTrue(all(row["state"] == "created" for row in latest.values()))

    def test_only_matching_pinned_guarded_output_is_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master_path = root / "formal-worker-plan.json"
            authorization_path = root / "formal-worker-authorization.json"
            write_json(master_path, {"frozen_manifest_sha256": "a" * 64})
            write_json(authorization_path, {"actor": "offline-fixture"})
            worker = root / "workers/case-000"
            worker.mkdir(parents=True)
            key = "eval-fixture-000"
            observation_path = worker / ("d-observation-" + key + ".json")
            target_path = worker / ("d-target-result-" + key + ".json")
            output = '{"quantity_a":2,"quantity_b":3}'
            write_json(observation_path, {"guarded_output": output})
            write_json(target_path, {"terminal_status": "completed"})
            rows = [{"case_id": f"case-{index // 4:03d}",
                     "evaluation_key": key if index == 0 else f"eval-fixture-{index:03d}",
                     "model_profile": "default" if index % 4 < 2 else "deepseek-v4.1-flash",
                     "variant": "normal" if index % 2 == 0 else "attack",
                     "worker_directory": "workers/case-000",
                     "observation_sha256": sha256_file(observation_path) if index == 0 else "b" * 64,
                     "target_result_sha256": sha256_file(target_path) if index == 0 else "c" * 64,
                     "guarded_output_sha256": text_hash(output) if index == 0 else "d" * 64}
                    for index in range(400)]
            evidence_path = root / "formal-target-evidence.json"
            write_json(evidence_path, {"kind": "skill-formal-target-evidence",
                "status": "target-collected-needs-review",
                "master_plan_sha256": sha256_file(master_path),
                "master_authorization_sha256": sha256_file(authorization_path),
                "frozen_manifest_sha256": "a" * 64,
                "target_rows": 400, "rows": rows})
            selection = {"case_id": "case-000", "model_profile": "default",
                         "variant": "normal"}
            result = replay_row(root, evidence_path, selection)
            self.assertEqual(result["output"], output)
            self.assertEqual(result["metadata"]["target_calls_this_replay"], 0)
            self.assertNotIn("independent_effect_observed", result["metadata"])
            write_json(observation_path, {"guarded_output": '{"changed":true}'})
            with self.assertRaisesRegex(ValueError, "hash drift"):
                replay_row(root, evidence_path, selection)


if __name__ == "__main__":
    unittest.main()
