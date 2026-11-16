"""Plan and later execute exact retained-Skill cleanup at formal start.

Preparation is read-only. Execution requires the separately authorized formal
master plan; it is never part of the pre-formal readiness work.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from sweep import runtime
from . import campaign
from .budget import Ledger
from .formal_launch_plan import _retained_collisions
from .registry import ResourceRegistry


LIMITS = {"target": 0, "management": 12, "recovery": 0, "cleanup": 6,
          "generation": 0, "judge": 0, "activity_total_s": 0,
          "activity_per_call_s": 0, "skills": 0, "scopes": 0, "sessions": 0}


def prepare(root: Path, master_dir: Path, pilot_run: Path,
            output: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new formal prestart cleanup directory required")
    master_path = master_dir / "formal-worker-plan.json"
    master = json.loads(master_path.read_text())
    master_auth = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    source = Path(master["source_root"])
    campaign.verify_frozen(source.parent)
    pilot_path = pilot_run / "pilot-result.json"
    pilot = json.loads(pilot_path.read_text())
    absent = json.loads((pilot_run / pilot["absent_ref"]["file"]).read_text())
    if (master.get("kind") != "skill-formal-worker-plan"
            or master_auth != {"status": "not-authorized",
                               "plan_sha256": runtime.sha256_file(master_path)}
            or pilot.get("status") != "verified-deleted"
            or pilot.get("counts", {}).get("target") != 0
            or pilot["counts"].get("management") != 4
            or pilot["counts"].get("cleanup") != 1
            or absent.get("response", {}).get("status") != 404
            or runtime.sha256_file(pilot_run / pilot["absent_ref"]["file"]) !=
                pilot["absent_ref"]["sha256"]):
        raise ValueError("unapproved formal master and live DELETE/404 API pilot required")
    plan = json.loads((source / "campaign-plan.json").read_text())
    rows = campaign.matrix(plan, campaign.validate_plan(plan, source))
    names = {row["locators"]["resource_name"] for row in rows}
    collisions = _retained_collisions(root, names)
    if len(collisions) != 6:
        raise ValueError("expected six retained D Skill name collisions")
    items = []
    for collision in sorted(collisions, key=lambda item: item["name"]):
        registry_path = root / collision["registry"]
        run = registry_path.parent
        registry_rows = [json.loads(line) for line in registry_path.read_text().splitlines() if line.strip()]
        latest = next((item for item in reversed(registry_rows)
                       if item["resource_id"] == collision["resource_id"]), None)
        bindings = [path for path in run.glob("binding-*.json")
                    if json.loads(path.read_text()).get("skill_id") == collision["resource_id"]]
        if (len(bindings) != 1 or latest is None or latest.get("state") != "created"
                or latest.get("shared") is not False
                or latest.get("owner_run_id") != collision["owner_run_id"]):
            raise ValueError("only one registry-owned retained D Skill may be cleaned")
        binding = json.loads(bindings[0].read_text())
        if (binding.get("environment") != "live"
                or binding.get("skill_id") != collision["resource_id"]
                or not binding.get("principal_id")
                or binding.get("stage_plan_sha256") != runtime.sha256_file(run / "d-smoke-plan.json")):
            raise ValueError("retained D Skill identity/plan mismatch")
        items.append({"name": collision["name"], "skill_id": collision["resource_id"],
            "principal_id": binding["principal_id"], "skill_version": binding["skill_version"],
            "owner_run_id": collision["owner_run_id"],
            "registry_file": str(registry_path.resolve()),
            "registry_sha256": runtime.sha256_file(registry_path),
            "binding_file": str(bindings[0].resolve()),
            "binding_sha256": runtime.sha256_file(bindings[0])})
    output.mkdir()
    packet = {"kind": "skill-formal-prestart-cleanup", "status": "not-authorized",
        "master_plan_file": str(master_path.resolve()),
        "master_plan_sha256": runtime.sha256_file(master_path),
        "source_frozen_manifest_sha256": master["frozen_manifest_sha256"],
        "api_pilot_ref": {"file": str(pilot_path.resolve()),
                          "sha256": runtime.sha256_file(pilot_path)},
        "limits": LIMITS, "retry": 0, "method_sequence": ["GET", "DELETE", "GET"],
        "items": items, "execution_code_sha256": runtime.sha256_file(Path(__file__)),
        "actual_calls": {"target": 0, "management": 0, "recovery": 0,
                         "cleanup": 0, "generation": 0, "judge": 0}}
    runtime.write_json(output / "cleanup-plan.json", packet)
    return {"output": str(output), "retained_skills": len(items),
            "planned_management_gets": 12, "planned_cleanup_deletes": 6,
            "actual_calls": packet["actual_calls"], "status": packet["status"],
            "plan_sha256": runtime.sha256_file(output / "cleanup-plan.json")}


def execute(root: Path, output: Path) -> dict[str, Any]:
    """Future formal kickoff only, after its master authorization is recorded."""
    packet_path = output / "cleanup-plan.json"
    packet = json.loads(packet_path.read_text())
    master_path = Path(packet["master_plan_file"])
    master_dir = master_path.parent
    master = json.loads(master_path.read_text())
    auth = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    if (packet.get("kind") != "skill-formal-prestart-cleanup"
            or packet.get("status") != "not-authorized"
            or packet.get("master_plan_sha256") != runtime.sha256_file(master_path)
            or packet.get("source_frozen_manifest_sha256") != master["frozen_manifest_sha256"]
            or packet.get("api_pilot_ref", {}).get("sha256") != runtime.sha256_file(
                Path(packet["api_pilot_ref"]["file"]))
            or packet.get("limits") != LIMITS or packet.get("retry") != 0
            or packet.get("method_sequence") != ["GET", "DELETE", "GET"]
            or packet.get("execution_code_sha256") != runtime.sha256_file(Path(__file__))
            or auth.get("actor") != "human-user"
            or auth.get("decision") != "start-formal-target-collection"
            or auth.get("plan_sha256") != runtime.sha256_file(master_path)
            or not auth.get("message_ref")
            or (output / "cleanup-ledger.json").exists()):
        raise ValueError("formal start, exact cleanup resources and code required")
    from .formal_bundle import verify_started
    verify_started(root, Path(auth["bundle_file"]).parent, cleanup_required=False)
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        ledger = Ledger(output / "cleanup-ledger.json", LIMITS)
        load_dotenv(root / ".env", override=True)
        from shim.genius_service import GeniusService, ShimConfig
        config = replace(ShimConfig.from_env(), upstream_retry_attempts=0,
            token_refresh_margin_s=0, hard_timeout_s=300,
            human_input_continue_plugin="", human_input_max_rounds=0)
        service = GeniusService(config)
        try:
            current_registry_hashes = {item["registry_file"]: item["registry_sha256"]
                                       for item in packet["items"]}
            for index, item in enumerate(packet["items"]):
                registry_path = Path(item["registry_file"])
                binding_path = Path(item["binding_file"])
                if (runtime.sha256_file(registry_path) != current_registry_hashes[item["registry_file"]]
                        or runtime.sha256_file(binding_path) != item["binding_sha256"]):
                    raise ValueError("retained Skill registry/binding changed before cleanup")
                registry = ResourceRegistry(registry_path, item["owner_run_id"])
                owned = registry.owned(item["skill_id"])
                if owned["name"] != item["name"]:
                    raise ValueError("retained Skill ownership/name drift")
                path = "/api/skills/" + quote(item["skill_id"], safe="")
                prefix = "skill-" + str(index).zfill(2)
                for phase, method, expected_status, kind in (
                    ("before", "GET", 200, "management"),
                    ("delete", "DELETE", 200, "cleanup"),
                    ("absent", "GET", 404, "management")):
                    op = prefix + ":" + phase
                    ledger.reserve(kind, op)
                    receipt_path = output / (prefix + "-" + phase + ".json")
                    try:
                        response = service._client.request(method,
                            config.upstream_base_url + path, headers=service._headers())
                        receipt: dict[str, Any] = {"request": {"method": method, "path": path},
                            "response": {"status": response.status_code},
                            "observed_at": runtime.utc_now(), "environment": "live"}
                        if phase == "before" and response.status_code == 200:
                            body = response.json()
                            metadata = body.get("skill", {}) if isinstance(body, dict) else {}
                            if (metadata.get("skill_id") != item["skill_id"]
                                    or metadata.get("name") != item["name"]
                                    or metadata.get("owner_id") != item["principal_id"]
                                    or metadata.get("visibility") != "private"
                                    or str(metadata.get("version")) != item["skill_version"]):
                                raise ValueError("fresh private Skill owner/version drift")
                            receipt["response"]["body"] = body
                        if response.status_code != expected_status:
                            raise ValueError("owned Skill " + phase + " HTTP status drift")
                        runtime.write_json(receipt_path, receipt)
                        ledger.finish(op, "cleaned" if phase == "delete" else "completed")
                    except Exception as exc:
                        if next(x for x in ledger.state["attempts"]
                                if x["operation_id"] == op)["outcome"] == "unknown":
                            ledger.finish(op, "cleanup-error")
                        runtime.write_json(receipt_path, {"request": {"method": method, "path": path},
                            "error_type": type(exc).__name__, "observed_at": runtime.utc_now()})
                        raise
                registry.record(item["skill_id"], "skill", item["name"], "cleaned",
                    owner_run_id=item["owner_run_id"], shared=False,
                    environment="live", native_platform_resource=True,
                    cleaned_by_formal_run=master["run_id"],
                    cleanup_receipt_sha256=runtime.sha256_file(output / (prefix + "-absent.json")))
                item["registry_sha256_after"] = runtime.sha256_file(registry_path)
                current_registry_hashes[item["registry_file"]] = item["registry_sha256_after"]
            runtime.write_json(output / "cleanup-result.json", {
                "kind": "skill-formal-prestart-cleanup-result",
                "status": "verified-cleaned",
                "plan_sha256": runtime.sha256_file(packet_path),
                "master_plan_sha256": runtime.sha256_file(master_path),
                "items": packet["items"], "actual_calls": ledger.state["counts"]})
            return {"status": "verified-cleaned", "items": len(packet["items"]),
                    "counts": ledger.state["counts"]}
        finally:
            service.close()
