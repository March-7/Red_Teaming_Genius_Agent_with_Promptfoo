"""Validate and authorize breadth-first revisions for the six remaining pilot risks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file
from .benchmark_adaptation import validate_manifest as validate_adaptation
from .pilot_ledger import PilotLedger, PilotBudgetError


OLD_LIMITS = {"target": 96, "management": 1200, "recovery": 120,
              "cleanup": 180, "generation": 0, "judge": 0, "retry": 0}
TOTAL_LIMITS = {"target": 96, "management": 1440, "recovery": 120,
                "cleanup": 180, "generation": 0, "judge": 0, "retry": 0}
INCREMENT_LIMITS = {"target": 36, "management": 720, "recovery": 72,
                    "cleanup": 108, "generation": 0, "judge": 0, "retry": 0}
CASE_LIMITS = {"target": 6, "management": 120, "recovery": 12,
               "cleanup": 18, "generation": 0, "judge": 0, "retry": 0}
CASE_PARENTS = {
    "receiver-exfiltration-e2": "receiver-exfiltration",
    "unrequested-egress-e2": "unrequested-egress",
    "unrequested-code-e2": "unrequested-code",
    "bounded-resource-abuse-e2": "bounded-resource-abuse",
    "protected-data-copy-e2": "protected-data-copy",
    "security-config-tamper-e2": "security-config-tamper",
}
FAILURES = {
    "receiver-exfiltration-e2": "receiver-positive-control",
    "unrequested-egress-e2": "receiver-positive-control",
    "unrequested-code-e2": "positive-control-clarification",
    "bounded-resource-abuse-e2": "positive-control-input-and-oracle",
    "protected-data-copy-e2": "normal-control-contract",
    "security-config-tamper-e2": "attachment-format",
}
ORDER = [
    {"model_profile": "default", "variant": "positive"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "positive"},
    {"model_profile": "default", "variant": "normal"},
    {"model_profile": "default", "variant": "attack"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "normal"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "attack"},
]
FOLLOWUP_LIMITS = {"target": 30, "management": 600, "recovery": 60,
                   "cleanup": 90, "generation": 0, "judge": 0, "retry": 0}
FOLLOWUP_CASES = {"receiver-exfiltration-e3", "unrequested-code-e2",
                  "bounded-resource-abuse-e2", "protected-data-copy-e2",
                  "security-config-tamper-e2"}


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _load_ref(base: Path, ref: dict[str, str], label: str) -> tuple[Path, Any]:
    _exact(ref, {"file", "sha256"}, label)
    path = (base / ref["file"]).resolve()
    if not path.is_file() or sha256_file(path) != ref["sha256"]:
        raise ValueError(label + " drift")
    return path, json.loads(path.read_text())


def validate_case(root: Path, case_path: Path, revision_path: Path) -> dict[str, Any]:
    base = root / "skill-suites/benchmark-multi-risk"
    case = json.loads(case_path.read_text())
    revision = json.loads(revision_path.read_text())
    _exact(revision, {"schema_version", "kind", "revision_id", "parent_case_id",
        "risk_family", "failure_class", "parent_card_ref", "parent_case_ref",
        "parent_pilot_summary_ref", "changes", "risk_semantics_changed",
        "authorized_candidate_iteration"}, "stage E revision")
    if (revision["schema_version"] != 1 or revision["kind"] != "skill-risk-stage-e-revision"
            or revision["revision_id"] != case["case_id"]
            or CASE_PARENTS.get(case["case_id"]) != revision["parent_case_id"]
            or revision["failure_class"] != FAILURES.get(case["case_id"])
            or revision["risk_semantics_changed"] is not False
            or revision["authorized_candidate_iteration"] is not True):
        raise ValueError("stage E revision scope drift")
    _card_path, card = _load_ref(base / "risk-cards", revision["parent_card_ref"],
                                 "stage E parent card")
    _parent_path, parent = _load_ref(base / "pilot-cases" / revision["parent_case_id"],
                                     revision["parent_case_ref"], "stage E parent case")
    _summary_path, summary = _load_ref(base, revision["parent_pilot_summary_ref"],
                                       "stage E initial pilot summary")
    prior = next((row for row in summary["outcomes"]
                  if row["case_id"] == revision["parent_case_id"]), None)
    if (prior is None or prior["formal_eligible"] is not False
            or card["risk_family"] != revision["risk_family"]
            or parent["risk_family"] != revision["risk_family"]
            or case["risk_family"] != revision["risk_family"]
            or case["limits"] != CASE_LIMITS
            or case["actual_calls"] != dict.fromkeys(CASE_LIMITS, 0)
            or case["target_context"] != "global-general"
            or case["session_type"] != "general"):
        raise ValueError("stage E prior blocker, risk, budget or route drift")
    if not revision["changes"]:
        raise ValueError("stage E evidence-linked changes required")
    for change in revision["changes"]:
        _exact(change, {"field", "before_sha256", "after_sha256", "reason"},
               "stage E revision change")
        if (change["before_sha256"] == change["after_sha256"] or not change["reason"]):
            raise ValueError("stage E revision must use a new hash and reason")
    normal_path = case_path.parent / case["skills"]["normal"]["file"]
    attack_path = case_path.parent / case["skills"]["attack"]["file"]
    normal, attack = normal_path.read_text(), attack_path.read_text()
    if (sha256_file(normal_path) != case["skills"]["normal"]["sha256"]
            or sha256_file(attack_path) != case["skills"]["attack"]["sha256"]
            or not attack.startswith(normal.rstrip() + "\n\n")):
        raise ValueError("stage E Skill carrier drift")
    if (case["legitimate_task_sha256"] == parent["legitimate_task_sha256"]
            and case["skills"]["normal"]["sha256"] == parent["skills"]["normal"]["sha256"]
            and case["initial_assets"] == parent["initial_assets"]):
        raise ValueError("stage E revision requires a new task, normal Skill or input asset")
    for ref in case["source_adaptations"]:
        path = case_path.parent / ref["file"]
        if sha256_file(path) != ref["sha256"]:
            raise ValueError("stage E adaptation hash drift")
        validate_adaptation(path, base / "source-registry.json",
            base / "source-inventory.jsonl", base / "source-inventory-summary.json")
    return {"case_id": case["case_id"], "parent_case_id": revision["parent_case_id"],
            "risk_family": case["risk_family"], "failure_class": revision["failure_class"]}


def validate_master(root: Path, master_path: Path, authorization_path: Path) -> dict[str, Any]:
    base = root / "skill-suites/benchmark-multi-risk"
    master = json.loads(master_path.read_text())
    auth = json.loads(authorization_path.read_text())
    _exact(master, {"schema_version", "kind", "status", "iteration_offset", "worker_count",
        "workers", "planned_limits", "actual_calls", "target_context", "session_type",
        "retry", "max_concurrency", "formal_asr_eligible"}, "stage E master")
    _exact(auth, {"schema_version", "kind", "actor", "decision", "effective_date",
        "prior_authorization_sha256", "pilot_summary_v2_sha256", "candidate_iteration_cap",
        "increment_limits", "total_api_limits", "management_limit_amendment",
        "stage_e_master_sha256", "message_ref", "status"}, "stage E authorization")
    if (master["schema_version"] != 1 or master["kind"] != "skill-multi-risk-stage-e-master"
            or master["status"] != "stage-e-authorized-not-started"
            or master["iteration_offset"] != 14 or master["worker_count"] != 6
            or len(master["workers"]) != 6 or master["planned_limits"] != INCREMENT_LIMITS
            or master["actual_calls"] != dict.fromkeys(CASE_LIMITS, 0)
            or master["target_context"] != "global-general"
            or master["session_type"] != "general" or master["retry"] != 0
            or master["max_concurrency"] != 1 or master["formal_asr_eligible"] is not False):
        raise ValueError("stage E master boundary drift")
    if (auth["schema_version"] != 1 or auth["kind"] != "skill-pilot-stage-e-authorization"
            or auth["actor"] != "human-user" or auth["decision"] != "start-stage-e-ten-risk-coverage"
            or auth["candidate_iteration_cap"] != 22
            or auth["increment_limits"] != INCREMENT_LIMITS
            or auth["total_api_limits"] != TOTAL_LIMITS
            or auth["management_limit_amendment"] != {"from": 1200, "to": 1440}
            or auth["stage_e_master_sha256"] != sha256_file(master_path)
            or auth["prior_authorization_sha256"] != sha256_file(
                base / "standing-authorization-extension.json")
            or auth["pilot_summary_v2_sha256"] != sha256_file(base / "pilot-summary-v2.json")
            or auth["status"] != "active" or not auth["message_ref"]):
        raise ValueError("stage E user authorization drift")
    seen, results = set(), []
    for position, worker in enumerate(master["workers"]):
        _exact(worker, {"position", "case_id", "risk_family", "case_file", "case_sha256",
            "revision_file", "revision_sha256", "call_order", "limits", "status"},
            "stage E worker")
        case_path, revision_path = Path(worker["case_file"]), Path(worker["revision_file"])
        if (worker["position"] != position or worker["case_id"] in seen
                or worker["case_sha256"] != sha256_file(case_path)
                or worker["revision_sha256"] != sha256_file(revision_path)
                or worker["call_order"] != ORDER or worker["limits"] != CASE_LIMITS
                or worker["status"] != "not-started"):
            raise ValueError("stage E worker source, order or budget drift")
        seen.add(worker["case_id"])
        result = validate_case(root, case_path, revision_path)
        if result["case_id"] != worker["case_id"] or result["risk_family"] != worker["risk_family"]:
            raise ValueError("stage E worker identity drift")
        results.append(result)
    if set(seen) != set(CASE_PARENTS) or master["iteration_offset"] + len(seen) != 20:
        raise ValueError("stage E six-case coverage or iteration count drift")
    return {"valid": True, "worker_count": 6, "candidate_iterations_total": 20,
            "candidate_iteration_cap": 22, "planned_limits": INCREMENT_LIMITS,
            "total_api_limits": TOTAL_LIMITS, "actual_calls": master["actual_calls"],
            "formal_asr_eligible": False}


def apply_budget_amendment(root: Path, authorization_path: Path,
                           master_path: Path) -> dict[str, Any]:
    validate_master(root, master_path, authorization_path)
    ledger_path = root / "skill-suites/benchmark-multi-risk/runs/pilot-standing-ledger.json"
    state = json.loads(ledger_path.read_text())
    auth_hash = sha256_file(authorization_path)
    if state.get("limits") == TOTAL_LIMITS:
        matches = [row for row in state.get("limit_amendments", [])
                   if row.get("authorization_sha256") == auth_hash]
        if len(matches) != 1:
            raise PilotBudgetError("amended ledger lacks unique authorization evidence")
        return {"amended": True, "idempotent": True, "limits": TOTAL_LIMITS,
                "counts": state["counts"], "authorization_sha256": auth_hash}
    ledger = PilotLedger(ledger_path, OLD_LIMITS)
    ledger.amend_limits(TOTAL_LIMITS, authorization_path=authorization_path)
    return {"amended": True, "idempotent": False, "limits": TOTAL_LIMITS,
            "counts": ledger.state["counts"], "authorization_sha256": auth_hash}


def validate_followup_master(root: Path, master_path: Path,
                             authorization_path: Path) -> dict[str, Any]:
    base = root / "skill-suites/benchmark-multi-risk"
    master = json.loads(master_path.read_text())
    auth = json.loads(authorization_path.read_text())
    _exact(master, {"schema_version", "kind", "status", "iteration_offset", "worker_count",
        "workers", "planned_limits", "actual_calls", "target_context", "session_type",
        "retry", "max_concurrency", "formal_asr_eligible"}, "stage E followup master")
    _exact(auth, {"schema_version", "kind", "actor", "decision", "effective_date",
        "stage_e_authorization_sha256", "receiver_recovery_file", "receiver_recovery_sha256",
        "candidate_iteration_cap", "increment_limits", "total_api_limits",
        "followup_master_sha256", "message_ref", "status"},
        "stage E followup authorization")
    if (master["schema_version"] != 1
            or master["kind"] != "skill-multi-risk-stage-e-followup-master"
            or master["status"] != "stage-e-followup-authorized-not-started"
            or master["iteration_offset"] != 15 or master["worker_count"] != 5
            or len(master["workers"]) != 5 or master["planned_limits"] != FOLLOWUP_LIMITS
            or master["actual_calls"] != dict.fromkeys(CASE_LIMITS, 0)
            or master["target_context"] != "global-general"
            or master["session_type"] != "general" or master["retry"] != 0
            or master["max_concurrency"] != 1 or master["formal_asr_eligible"] is not False):
        raise ValueError("stage E followup master boundary drift")
    recovery = Path(auth["receiver_recovery_file"])
    if (auth["schema_version"] != 1
            or auth["kind"] != "skill-pilot-stage-e-followup-authorization"
            or auth["actor"] != "human-user"
            or auth["decision"] != "continue-stage-e-with-recovered-receiver-locator"
            or auth["stage_e_authorization_sha256"] != sha256_file(
                base / "standing-authorization-stage-e.json")
            or not recovery.is_file()
            or auth["receiver_recovery_sha256"] != sha256_file(recovery)
            or auth["candidate_iteration_cap"] != 22
            or auth["increment_limits"] != FOLLOWUP_LIMITS
            or auth["total_api_limits"] != TOTAL_LIMITS
            or auth["followup_master_sha256"] != sha256_file(master_path)
            or auth["status"] != "active" or not auth["message_ref"]):
        raise ValueError("stage E followup authorization drift")
    seen = set()
    for position, worker in enumerate(master["workers"]):
        _exact(worker, {"position", "case_id", "risk_family", "case_file", "case_sha256",
            "revision_file", "revision_sha256", "call_order", "limits", "status"},
            "stage E followup worker")
        case_path, revision_path = Path(worker["case_file"]), Path(worker["revision_file"])
        if (worker["position"] != position or worker["case_id"] in seen
                or worker["case_sha256"] != sha256_file(case_path)
                or worker["revision_sha256"] != sha256_file(revision_path)
                or worker["call_order"] != ORDER or worker["limits"] != CASE_LIMITS
                or worker["status"] != "not-started"):
            raise ValueError("stage E followup worker source, order or budget drift")
        seen.add(worker["case_id"])
        if worker["case_id"] == "receiver-exfiltration-e3":
            case = json.loads(case_path.read_text())
            revision = json.loads(revision_path.read_text())
            if (case["risk_family"] != "receiver-confirmed-data-exfiltration"
                    or revision.get("failure_class") != "receiver-locator-contract"
                    or revision.get("risk_semantics_changed") is not False
                    or revision.get("receiver_recovery_ref", {}).get("sha256") !=
                       sha256_file(recovery)):
                raise ValueError("recovered receiver revision drift")
        else:
            validate_case(root, case_path, revision_path)
    if seen != FOLLOWUP_CASES or master["iteration_offset"] + len(seen) != 20:
        raise ValueError("stage E followup five-case coverage drift")
    return {"valid": True, "worker_count": 5, "candidate_iterations_total": 20,
            "candidate_iteration_cap": 22, "planned_limits": FOLLOWUP_LIMITS,
            "total_api_limits": TOTAL_LIMITS, "actual_calls": master["actual_calls"],
            "formal_asr_eligible": False}
