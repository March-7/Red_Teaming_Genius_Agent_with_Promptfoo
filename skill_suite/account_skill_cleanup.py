"""Delete only private Genius Skills proven to be owned by this project."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from sweep import runtime
from .package_gate_runtime import PackageGateLedger


LIMIT_KEYS = {"target", "management", "recovery", "cleanup",
              "generation", "judge", "retry"}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _receipt_body(path: Path) -> dict[str, Any]:
    value = _json(path)
    body = value.get("response", {}).get("body")
    if not isinstance(body, dict):
        raise ValueError("catalogue receipt body missing")
    return body


def _safe_response_body(response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def _local_skills(root: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in root.joinpath("skill-suites").rglob("resource-registry.jsonl"):
        if "precleanup-snapshots" in path.parts:
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            resource_id = row.get("resource_id")
            if (row.get("kind") == "skill" and isinstance(resource_id, str)
                    and resource_id.startswith("skill-")):
                latest[resource_id] = {**row, "registry_file": str(path.resolve())}
    return latest


def validate_plan(root: Path, run: Path) -> dict[str, Any]:
    plan = _json(run / "cleanup-plan.json")
    auth = _json(run / "authorization.json")
    required = {"schema_version", "kind", "run_id", "status", "authorization_ref",
        "catalogue_refs", "catalogue_total", "items", "excluded_skill_ids",
        "discovery_calls", "execution_limits", "retry", "code_sha256",
        "target_calls", "generation_calls", "judge_calls"}
    if (set(plan) != required or plan["schema_version"] != 1
            or plan["kind"] != "genius-project-owned-skill-cleanup-plan"
            or plan["run_id"] != run.name or plan["status"] != "authorized"
            or plan["retry"] != 0 or plan["target_calls"] != 0
            or plan["generation_calls"] != 0 or plan["judge_calls"] != 0
            or set(plan["execution_limits"]) != LIMIT_KEYS
            or plan["execution_limits"]["cleanup"] != len(plan["items"])
            or plan["execution_limits"]["management"] != (
                len(plan["items"]) + plan["execution_limits"]["recovery"])
            or plan["code_sha256"] != runtime.sha256_file(Path(__file__))):
        raise ValueError("account Skill cleanup plan boundary drift")
    if (auth != {"status": "active", "actor": "human-user",
            "decision": "delete-project-owned-genius-skills",
            "message_ref": "user-message:2026-10-08-clean-previous-uploaded-genius-skills",
            "scope": "registry-owned-private-skills-only", "retry": 0}
            or plan["authorization_ref"] != {"file": "authorization.json",
                "sha256": runtime.sha256_file(run / "authorization.json")}):
        raise ValueError("fresh human cleanup authorization required")
    catalogue: dict[str, dict[str, Any]] = {}
    for ref in plan["catalogue_refs"]:
        path = run / ref["file"]
        if runtime.sha256_file(path) != ref["sha256"]:
            raise ValueError("catalogue receipt drift")
        body = _receipt_body(path)
        if body.get("total") != plan["catalogue_total"]:
            raise ValueError("catalogue total drift")
        for skill in body.get("skills", []):
            catalogue[skill["skill_id"]] = skill
    if len(catalogue) != plan["catalogue_total"]:
        raise ValueError("complete paginated catalogue required")
    local = _local_skills(root)
    item_ids = set()
    for item in plan["items"]:
        required_item = {"skill_id", "name", "owner_id", "owner_run_id",
                         "registry_file", "registry_state", "mode", "version"}
        if set(item) != required_item or item["skill_id"] in item_ids:
            raise ValueError("cleanup item invalid")
        item_ids.add(item["skill_id"])
        actual, registered = catalogue.get(item["skill_id"]), local.get(item["skill_id"])
        if (actual is None or registered is None or actual.get("name") != item["name"]
                or registered.get("name") != item["name"]
                or registered.get("owner_run_id") != item["owner_run_id"]
                or registered.get("registry_file") != item["registry_file"]
                or registered.get("state") != item["registry_state"]
                or actual.get("owner_id") != item["owner_id"]
                or actual.get("source") != "user" or actual.get("visibility") != "private"
                or actual.get("sharing_scope") != "private"
                or actual.get("shared_with_count") != 0
                or actual.get("can_manage") is not True or actual.get("mode") != item["mode"]
                or actual.get("version") != item["version"]):
            raise ValueError("cleanup item owner/private/name/version drift")
    actual_owned = {skill_id for skill_id, skill in catalogue.items()
        if skill.get("source") == "user" and skill.get("visibility") == "private"
        and skill.get("can_manage") is True}
    if item_ids != actual_owned & set(local):
        raise ValueError("cleanup plan is not the exact registry-owned catalogue intersection")
    if set(plan["excluded_skill_ids"]) != actual_owned - item_ids:
        raise ValueError("unowned account Skills must be explicitly excluded")
    return plan


def execute(root: Path, run: Path) -> dict[str, Any]:
    plan = validate_plan(root, run)
    result_path = run / "cleanup-result.json"
    if result_path.exists():
        raise ValueError("account Skill cleanup already completed")
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        ledger = PackageGateLedger(run / "cleanup-ledger.json", plan["execution_limits"])
        load_dotenv(root / ".env", override=True)
        from shim.genius_service import GeniusService, ShimConfig
        config = replace(ShimConfig.from_env(), upstream_retry_attempts=0,
            token_refresh_margin_s=0, hard_timeout_s=60,
            human_input_continue_plugin="", human_input_max_rounds=0)
        if not config.upstream_base_url or not config.upstream_authorization:
            raise ValueError("Genius credential/base URL unavailable")
        service = GeniusService(config)
        completed = []
        try:
            for index, item in enumerate(plan["items"]):
                prefix = f"skill-{index:03d}"
                delete_path = run / f"{prefix}-delete.json"
                absent_path = run / f"{prefix}-absent.json"
                api_path = "/api/skills/" + quote(item["skill_id"], safe="")
                if absent_path.exists():
                    absent = _json(absent_path)
                    if absent.get("response", {}).get("status") != 404:
                        raise ValueError("existing absence receipt drift")
                    completed.append(item["skill_id"])
                    continue
                if not delete_path.exists():
                    operation = prefix + ":delete"
                    ledger.reserve("cleanup", operation)
                    response = service._client.delete(
                        config.upstream_base_url.rstrip("/") + api_path,
                        headers=service._headers())
                    body = _safe_response_body(response)
                    runtime.write_json(delete_path, {"request": {"method": "DELETE", "path": api_path},
                        "response": {"status": response.status_code, "bytes": len(response.content),
                            "sha256": hashlib.sha256(response.content).hexdigest(), "body": body},
                        "observed_at": runtime.utc_now()})
                    if (response.status_code != 200 or not isinstance(body, dict)
                            or body.get("status") != "deleted"
                            or body.get("skill_id") != item["skill_id"]):
                        ledger.finish(operation, "cleanup-error")
                        raise ValueError("owned Skill delete response drift")
                    ledger.finish(operation, "cleaned")
                operation = prefix + ":absent"
                existing = next((row for row in ledger.state["attempts"]
                    if row["operation_id"] == operation), None)
                if existing is not None and existing["outcome"] == "unknown":
                    ledger.finish(operation, "local-response-parse-error")
                    operation = prefix + ":absent-recovery"
                    ledger.reserve("recovery", operation)
                elif existing is None:
                    ledger.reserve("management", operation)
                else:
                    raise ValueError("absence operation already finished without a receipt")
                response = service._client.get(
                    config.upstream_base_url.rstrip("/") + api_path,
                    headers=service._headers())
                body = _safe_response_body(response)
                runtime.write_json(absent_path, {"request": {"method": "GET", "path": api_path},
                    "response": {"status": response.status_code, "bytes": len(response.content),
                        "sha256": hashlib.sha256(response.content).hexdigest(), "body": body},
                    "observed_at": runtime.utc_now()})
                if response.status_code != 404:
                    ledger.finish(operation, "absence-error")
                    raise ValueError("deleted Skill did not read back 404")
                ledger.finish(operation, "completed")
                completed.append(item["skill_id"])
                runtime.write_json(run / "cleanup-progress.json", {"completed": completed,
                    "remaining": len(plan["items"]) - len(completed),
                    "counts": ledger.state["counts"]})
            result = {"schema_version": 1,
                "kind": "genius-project-owned-skill-cleanup-result",
                "status": "verified-cleaned", "run_id": run.name,
                "planned_skills": len(plan["items"]),
                "deleted_skills": len(completed), "verified_404": len(completed),
                "excluded_unowned_skills": len(plan["excluded_skill_ids"]),
                "execution_calls": ledger.state["counts"],
                "discovery_calls": plan["discovery_calls"],
                "target_calls": 0, "generation_calls": 0, "judge_calls": 0,
                "retry_calls": 0, "pending_compute_ownership": 0}
            runtime.write_json(result_path, result)
            return result
        finally:
            service.close()


def validate_summary(root: Path, summary_path: Path) -> dict[str, Any]:
    summary = _json(summary_path)
    required = {"schema_version", "kind", "status", "run_id", "authorization_ref",
        "plan_ref", "result_ref", "final_audit_ref", "catalogue_before",
        "catalogue_after", "project_owned_planned", "project_owned_deleted",
        "verified_404", "project_owned_remaining", "unowned_private_skills_preserved",
        "calls", "sessions_deleted", "projects_deleted", "artifacts_deleted",
        "pending_compute_ownership"}
    if (set(summary) != required or summary["schema_version"] != 1
            or summary["kind"] != "genius-project-owned-skill-cleanup-summary"
            or summary["status"] != "verified-project-skill-set-empty"
            or summary["catalogue_before"] != 275 or summary["catalogue_after"] != 142
            or summary["project_owned_planned"] != 133
            or summary["project_owned_deleted"] != 133 or summary["verified_404"] != 133
            or summary["project_owned_remaining"] != 0
            or summary["unowned_private_skills_preserved"] != 21
            or summary["calls"] != {"management": 142, "recovery": 1,
                "cleanup": 133, "target": 0, "generation": 0, "judge": 0, "retry": 0}
            or any(summary[key] != 0 for key in ("sessions_deleted", "projects_deleted",
                                                  "artifacts_deleted", "pending_compute_ownership"))):
        raise ValueError("account Skill cleanup summary boundary drift")
    refs = {}
    for key in ("authorization_ref", "plan_ref", "result_ref", "final_audit_ref"):
        ref = summary[key]
        if set(ref) != {"file", "sha256"}:
            raise ValueError("cleanup summary ref invalid")
        path = (root / ref["file"]).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or runtime.sha256_file(path) != ref["sha256"]):
            raise ValueError("cleanup summary evidence drift")
        refs[key] = _json(path)
    result, audit = refs["result_ref"], refs["final_audit_ref"]
    if (result.get("status") != "verified-cleaned" or result.get("deleted_skills") != 133
            or result.get("verified_404") != 133
            or audit.get("status") != "verified-project-skill-set-empty"
            or audit.get("remaining_project_owned_count") != 0
            or audit.get("excluded_unowned_still_present") != 21):
        raise ValueError("cleanup result or final audit drift")
    return {"valid": True, "deleted_skills": 133, "verified_404": 133,
        "remaining_project_owned": 0, "unowned_preserved": 21,
        "target_calls": 0, "generation_calls": 0, "judge_calls": 0}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "execute", "validate-summary"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    root, run = args.root.resolve(), args.run.resolve()
    result = (validate_plan(root, run) if args.command == "validate"
              else validate_summary(root, run) if args.command == "validate-summary"
              else execute(root, run))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
