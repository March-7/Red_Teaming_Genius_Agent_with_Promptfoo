"""Strict, local-only suite and case contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml
from sweep.models import MATRIX
from sweep.resource_naming import validate_neutral_user_question

IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}$")
RESOURCE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@-]{0,254}$")
HASH = re.compile(r"^[a-f0-9]{64}$")
CALL_KINDS = ("target", "management", "recovery", "cleanup", "generation", "judge")
PHASES = {
    "A": {"target": 4, "management": 64, "recovery": 4, "cleanup": 12,
          "generation": 0, "judge": 0, "activity_total_s": 1200,
          "activity_per_call_s": 300, "skills": 2, "scopes": 4, "sessions": 4},
    "B": {"target": 6, "management": 128, "recovery": 4, "cleanup": 12,
          "generation": 0, "judge": 0, "activity_total_s": 1800,
          "activity_per_call_s": 300, "skills": 6, "scopes": 6, "sessions": 6},
    "C": {**dict.fromkeys(CALL_KINDS, 0), "activity_total_s": 0,
          "activity_per_call_s": 0, "skills": 0, "scopes": 0, "sessions": 0},
}


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_hash(value: Any) -> str:
    return text_hash(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def resource_identifier(value: Any, label: str = "resource_id") -> str:
    """Validate an opaque Genius resource id without widening local ids.

    Package Skill ids use ``name@org`` while session ids use ``:``. Run,
    case, and artifact ids continue to use the stricter ``identifier``.
    """
    if not isinstance(value, str) or not RESOURCE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def logical_scope_id(run_id: str, case_id: str) -> str:
    """A lifecycle case partition; it is not a Genius Project or routing key."""
    identifier(run_id, "run_id")
    identifier(case_id, "case_id")
    return identifier(f"scope:{run_id}:{case_id}", "logical scope_id")


def content_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def load_suite(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_suite(data)
    return data


def validate_suite(data: Any) -> None:
    required = {"schema_version", "kind", "suite_id", "risk_id", "phase", "model_matrix",
                "phases", "max_concurrency", "retry", "approval_policy", "task_template",
                "allowed_behavior", "failure_criterion", "examples", "interface_attestation",
                "lifecycle", "confirmation"}
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version == 2: required.add("target_context")
    if isinstance(data, dict) and data.get("phase") == "B": required.add("allowed_write_task_template")
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("suite has missing or unknown fields")
    if type(version) is not int or version not in {1, 2} or data["kind"] != "skill-suite":
        raise ValueError("unsupported suite schema")
    if version == 2 and data["target_context"] != "global-general":
        raise ValueError("main Skill suite requires the global general assistant")
    identifier(data["suite_id"], "suite_id")
    if data["risk_id"] != "skill-task-scope-write" or data["phase"] not in PHASES:
        raise ValueError("unsupported risk or phase")
    expected = [{"label": label, "model_profile": profile, "reasoning_effort": "high", "thinking": "on"}
                for label, profile, _ in MATRIX]
    if data["model_matrix"] != expected:
        raise ValueError("fixed paired model matrix required")
    # Earlier completed A runs pinned the old, smaller prospective B budget.
    # They remain readable, but a new B run must use the current reviewed limit.
    historical_a_phases = {**PHASES, "B": {**PHASES["B"], "management": 40}}
    allowed_phases = data["phases"] == PHASES or (data["phase"] == "A" and data["phases"] == historical_a_phases)
    if not allowed_phases or any(type(v) is not int for p in data["phases"].values() for v in p.values()):
        raise ValueError("phase budgets differ from the prepared contract; revise and review before execution")
    if type(data["retry"]) is not int or data["retry"] != 0 or data["max_concurrency"] != 1:
        raise ValueError("A/B require zero retries and serial execution")
    if data["lifecycle"] not in {"unselected", "retain", "cleanup"}:
        raise ValueError("invalid lifecycle")
    if data["approval_policy"] != "approval-policy.json":
        raise ValueError("suite-local approval policy required")
    for key in (("task_template", "allowed_write_task_template", "allowed_behavior", "failure_criterion")
                if data["phase"] == "B" else ("task_template", "allowed_behavior", "failure_criterion")):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"missing {key}")
    validate_neutral_user_question(data["task_template"])
    if data["phase"] == "B": validate_neutral_user_question(data["allowed_write_task_template"])
    if not isinstance(data["examples"], list) or len(data["examples"]) != 2:
        raise ValueError("exactly two explanatory examples required")
    if any(not isinstance(v, str) or not v for v in data["examples"]):
        raise ValueError("invalid examples")
    # No online confirmation or capability facts are inferred from configuration.
    if data["interface_attestation"] is not None:
        identifier(data["interface_attestation"], "interface attestation id")
    if data["confirmation"] is not None and not isinstance(data["confirmation"], dict):
        raise ValueError("invalid confirmation")


def validate_case(row: dict[str, Any], suite: dict[str, Any]) -> None:
    required = {"schema_version", "run_id", "suite_id", "risk_id", "case_id", "variant",
                "model_profile", "reasoning_effort", "thinking", "scope_id", "session_id",
                "resource_name", "record_id", "user_task", "task_hash", "task_template_hash",
                "initial_state_hash", "skill_id", "skill_version", "skill_hash", "asset_hash"}
    if suite["schema_version"] == 2: required.add("target_context")
    if set(row) != required or type(row["schema_version"]) is not int or row["schema_version"] != suite["schema_version"]:
        raise ValueError("case has missing or unknown fields")
    if suite["schema_version"] == 2 and (row["target_context"] != "global-general"
                                         or not str(row["session_id"]).startswith("chat:")):
        raise ValueError("global case cannot use a Workspace session")
    for key in ("run_id", "case_id", "scope_id", "session_id", "record_id"):
        identifier(row[key], key)
    if row["suite_id"] != suite["suite_id"] or row["risk_id"] != suite["risk_id"]:
        raise ValueError("case belongs to another suite/risk")
    variants = {"normal", "absent"} if suite["phase"] == "A" else {"normal", "attack", "allowed-write"}
    if row["variant"] not in variants:
        raise ValueError("variant not allowed in this phase")
    if row["model_profile"] not in {p for _, p, _ in MATRIX} or row["reasoning_effort"] != "high" or row["thinking"] != "on":
        raise ValueError("case model parameters differ")
    for key in ("task_hash", "task_template_hash", "initial_state_hash"):
        content_hash(row[key], key)
    template = (suite["allowed_write_task_template"] if suite["phase"] == "B" and row["variant"] == "allowed-write"
                else suite["task_template"])
    if row["task_template_hash"] != text_hash(template):
        raise ValueError("task template changed")
    expected = template.format(resource_name=row["resource_name"], record_id=row["record_id"])
    if row["user_task"] != expected or text_hash(expected) != row["task_hash"]:
        raise ValueError("user task changed or contains Skill payload")
    validate_neutral_user_question(expected)
    if row["variant"] == "absent":
        if any(row[k] is not None for k in ("skill_id", "skill_version", "skill_hash", "asset_hash")):
            raise ValueError("absent control must not bind a Skill")
    else:
        identifier(row["skill_id"], "skill_id")
        for key in ("skill_hash", "asset_hash"):
            content_hash(row[key], key)
        if row["skill_version"] is not None:
            identifier(row["skill_version"], "skill_version")


def validate_isolation(rows: list[dict[str, Any]], suite: dict[str, Any]) -> None:
    seen: dict[str, set[Any]] = {k: set() for k in ("scope_id", "session_id")}
    keys = set()
    for row in rows:
        validate_case(row, suite)
        key = (row["case_id"], row["model_profile"], row["variant"])
        if key in keys:
            raise ValueError("duplicate case/model/variant")
        keys.add(key)
        for field in seen:
            if row[field] in seen[field]:
                raise ValueError(f"shared {field}; native scope/session isolation required")
            seen[field].add(row[field])
    if len(rows) > suite["phases"][suite["phase"]]["target"]:
        raise ValueError("registry exceeds phase target budget")
