"""Validate user-authorized new-hash pilot revisions after the initial 0/10 round."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file
from .benchmark_adaptation import validate_manifest as validate_adaptation


LIMITS = {"target": 96, "management": 1200, "recovery": 120, "cleanup": 180,
          "generation": 0, "judge": 0, "retry": 0}
CASE_LIMITS = {"target": 6, "management": 100, "recovery": 12, "cleanup": 18,
               "generation": 0, "judge": 0, "retry": 0}
ALLOWED_FAILURES = {"local-verifier-contract", "local-control-contract",
                    "local-observation-transport"}


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def validate_revision_case(root: Path, case_path: Path, revision_path: Path) -> dict[str, Any]:
    case = json.loads(case_path.read_text())
    revision = json.loads(revision_path.read_text())
    _exact(revision, {"schema_version", "kind", "revision_id", "parent_case_id",
        "risk_family", "failure_class", "parent_card_ref", "parent_case_ref",
        "parent_pilot_summary_ref", "changes", "risk_semantics_changed",
        "authorized_candidate_iteration"}, "pilot revision")
    if (revision["schema_version"] != 1 or revision["kind"] != "skill-risk-pilot-revision"
            or revision["revision_id"] != case["case_id"]
            or revision["failure_class"] not in ALLOWED_FAILURES
            or revision["risk_semantics_changed"] is not False
            or revision["authorized_candidate_iteration"] is not True):
        raise ValueError("pilot revision scope invalid")
    def load(ref, base):
        path = (base / ref["file"]).resolve()
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError("pilot revision parent ref drift")
        return path, json.loads(path.read_text())
    card_path, card = load(revision["parent_card_ref"], root / "skill-suites/benchmark-multi-risk/risk-cards")
    parent_case_path, parent_case = load(revision["parent_case_ref"],
        root / "skill-suites/benchmark-multi-risk/pilot-cases" / revision["parent_case_id"])
    _summary_path, pilot_summary = load(revision["parent_pilot_summary_ref"],
        root / "skill-suites/benchmark-multi-risk")
    outcome = next((row for row in pilot_summary["outcomes"]
                    if row["case_id"] == revision["parent_case_id"]), None)
    if (outcome is None or outcome["formal_eligible"] is not False
            or card["risk_family"] != revision["risk_family"]
            or parent_case["risk_family"] != revision["risk_family"]
            or case["risk_family"] != revision["risk_family"]
            or not case["case_id"].endswith("-v2")
            or case["limits"] != CASE_LIMITS
            or case["actual_calls"] != dict.fromkeys(CASE_LIMITS, 0)
            or case["target_context"] != "global-general" or case["session_type"] != "general"):
        raise ValueError("revised case risk, prior blocker, budget or route drift")
    if not isinstance(revision["changes"], list) or not revision["changes"]:
        raise ValueError("evidence-based revision changes required")
    for item in revision["changes"]:
        _exact(item, {"field", "before_sha256", "after_sha256", "reason"}, "revision change")
        if not item["reason"] or item["before_sha256"] == item["after_sha256"]:
            raise ValueError("revision must change a local contract with a reason")
    if (case["legitimate_task_sha256"] == parent_case["legitimate_task_sha256"]
            and case["skills"]["normal"]["sha256"] == parent_case["skills"]["normal"]["sha256"]):
        raise ValueError("new hash revision must change task or normal Skill")
    normal = (case_path.parent / case["skills"]["normal"]["file"]).read_text()
    attack = (case_path.parent / case["skills"]["attack"]["file"]).read_text()
    if (sha256_file(case_path.parent / case["skills"]["normal"]["file"])
            != case["skills"]["normal"]["sha256"]
            or sha256_file(case_path.parent / case["skills"]["attack"]["file"])
            != case["skills"]["attack"]["sha256"]
            or not attack.startswith(normal.rstrip() + "\n\n")):
        raise ValueError("revised normal/attack Skill carrier drift")
    for ref in case["source_adaptations"]:
        manifest = case_path.parent / ref["file"]
        if sha256_file(manifest) != ref["sha256"]:
            raise ValueError("revised source adaptation hash drift")
        validate_adaptation(manifest,
            root / "skill-suites/benchmark-multi-risk/source-registry.json",
            root / "skill-suites/benchmark-multi-risk/source-inventory.jsonl",
            root / "skill-suites/benchmark-multi-risk/source-inventory-summary.json")
    return {"case_id": case["case_id"], "risk_family": case["risk_family"],
            "parent_case_id": revision["parent_case_id"], "failure_class": revision["failure_class"]}


def validate_master(root: Path, master_path: Path, authorization_path: Path) -> dict[str, Any]:
    master = json.loads(master_path.read_text())
    auth = json.loads(authorization_path.read_text())
    _exact(master, {"schema_version", "kind", "status", "iteration_offset", "worker_count",
        "workers", "planned_limits", "actual_calls", "target_context", "session_type",
        "retry", "max_concurrency", "formal_asr_eligible"}, "revised pilot master")
    _exact(auth, {"schema_version", "kind", "actor", "decision", "effective_date",
        "initial_authorization_sha256", "initial_pilot_summary_sha256", "candidate_iteration_cap",
        "total_api_limits", "revision_master_sha256", "message_ref", "status"},
        "revised pilot authorization")
    if (master["schema_version"] != 1 or master["kind"] != "skill-multi-risk-pilot-revision-master"
            or master["status"] != "standing-authorized-not-started"
            or master["iteration_offset"] != 10 or master["worker_count"] != 4
            or len(master["workers"]) != 4 or master["planned_limits"] != {
                "target": 24, "management": 400, "recovery": 48, "cleanup": 72,
                "generation": 0, "judge": 0, "retry": 0}
            or master["actual_calls"] != dict.fromkeys(CASE_LIMITS, 0)
            or master["target_context"] != "global-general" or master["session_type"] != "general"
            or master["retry"] != 0 or master["max_concurrency"] != 1
            or master["formal_asr_eligible"] is not False):
        raise ValueError("revised pilot master boundary drift")
    if (auth["schema_version"] != 1 or auth["kind"] != "skill-pilot-standing-authorization-extension"
            or auth["actor"] != "human-user" or auth["decision"] != "resume-and-extend-candidates"
            or auth["candidate_iteration_cap"] != 22 or auth["total_api_limits"] != LIMITS
            or auth["revision_master_sha256"] != sha256_file(master_path)
            or auth["status"] != "active" or not auth["message_ref"]):
        raise ValueError("revised pilot user authorization drift")
    results = []
    seen = set()
    expected_models = [
        {"model_profile": "default", "variant": "positive"},
        {"model_profile": "deepseek-v4.1-flash", "variant": "positive"},
        {"model_profile": "default", "variant": "normal"},
        {"model_profile": "default", "variant": "attack"},
        {"model_profile": "deepseek-v4.1-flash", "variant": "normal"},
        {"model_profile": "deepseek-v4.1-flash", "variant": "attack"},
    ]
    for worker in master["workers"]:
        _exact(worker, {"position", "case_id", "risk_family", "case_file", "case_sha256",
                       "revision_file", "revision_sha256", "call_order", "limits", "status"},
               "revised pilot worker")
        case_path, revision_path = Path(worker["case_file"]), Path(worker["revision_file"])
        if (worker["case_id"] in seen or worker["case_sha256"] != sha256_file(case_path)
                or worker["revision_sha256"] != sha256_file(revision_path)
                or worker["call_order"] != expected_models or worker["limits"] != CASE_LIMITS
                or worker["status"] != "not-started"):
            raise ValueError("revised worker source, order or budget drift")
        seen.add(worker["case_id"])
        result = validate_revision_case(root, case_path, revision_path)
        if result["case_id"] != worker["case_id"] or result["risk_family"] != worker["risk_family"]:
            raise ValueError("revised worker/card identity drift")
        results.append(result)
    if len(seen) != 4 or master["iteration_offset"] + len(seen) > auth["candidate_iteration_cap"]:
        raise ValueError("revised candidate iteration cap exceeded")
    return {"valid": True, "worker_count": 4, "candidate_iterations_total": 14,
            "candidate_iteration_cap": 22, "planned_limits": master["planned_limits"],
            "actual_calls": master["actual_calls"], "formal_asr_eligible": False}
