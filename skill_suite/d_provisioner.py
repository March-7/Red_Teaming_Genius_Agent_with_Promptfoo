"""Metered on-demand private Skill and general session provisioner for D.

Construction requires a phase-bound stage authorization and active project
lease. Fixture injection tests the exact observed HTTP path without egress;
live construction loads credentials only after every local gate succeeds.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from sweep import runtime
from . import campaign
from .budget import Ledger
from .d_binding import case_request, validate_binding
from .d_smoke_plan import CODE_FILES, CODE_ROOT, LIMITS, MIN_SKILL_AGE_SECONDS
from .http_accounting import meter_client
from .observed_api import ObservedGeneralControl
from .registry import ResourceRegistry


class DProvisioner:
    def __init__(self, root: Path, run: Path, source: Path, lease: runtime.RunLease,
                 *, fixture_service: Any = None):
        lease.require_active()
        if lease.root != root.resolve():
            raise ValueError("D provisioner requires this project's active lock")
        self.root, self.run, self.source, self.lease = root, run, source, lease
        self.environment = "offline-fixture" if fixture_service is not None else "live"
        if self.environment == "live" and not run.resolve().is_relative_to(
                (root / "skill-suites/skill-task-scope-write/runs").resolve()):
            raise ValueError("live D run must be in ignored suite runs")
        self.stage_path = run / "d-smoke-plan.json"
        self.stage = json.loads(self.stage_path.read_text())
        authorization = json.loads((run / "d-smoke-authorization.json").read_text())
        actor = "offline-fixture" if fixture_service is not None else "human-user"
        if (self.stage.get("kind") != "skill-generated-smoke-plan"
                or self.stage.get("phase") != "D"
                or self.stage.get("source_origin") != ("offline-fixture" if fixture_service is not None else "provider-response")
                or self.stage.get("limits") != LIMITS or self.stage.get("retry") != 0
                or self.stage.get("min_skill_age_seconds") != MIN_SKILL_AGE_SECONDS
                or self.stage.get("policy_sha256") != runtime.sha256_file(run / "approval-policy.json")
                or self.stage.get("guard_sha256") != runtime.sha256_file(runtime.GUARD_PATH)
                or self.stage.get("code_hashes") !=
                   {name: runtime.sha256_file(CODE_ROOT / name) for name in CODE_FILES}
                or authorization.get("actor") != actor or authorization.get("decision") != "start"
                or authorization.get("phase") != "D" or authorization.get("run_id") != self.stage.get("run_id")
                or authorization.get("plan_sha256") != runtime.sha256_file(self.stage_path)
                or not authorization.get("message_ref") or not authorization.get("confirmed_at")):
            raise ValueError("fresh approved D stage, fixed budget and policy required")
        self.plan = json.loads((source / "campaign-plan.json").read_text())
        self.cases = campaign.validate_plan(self.plan, source)
        self.rows = campaign.matrix(self.plan, self.cases)
        campaign.validate_matrix(self.plan, self.cases, self.rows)
        if (self.stage["source_plan_file_sha256"] != runtime.sha256_file(source / "campaign-plan.json")
                or self.stage["campaign_id"] != self.plan["campaign_id"]
                or self.stage["target_context"] != "global-general"
                or self.stage["session_type"] != "general"):
            raise ValueError("D campaign source or target route drift")
        if self.environment == "live":
            if (source.name != "source" or
                    self.stage.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")):
                raise ValueError("reviewed frozen C source required before live D")
            campaign.verify_frozen(source.parent)
        self.selected = {row["evaluation_key"]: row for row in self.rows
                         if row["case_id"] == self.stage["case_id"]}
        if len(self.selected) != 4 or set(self.selected) != {item["evaluation_key"] for item in self.stage["rows"]}:
            raise ValueError("four fixed D rows required")
        self.ledger = Ledger(run / "call-ledger.json", LIMITS)
        if self.ledger.state["stopped"]:
            raise ValueError("stopped D ledger requires review or read-only recovery")
        self.registry = ResourceRegistry(run / "resource-registry.jsonl", self.stage["run_id"])
        # Only now may a live construction read the local credential.
        if fixture_service is None:
            runtime.require_free_shim_port()
            from dotenv import load_dotenv
            from shim.genius_service import GeniusService, ShimConfig
            load_dotenv(root / ".env", override=True)
            config = replace(ShimConfig.from_env(), upstream_retry_attempts=0,
                token_refresh_margin_s=0, hard_timeout_s=300,
                human_input_continue_plugin="", human_input_max_rounds=0,
                approval_policy_file=str(run / "approval-policy.json"),
                trace_jsonl_path=str(run / "genius_trace.jsonl"),
                lifecycle_jsonl_path=str(run / "session_lifecycle.jsonl"),
                trace_raw_events=True)
            self.service = GeniusService(config)
            self._owns_service = True
        else:
            self.service = fixture_service
            self._owns_service = False
        self.receipts: dict[str, dict[str, str]] = {}
        self._current_row: dict[str, Any] | None = None

    def close(self) -> None:
        if self._owns_service:
            self.service.close()

    def request(self, name: str, method: str, path: str,
                body: dict[str, Any] | None = None, *,
                accounting_kind: str = "management") -> dict[str, Any]:
        self.lease.require_active()
        from .schema import identifier
        identifier(name, "D HTTP receipt name")
        if accounting_kind not in {"management", "recovery", "cleanup"} or (
                accounting_kind == "recovery" and method != "GET") or (
                accounting_kind == "cleanup" and method != "DELETE"):
            raise ValueError("D management/recovery/cleanup method mismatch")
        destination = self.run / (name + ".json")
        if destination.exists():
            raise ValueError("zero retry: D HTTP receipt already exists")
        receipt: dict[str, Any] = {"request": {"method": method, "path": path},
            "response": None, "environment": self.environment,
            "observed_at": runtime.utc_now()}
        if body is not None:
            receipt["request"]["body"] = body
        runtime.write_json(destination, receipt)
        records: list[dict[str, Any]] = []
        try:
            with meter_client(self.service._client, self.ledger, "d:" + name,
                              management_kind=accounting_kind) as records:
                response = self.service._request_json(method, path, json_body=body)
            if len(records) != 1 or records[0]["outcome"] != "completed":
                raise ValueError("exactly one successful observed HTTP attempt required")
            receipt["response"] = {"status": records[0]["status_code"], "body": response}
            row = self._current_row
            if row is not None and method == "POST" and path in {"/api/sessions", "/api/skills"}:
                kind = "session" if path == "/api/sessions" else "skill"
                resource_id = response.get("session_id") if kind == "session" else response.get("skill_id")
                if isinstance(resource_id, str) and resource_id:
                    if any(item["resource_id"] == resource_id and
                           item.get("evaluation_key") != row["evaluation_key"]
                           for item in self.registry.rows):
                        raise ValueError("created resource identity collides with another D row")
                    resource_name = ("research-session-" + row["evaluation_key"][:16]
                                     if kind == "session" else body["name"])
                    self.registry.record(resource_id, kind, resource_name, "created-unverified",
                        owner_run_id=self.stage["run_id"], shared=True,
                        environment=self.environment, evaluation_key=row["evaluation_key"],
                        native_platform_resource=True)
            return response
        except Exception as exc:
            self.ledger.stop("D-management-error:" + type(exc).__name__)
            receipt["error"] = type(exc).__name__
            raise
        finally:
            receipt["http_attempts"] = records
            runtime.write_json(destination, receipt)
            self.receipts[name] = {"file": destination.name,
                                   "sha256": runtime.sha256_file(destination)}

    def provision_one(self, evaluation_key: str) -> dict[str, Any]:
        self.lease.require_active()
        row = self.selected.get(evaluation_key)
        if row is None:
            raise ValueError("D provisioner row is not in the frozen four")
        if (self.run / ("binding-" + evaluation_key + ".json")).exists():
            raise ValueError("D case already provisioned; no repeated creation")
        if len({item["resource_id"] for item in self.registry.rows
                if item["kind"] == "skill" and item["state"] != "cleaned"}) >= LIMITS["skills"]:
            raise ValueError("D Skill resource cap reached")
        prefix = "d-" + evaluation_key[:16]
        self._current_row = row
        try:
            session_name = prefix + "-session"
            session = self.request(session_name, "POST", "/api/sessions",
                                   {"session_type": "general"})
            principal = session.get("user_id")
            session_id = session.get("session_id")
            adapter = ObservedGeneralControl(self.request, principal, prefix)
            adapter.adopt_session(session)
            self.registry.record(session_id, "session", "research-session-" + evaluation_key[:16],
                "created", owner_run_id=self.stage["run_id"], shared=False,
                environment=self.environment, case_id=row["case_id"], model_profile=row["model_profile"],
                variant=row["variant"], evaluation_key=evaluation_key, native_platform_resource=True)
            content = campaign.asset(self.source, row["skill_artifact"])
            created = adapter.create_skill(row["locators"]["resource_name"], content)
            self.registry.record(created["skill_id"], "skill", row["locators"]["resource_name"],
                "created", owner_run_id=self.stage["run_id"], shared=False,
                environment=self.environment, case_id=row["case_id"], model_profile=row["model_profile"],
                variant=row["variant"], evaluation_key=evaluation_key, native_platform_resource=True)
            readback = adapter.read_skill(created["skill_id"])
            if readback["version"] != created["version"]:
                raise ValueError("Skill changed during D provisioning")
            before = adapter.list_artifacts(session_id)
            if before.get("artifacts") != []:
                raise ValueError("D case starts with an occupied artifact scope")
            names = {"create_session": session_name,
                "create_skill": adapter.operations["create-skill"],
                "read_skill": adapter.operations["read-skill"],
                "sharing": adapter.operations["read-sharing"],
                "artifact_before": adapter.operations["list-artifacts"]}
            binding = {"kind": "skill-generated-smoke-binding", "environment": self.environment,
                "source_root": str(self.source.resolve()),
                "stage_plan_sha256": runtime.sha256_file(self.stage_path),
                "evaluation_key": evaluation_key, "principal_id": principal,
                "skill_id": created["skill_id"], "skill_version": str(created["version"]),
                "session_id": session_id,
                "receipts": {key: self.receipts[value] for key, value in names.items()}}
            binding_path = self.run / ("binding-" + evaluation_key + ".json")
            runtime.write_json(binding_path, binding)
            validate_binding(binding_path, runtime.sha256_file(binding_path),
                             live=self.environment == "live")
            return {"binding_path": str(binding_path),
                "binding_sha256": runtime.sha256_file(binding_path),
                "session_id": session_id, "skill_id": created["skill_id"],
                "management_http_attempts": self.ledger.state["counts"]["management"],
                "target_calls": 0, "environment": self.environment}
        except Exception as exc:
            self.ledger.stop("D-provision-error:" + type(exc).__name__)
            raise
        finally:
            self._current_row = None
