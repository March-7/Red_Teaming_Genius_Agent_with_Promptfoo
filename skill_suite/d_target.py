"""One-shot D target submission with a durable result and no Judge call."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import quote

from sweep import runtime
from . import campaign
from .budget import BudgetError
from .d_binding import bound_request, case_request, validate_binding
from .evidence import read_ref
from .http_accounting import meter_client
from .schema import canonical_hash


def require_live_skill_age(run: Path, binding: dict[str, Any],
                           minimum_seconds: int, *, now: datetime | None = None) -> None:
    """Require one matching Skill POST and a bounded catalogue propagation window."""
    created = read_ref(run, binding["receipts"]["create_skill"])
    observed_at = created.get("observed_at")
    campaign.timestamp(observed_at)
    current = now or datetime.now(timezone.utc)
    age = (current - datetime.fromisoformat(observed_at.replace("Z", "+00:00"))).total_seconds()
    if (created.get("request", {}).get("method") != "POST"
            or created["request"].get("path") != "/api/skills"
            or created.get("response", {}).get("body", {}).get("skill_id") != binding["skill_id"]
            or age < minimum_seconds):
        raise ValueError("freshly created Skill has not passed the D propagation wait")


def submit_one(provisioner: Any, binding_path: Path,
               *, fixture_target: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    """Submit exactly one pinned row; fixture callbacks cannot enable live work."""
    provisioner.lease.require_active()
    live = provisioner.environment == "live"
    if (live and fixture_target is not None) or (not live and fixture_target is None):
        raise ValueError("D target transport must match the approved environment")
    row, binding = validate_binding(binding_path, runtime.sha256_file(binding_path), live=live)
    stage = provisioner.stage
    request = case_request(stage, row, binding)
    bound_request(binding_path, runtime.sha256_file(binding_path), request, live=live)
    key = row["evaluation_key"]
    result_path = provisioner.run / ("d-target-result-" + key + ".json")
    if result_path.exists():
        raise ValueError("D target result already exists; no replay")
    operation = "target:" + key
    if any(item["operation_id"] == operation for item in provisioner.ledger.state["attempts"]):
        raise BudgetError("zero retries: D target already attempted")
    if provisioner.ledger.state["stopped"]:
        raise BudgetError("new D target work stopped: " + provisioner.ledger.state["stopped"])
    if live:
        require_live_skill_age(provisioner.run, binding, stage["min_skill_age_seconds"])
    before_name = "d-" + key[:16] + "-before-skill"
    catalogue = provisioner.request(before_name, "GET",
        "/api/skills/" + quote(binding["skill_id"], safe=""))
    source_body = campaign.asset(provisioner.source, row["skill_artifact"])
    metadata = catalogue.get("skill", {})
    if (metadata.get("skill_id") != binding["skill_id"]
            or metadata.get("name") != row["locators"]["resource_name"]
            or metadata.get("owner_id") != binding["principal_id"]
            or metadata.get("visibility") != "private"
            or metadata.get("instructions") != source_body
            or str(metadata.get("version")) != binding["skill_version"]):
        provisioner.ledger.stop("D-pretarget-skill-drift")
        raise ValueError("fresh private Skill readback differs before target")
    before_path = provisioner.run / (before_name + ".json")
    before_ref = {"file": before_path.name, "sha256": runtime.sha256_file(before_path)}
    provisioner.ledger.reserve("target", operation)
    submitted_at = runtime.utc_now()
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    try:
        if live:
            from shim.genius_service import GeniusService
            config = replace(provisioner.service.config,
                skill_case_registry_path=str(binding_path),
                skill_case_registry_hash=runtime.sha256_file(binding_path),
                approval_policy_file=str(provisioner.run / "approval-policy.json"),
                upstream_retry_attempts=0, human_input_continue_plugin="")
            target_service = GeniusService(config, client=provisioner.service._client)
            try:
                with meter_client(provisioner.service._client, provisioner.ledger, operation) as records:
                    _answer, result = target_service.complete(request)
            finally:
                target_service.close()
            sent = [item for item in records if item["kind"] == "target"]
            if len(sent) != 1 or sent[0]["outcome"] != "completed":
                raise ValueError("one successful native target HTTP attempt required")
        else:
            result = fixture_target(request)
        raw = asdict(result) if is_dataclass(result) else result
        if (not isinstance(raw, dict) or raw.get("terminal_status") != "completed"
                or raw.get("upstream_session_id") != binding["session_id"]
                or not raw.get("request_id") or not isinstance(raw.get("content"), str)
                or not isinstance(raw.get("tool_events"), list)):
            raise ValueError("matching completed D target result required")
        finished_at = runtime.utc_now()
        envelope = {"kind": "skill-d-target-result", "environment": provisioner.environment,
            "evaluation_key": key, "session_id": binding["session_id"],
            "request_sha256": canonical_hash(request),
            "before_catalogue_ref": before_ref,
            "submitted_at": submitted_at, "finished_at": finished_at,
            "result": raw, "http_attempts": records, "formal_ready": False}
        runtime.durable_json(result_path, envelope)
        provisioner.ledger.finish(operation, "completed", elapsed_s=time.monotonic() - started)
        return {"target_result_ref": {"file": result_path.name,
                                      "sha256": runtime.sha256_file(result_path)},
                "evaluation_key": key, "environment": provisioner.environment,
                "target_calls": provisioner.ledger.state["counts"]["target"],
                "judge_calls": 0, "formal_ready": False}
    except Exception as exc:
        attempt = next(item for item in provisioner.ledger.state["attempts"]
                       if item["operation_id"] == operation)
        if attempt["outcome"] == "unknown":
            provisioner.ledger.finish(operation, "target-error",
                                      elapsed_s=time.monotonic() - started)
        if live and any(item["kind"] == "target" for item in records):
            runtime.record_pending(provisioner.root, stage["run_id"], binding["session_id"],
                                   "D target terminal unverified: " + operation)
        raise
