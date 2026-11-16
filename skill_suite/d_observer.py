"""Offline-verifiable D Skill-read and independent session artifact observation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from . import campaign
from .artifact_download import download_artifact
from .d_binding import validate_binding
from .evidence import read_ref
from .file_oracle import normalize_session_artifacts
from .general_a import skill_result
from .schema import text_hash


def observe(provisioner: Any, binding_path: Path,
            target_result_ref: dict[str, str]) -> dict[str, Any]:
    """Read target evidence and state; no Judge or new target submission."""
    provisioner.lease.require_active()
    run = provisioner.run
    row, binding = validate_binding(binding_path, runtime.sha256_file(binding_path),
                                    live=provisioner.environment == "live")
    key = row["evaluation_key"]
    output_path = run / ("d-observation-" + key + ".json")
    if output_path.exists():
        raise ValueError("D case already observed; no replay")
    operation = "target:" + key
    attempts = [item for item in provisioner.ledger.state["attempts"]
                if item["operation_id"] == operation and item["kind"] == "target"]
    if len(attempts) != 1 or attempts[0]["outcome"] != "completed":
        raise ValueError("completed matching target attempt required before state observation")
    envelope = read_ref(run, target_result_ref)
    result = envelope.get("result", {}) if isinstance(envelope, dict) else {}
    if (envelope.get("environment") != provisioner.environment
            or result.get("terminal_status") != "completed"
            or result.get("upstream_session_id") != binding["session_id"]
            or not result.get("request_id") or not isinstance(result.get("tool_events"), list)):
        raise ValueError("matching terminal target evidence required")
    campaign.timestamp(envelope.get("submitted_at"))
    campaign.timestamp(envelope.get("finished_at"))
    def instant(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    before = read_ref(run, binding["receipts"]["artifact_before"])
    before_catalogue = read_ref(run, envelope.get("before_catalogue_ref"))
    before_skill = before_catalogue.get("response", {}).get("body", {}).get("skill", {})
    if (before_catalogue.get("request", {}).get("method") != "GET"
            or before_catalogue["request"].get("path") !=
            "/api/skills/" + quote(binding["skill_id"], safe="")
            or before_catalogue.get("response", {}).get("status") != 200
            or before_skill.get("skill_id") != binding["skill_id"]
            or before_skill.get("owner_id") != binding["principal_id"]
            or before_skill.get("instructions") != campaign.asset(provisioner.source, row["skill_artifact"])
            or str(before_skill.get("version")) != binding["skill_version"]):
        raise ValueError("fresh pre-target private Skill source evidence missing")
    if (instant(before["observed_at"]) >= instant(envelope["submitted_at"])
            or instant(before_catalogue["observed_at"]) >= instant(envelope["submitted_at"])
            or instant(before["observed_at"]) > instant(before_catalogue["observed_at"])
            or instant(attempts[0]["submitted_at"]) > instant(envelope["submitted_at"])
            or instant(envelope["submitted_at"]) > instant(envelope["finished_at"])):
        raise ValueError("D target/before-state causal time window invalid")
    output = result.get("content")
    if not isinstance(output, str):
        raise ValueError("target output missing")
    try:
        guarded = runtime.guard_output(output, known_hashes="")
        events = result["tool_events"]
        calls = [event for event in events if event.get("event_type") == "tool_call"
                 and event.get("tool_name") == "skill_read"
                 and event.get("request_id") == result["request_id"]
                 and event.get("tool_input") == {"skill_name": row["locators"]["resource_name"]}]
        reads = [event for event in events if event.get("event_type") == "tool_result"
                 and event.get("tool_name") == "skill_read" and event.get("status") == "success"
                 and event.get("request_id") == result["request_id"]
                 and event.get("tool_call_id") in {item.get("tool_call_id") for item in calls}]
        if (len(calls) != 1 or len(reads) != 1
                or not isinstance(calls[0].get("tool_call_id"), str)
                or not calls[0]["tool_call_id"]):
            raise ValueError("unique runtime Skill read required")
        runtime_skill = skill_result(reads[0].get("tool_result"))
        source_body = campaign.asset(provisioner.source, row["skill_artifact"])
        if (not runtime_skill or runtime_skill.get("status") != "ok"
                or runtime_skill.get("name") != row["locators"]["resource_name"]
                or runtime_skill.get("source") != "user"
                or runtime_skill.get("mode") != "text"
                or runtime_skill.get("instructions") != source_body
                or runtime_skill.get("resource") != "skill"):
            raise ValueError("runtime Skill body differs from frozen source")
        prefix = "d-" + key[:16]
        skill_path = "/api/skills/" + quote(binding["skill_id"], safe="")
        catalogue = provisioner.request(prefix + "-after-skill", "GET", skill_path)
        after_skill_path = run / (prefix + "-after-skill.json")
        after_skill_raw = json.loads(after_skill_path.read_text())
        if instant(after_skill_raw["observed_at"]) <= instant(envelope["finished_at"]):
            raise ValueError("post-target catalogue read did not follow terminal target")
        metadata = catalogue.get("skill", {})
        if (metadata.get("skill_id") != binding["skill_id"]
                or metadata.get("name") != row["locators"]["resource_name"]
                or metadata.get("owner_id") != binding["principal_id"]
                or metadata.get("visibility") != "private"
                or metadata.get("instructions") != source_body
                or str(metadata.get("version")) != binding["skill_version"]):
            raise ValueError("post-target private catalogue readback drift")
        session_path = "/api/sessions/" + quote(binding["session_id"], safe="") + "/artifacts"
        after = provisioner.request(prefix + "-after-artifacts", "GET", session_path)
        after_artifacts_path = run / (prefix + "-after-artifacts.json")
        after_artifacts_raw = json.loads(after_artifacts_path.read_text())
        if instant(after_artifacts_raw["observed_at"]) <= instant(envelope["finished_at"]):
            raise ValueError("independent artifact read did not follow terminal target")
        matching = [item for item in after.get("artifacts", [])
                    if item.get("filename") == row["locators"]["record_id"]]
        digest = None
        artifact_id = None
        download_ref = None
        cleanup_ref = None
        restored_ref = None
        if matching:
            if len(matching) != 1 or len(after["artifacts"]) != 1:
                raise ValueError("ambiguous target-created artifact")
            artifact = matching[0]
            if (artifact.get("scope_id") != binding["session_id"]
                    or not isinstance(artifact.get("file_token"), str)
                    or not artifact["file_token"]):
                raise ValueError("listed artifact session/capability mismatch")
            artifact_id = artifact["id"]
            body, receipt = download_artifact(provisioner.service, provisioner.ledger,
                run, prefix + "-download", session_id=binding["session_id"],
                artifact_id=artifact_id, filename=row["locators"]["record_id"],
                file_token=artifact["file_token"])
            digest = hashlib.sha256(body).hexdigest()
            download_path = run / (prefix + "-download.json")
            download_ref = {"file": download_path.name, "sha256": runtime.sha256_file(download_path)}
        state, derived_version, matched_id = normalize_session_artifacts(after,
            expected_name=row["locators"]["record_id"], downloaded_sha256=digest)
        if matched_id is not None:
            deleted = provisioner.request(prefix + "-delete-artifact", "DELETE", session_path,
                {"ids": [matched_id]}, accounting_kind="cleanup")
            if deleted.get("deleted") != 1:
                raise ValueError("owned artifact cleanup not confirmed")
            cleanup_path = run / (prefix + "-delete-artifact.json")
            cleanup_ref = {"file": cleanup_path.name, "sha256": runtime.sha256_file(cleanup_path)}
            restored = provisioner.request(prefix + "-restored-artifacts", "GET", session_path)
            restored_state, _, _ = normalize_session_artifacts(restored,
                expected_name=row["locators"]["record_id"])
            if restored_state != {"artifact_state": None, "other_artifacts": []}:
                raise ValueError("D artifact scope not restored")
            restored_path = run / (prefix + "-restored-artifacts.json")
            restored_ref = {"file": restored_path.name, "sha256": runtime.sha256_file(restored_path)}
        evidence = {"kind": "skill-d-observation", "environment": provisioner.environment,
            "evaluation_key": key, "case_id": row["case_id"],
            "model_profile": row["model_profile"], "variant": row["variant"],
            "session_id": binding["session_id"], "skill_id": binding["skill_id"],
            "skill_hash": text_hash(source_body), "runtime_skill_read_verified": True,
            "guard_sha256": runtime.sha256_file(runtime.GUARD_PATH),
            "guarded_output": guarded,
            "target_result_ref": target_result_ref,
            "post_catalogue_ref": {"file": after_skill_path.name, "sha256": runtime.sha256_file(after_skill_path)},
            "post_artifacts_ref": {"file": after_artifacts_path.name, "sha256": runtime.sha256_file(after_artifacts_path)},
            "download_ref": download_ref, "cleanup_ref": cleanup_ref,
            "restored_ref": restored_ref,
            "state_after": state, "derived_version": derived_version,
            "artifact_id": artifact_id, "independent_effect_observed": matched_id is not None,
            "review_decision": "pending", "formal_ready": False,
            "call_accounting": dict(provisioner.ledger.state["counts"])}
        runtime.write_json(output_path, evidence)
        return evidence
    except Exception as exc:
        provisioner.ledger.stop("D-observation-error:" + type(exc).__name__)
        raise
