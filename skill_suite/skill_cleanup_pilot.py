"""Bounded create/read/delete proof for a run-owned private Skill."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from sweep import runtime
from .budget import Ledger
from .http_accounting import meter_client
from .observed_api import ObservedGeneralControl
from .registry import ResourceRegistry


LIMITS = {"target": 0, "management": 4, "recovery": 0, "cleanup": 1,
          "generation": 0, "judge": 0, "activity_total_s": 0,
          "activity_per_call_s": 0, "skills": 1, "scopes": 0, "sessions": 0}


def prepare(root: Path, output: Path, principal_id: str, source_skill: Path,
            message_ref: str) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir() or not message_ref:
        raise ValueError("new cleanup pilot with a direct user authorization reference required")
    nonce = secrets.token_hex(8)
    output.mkdir()
    plan = {"kind": "skill-private-delete-pilot", "phase": "preformal-cleanup-pilot",
        "run_id": "reading-cleanup-" + nonce,
        "resource_name": "research-notes-" + nonce,
        "principal_id": principal_id, "source_skill_file": str(source_skill.resolve()),
        "source_skill_sha256": runtime.sha256_file(source_skill),
        "limits": LIMITS, "retry": 0, "projects": 0,
        "code_sha256": runtime.sha256_file(Path(__file__)),
        "observed_api_sha256": runtime.sha256_file(Path(__file__).with_name("observed_api.py")),
        "authorization": {"actor": "human-user", "decision": "start-bounded-cleanup-pilot",
                          "message_ref": message_ref, "confirmed_at": runtime.utc_now()}}
    runtime.write_json(output / "pilot-plan.json", plan)
    return {"run_id": plan["run_id"], "output": str(output),
            "plan_sha256": runtime.sha256_file(output / "pilot-plan.json"),
            "max_management": 4, "max_cleanup": 1, "target_calls": 0}


def execute(root: Path, run: Path) -> dict[str, Any]:
    plan = json.loads((run / "pilot-plan.json").read_text())
    auth = plan.get("authorization") or {}
    source = Path(plan.get("source_skill_file", ""))
    if (not run.resolve().is_relative_to((root / "skill-suites/skill-task-scope-write/runs").resolve())
            or plan.get("kind") != "skill-private-delete-pilot"
            or plan.get("phase") != "preformal-cleanup-pilot"
            or plan.get("limits") != LIMITS or plan.get("retry") != 0
            or plan.get("projects") != 0
            or plan.get("code_sha256") != runtime.sha256_file(Path(__file__))
            or plan.get("observed_api_sha256") != runtime.sha256_file(Path(__file__).with_name("observed_api.py"))
            or not source.is_file() or plan.get("source_skill_sha256") != runtime.sha256_file(source)
            or auth.get("actor") != "human-user"
            or auth.get("decision") != "start-bounded-cleanup-pilot"
            or not auth.get("message_ref") or not auth.get("confirmed_at")
            or (run / "call-ledger.json").exists()):
        raise ValueError("bounded authorized Skill cleanup pilot drift")
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        ledger = Ledger(run / "call-ledger.json", LIMITS)
        registry = ResourceRegistry(run / "resource-registry.jsonl", plan["run_id"])
        load_dotenv(root / ".env", override=True)
        from shim.genius_service import GeniusService, ShimConfig
        config = replace(ShimConfig.from_env(), upstream_retry_attempts=0,
                         token_refresh_margin_s=0, hard_timeout_s=300,
                         human_input_continue_plugin="", human_input_max_rounds=0)
        service = GeniusService(config)
        def request(name: str, method: str, path: str,
                    body: dict[str, Any] | None = None) -> dict[str, Any]:
            destination = run / (name + ".json")
            if destination.exists():
                raise ValueError("zero retry: cleanup pilot receipt already exists")
            receipt: dict[str, Any] = {"request": {"method": method, "path": path},
                "response": None, "environment": "live", "observed_at": runtime.utc_now()}
            if body is not None:
                receipt["request"]["body"] = body
            records: list[dict[str, Any]] = []
            try:
                with meter_client(service._client, ledger, "pilot:" + name) as records:
                    value = service._request_json(method, path, json_body=body)
                if len(records) != 1 or records[0]["outcome"] != "completed":
                    raise ValueError("exactly one successful pilot management HTTP attempt required")
                receipt["response"] = {"status": records[0]["status_code"], "body": value}
                return value
            except Exception as exc:
                receipt["error"] = type(exc).__name__
                ledger.stop("pilot-management-error:" + type(exc).__name__)
                raise
            finally:
                receipt["http_attempts"] = records
                runtime.write_json(destination, receipt)
        try:
            adapter = ObservedGeneralControl(request, plan["principal_id"], "pilot")
            created = adapter.create_skill(plan["resource_name"], source.read_text())
            registry.record(created["skill_id"], "skill", plan["resource_name"], "created",
                            owner_run_id=plan["run_id"], shared=False,
                            environment="live", native_platform_resource=True)
            adapter.read_skill(created["skill_id"])
            skill_path = "/api/skills/" + quote(created["skill_id"], safe="")
            delete_path = run / "pilot-delete-skill.json"
            ledger.reserve("cleanup", "pilot:delete-skill")
            deleted = None
            try:
                response = service._client.request("DELETE",
                    config.upstream_base_url + skill_path, headers=service._headers())
                deleted = {"request": {"method": "DELETE", "path": skill_path},
                           "response": {"status": response.status_code},
                           "observed_at": runtime.utc_now(), "environment": "live"}
                if response.status_code < 200 or response.status_code >= 300:
                    raise ValueError("owned private Skill DELETE not accepted")
                ledger.finish("pilot:delete-skill", "cleaned")
            except Exception:
                if next(x for x in ledger.state["attempts"]
                        if x["operation_id"] == "pilot:delete-skill")["outcome"] == "unknown":
                    ledger.finish("pilot:delete-skill", "cleanup-error")
                raise
            finally:
                runtime.write_json(delete_path, deleted or {"status": "unknown"})
            # A single expected 404 is an independent post-delete state check.
            ledger.reserve("management", "pilot:verify-absent")
            absent_path = run / "pilot-verify-absent.json"
            verified = False
            try:
                response = service._client.request("GET", config.upstream_base_url + skill_path,
                                                   headers=service._headers())
                verified = response.status_code == 404
                runtime.write_json(absent_path, {"request": {"method": "GET", "path": skill_path},
                    "response": {"status": response.status_code},
                    "observed_at": runtime.utc_now(), "environment": "live"})
                ledger.finish("pilot:verify-absent", "completed" if verified else "not-absent")
                if not verified:
                    raise ValueError("Skill GET did not confirm deletion")
            except Exception:
                if next(x for x in ledger.state["attempts"]
                        if x["operation_id"] == "pilot:verify-absent")["outcome"] == "unknown":
                    ledger.finish("pilot:verify-absent", "transport-error")
                raise
            registry.record(created["skill_id"], "skill", plan["resource_name"], "cleaned",
                            owner_run_id=plan["run_id"], shared=False,
                            environment="live", native_platform_resource=True)
            report = {"kind": "skill-private-delete-pilot-result", "status": "verified-deleted",
                      "run_id": plan["run_id"], "plan_sha256": runtime.sha256_file(run / "pilot-plan.json"),
                      "skill_id": created["skill_id"], "resource_name": plan["resource_name"],
                      "counts": ledger.state["counts"],
                      "delete_ref": {"file": delete_path.name,
                                     "sha256": runtime.sha256_file(delete_path)},
                      "absent_ref": {"file": absent_path.name,
                                     "sha256": runtime.sha256_file(absent_path)},
                      "genius_target_calls": 0, "judge_calls": 0}
            runtime.write_json(run / "pilot-result.json", report)
            return {"status": report["status"], "counts": report["counts"],
                    "genius_target_calls": 0, "judge_calls": 0}
        finally:
            service.close()
