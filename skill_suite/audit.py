"""Evidence levels for actual Skill identity and task behavior."""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any
from .evidence import read_ref
from .registry import validate_skill
from .schema import text_hash


def behavior_matches(oracle: dict[str, Any], output: str) -> bool:
    """Local structured output oracle; no evaluation of instructions or model text."""
    if oracle.get("format") != "json-object":
        return text_hash(output) == oracle.get("expected_output_hash")
    expected = oracle.get("expected_json")
    if not isinstance(expected, dict) or not expected or not isinstance(output, str):
        return False
    payload = output.strip()
    if oracle.get("allow_code_fence") is True:
        fenced = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", payload)
        if fenced: payload = fenced.group(1).strip()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("nonfinite JSON value")
    def equivalent(actual, wanted):
        if isinstance(actual, dict) and isinstance(wanted, dict):
            return set(actual) == set(wanted) and all(equivalent(actual[key], wanted[key]) for key in actual)
        if isinstance(actual, list) and isinstance(wanted, list):
            return len(actual) == len(wanted) and all(equivalent(a, b) for a, b in zip(actual, wanted))
        if type(actual) in {int, float} and type(wanted) in {int, float}: return actual == wanted
        return type(actual) is type(wanted) and actual == wanted
    try:
        parsed = json.loads(payload, object_pairs_hook=unique, parse_constant=invalid_constant)
        return equivalent(parsed, expected)
    except (TypeError, ValueError, RecursionError):
        return False


def source_audit(case: dict[str, Any], skill: dict[str, Any], refs: list[dict[str, Any]],
                 root: Path) -> dict[str, Any]:
    result = {key: case.get(key) for key in ("run_id", "suite_id", "risk_id", "case_id",
              "model_profile", "variant", "skill_id", "skill_version", "skill_hash")}
    result.update(kind="skill-source-audit", upstream_session_id=case["session_id"],
                  environment=skill.get("environment"), imported=False, bound=False,
                  selected=False, content_read=False, behavior_followed=False,
                  script_invoked=False, service_result_verified=False,
                  source_verified=False, evidence_refs=refs, errors=[])
    result["target_context"] = case.get("target_context", "historical-unspecified")
    result["session_type"] = "general" if case["session_id"].startswith("chat:") else "workspace"
    try:
        result["asset_provenance"] = validate_skill(skill, root, case)
        catalogue = case.get("target_context") == "global-general"
        result.update(imported=True, bound=not catalogue, catalogue_private=catalogue,
                      selection_intent=catalogue)
        for ref in refs:
            event = read_ref(root, ref)
            if (event.get("session_id") != case["session_id"]
                    or event.get("scope_id") != case["scope_id"]
                    or event.get("environment") != skill.get("environment")
                    or not event.get("request_id") or not event.get("local_turn_id")):
                raise ValueError("source event identity does not match the case")
            if result.get("request_id") and (result["request_id"] != event["request_id"]
                                             or result["local_turn_id"] != event["local_turn_id"]):
                raise ValueError("source evidence spans different turns")
            result.update(request_id=event["request_id"], local_turn_id=event["local_turn_id"])
            if event.get("kind") in {"skill-selected", "skill-content-read", "skill-script-invoked"}:
                if (event.get("skill_id") != case["skill_id"] or event.get("skill_version") != case["skill_version"]
                        or not event.get("tool_call_id")):
                    raise ValueError("selected Skill identity missing or changed")
                if catalogue and skill["environment"] == "live" and event["kind"] != "skill-script-invoked":
                    from .general_a import verify_runtime_identity
                    result["identity_resolution"] = verify_runtime_identity(event, root, case)
                if event["kind"] == "skill-selected":
                    result["selected"] = True
                if event["kind"] == "skill-content-read":
                    if text_hash(event.get("content", "")) != case["skill_hash"]:
                        raise ValueError("loaded Skill content hash mismatch")
                    result["content_read"] = True
                if event["kind"] == "skill-script-invoked":
                    result["script_invoked"] = True
                    result["script_tool_call_id"] = event["tool_call_id"]
            elif event.get("kind") == "assistant-output" and skill.get("behavior_oracle"):
                oracle = read_ref(root, skill["behavior_oracle"])
                if (oracle.get("skill_hash") != case["skill_hash"] or oracle.get("scope_id") != case["scope_id"]
                        or oracle.get("derived_from") != "skill-and-controlled-source"):
                    raise ValueError("behavior oracle not tied to Skill/source")
                result["behavior_followed"] = behavior_matches(oracle, event.get("content", ""))
            elif event.get("kind") == "tool-service-result":
                if event.get("tool_call_id") == result.get("script_tool_call_id"):
                    result["service_result_verified"] = event.get("success") is True
        if catalogue:
            # A task locator is intent. Only matching runtime adoption establishes binding.
            result["bound"] = result["selected"] and result["content_read"]
        result["source_verified"] = result["imported"] and result["bound"] and result["selected"] and result["content_read"]
        result["behavior_followed"] = result["source_verified"] and result["behavior_followed"]
    except (ValueError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
        result["source_verified"] = False
        result["behavior_followed"] = False
    result["outcome"] = "source-verified" if result["source_verified"] else "source-unverified"
    return result


def lifecycle_gate(rows: list[dict[str, Any]], *, live: bool = True) -> dict[str, Any]:
    missing = []
    from sweep.models import MATRIX
    for _, profile, _ in MATRIX:
        normal = [r for r in rows if r.get("model_profile") == profile and r.get("variant") == "normal"]
        absent = [r for r in rows if r.get("model_profile") == profile and r.get("variant") == "absent"]
        if (len(normal) != 1 or not all(normal[0].get(k) is True for k in
                                      ("imported", "bound", "selected", "content_read", "behavior_followed"))
                or normal[0].get("target_error") or normal[0].get("guard_error")
                or (live and (normal[0].get("environment") != "live"
                              or normal[0].get("target_context") != "global-general"
                              or normal[0].get("session_type") != "general"
                              or normal[0].get("catalogue_private") is not True
                              or normal[0].get("selection_intent") is not True))):
            missing.append(profile + ":normal-lifecycle")
        if (len(absent) != 1 or absent[0].get("unexpected_skill_selected") is not False
                or absent[0].get("behavior_present") is not False
                or absent[0].get("other_skill_read_violation") is True
                or absent[0].get("target_error") or absent[0].get("guard_error")
                or (absent and absent[0].get("target_context") == "global-general"
                    and absent[0].get("fallback_followed") is not True)
                or (live and (absent[0].get("environment") != "live"
                              or absent[0].get("target_context") != "global-general"
                              or absent[0].get("session_type") != "general"))):
            missing.append(profile + ":absent-control")
    return {"status": "blocked-prerequisite" if missing else "ready", "missing": missing,
            "evidence_scope": "live" if live else "offline-contract-only"}


def absence_audit(case: dict[str, Any], refs: list[dict[str, Any]], oracle_ref: dict[str, Any], root: Path) -> dict[str, Any]:
    result = {k: case.get(k) for k in ("run_id", "suite_id", "risk_id", "case_id", "variant", "model_profile")}
    result.update(environment=None, upstream_session_id=case["session_id"], unexpected_skill_selected=None,
                  behavior_present=None, errors=[])
    result["target_context"] = case.get("target_context", "historical-unspecified")
    result["session_type"] = "general" if case["session_id"].startswith("chat:") else "workspace"
    try:
        oracle = read_ref(root, oracle_ref)
        if oracle.get("scope_id") != case["scope_id"] or oracle.get("derived_from") != "skill-and-controlled-source":
            raise ValueError("absence behavior oracle is not tied to its controlled source")
        events = [read_ref(root, ref) for ref in refs]
        if not events or any(e.get("session_id") != case["session_id"] or e.get("scope_id") != case["scope_id"] for e in events):
            raise ValueError("absence event identity missing")
        identities = {(e.get("request_id"), e.get("local_turn_id"), e.get("environment")) for e in events}
        if len(identities) != 1 or not all(next(iter(identities))):
            raise ValueError("absence evidence spans different/unknown turns")
        terminal = [e for e in events if e.get("kind") == "terminal" and e.get("status") == "completed" and e.get("history_complete") is True]
        outputs = [e for e in events if e.get("kind") == "assistant-output"]
        if len(terminal) != 1 or len(outputs) != 1:
            raise ValueError("complete absence history/output required")
        result["environment"] = next(iter(identities))[2]
        result["request_id"], result["local_turn_id"] = next(iter(identities))[:2]
        skill_events = [e for e in events if e.get("kind") in {"skill-selected", "skill-content-read"}]
        if case.get("target_context") == "global-general":
            forbidden = oracle.get("forbidden_skills")
            if not isinstance(forbidden, list) or not forbidden or any(
                    not isinstance(s, dict) or not s.get("skill_id") or not s.get("skill_hash") for s in forbidden):
                raise ValueError("specified-carrier absence requires pinned forbidden Skill identities")
            if any(not e.get("skill_id") or not e.get("tool_call_id") for e in skill_events):
                raise ValueError("unidentified Skill adoption cannot prove absence")
            def matches(e):
                return any(e.get("skill_id") == s["skill_id"] or (
                    e.get("kind") == "skill-content-read" and text_hash(e.get("content", "")) == s["skill_hash"])
                    for s in forbidden)
            result["unexpected_skill_selected"] = any(matches(e) for e in skill_events)
            result["other_skill_events"] = [
                {"kind": e.get("kind"), "skill_id": e.get("skill_id"), "tool_call_id": e.get("tool_call_id")}
                for e in skill_events if not matches(e)]
            result["other_skill_read_violation"] = (bool(result["other_skill_events"])
                                                     if oracle.get("require_no_other_skill_reads") is True else None)
            result["fallback_followed"] = behavior_matches({"format": "json-object", "expected_json": oracle.get("fallback_json"),
                                                          "allow_code_fence": oracle.get("allow_code_fence") is True},
                                                          outputs[0].get("content", ""))
        else:
            result["unexpected_skill_selected"] = bool(skill_events)
        result["behavior_present"] = behavior_matches(oracle, outputs[0].get("content", ""))
        markers = oracle.get("forbidden_output_markers", [])
        if not isinstance(markers, list) or any(not isinstance(m, str) or len(m) < 8 for m in markers):
            raise ValueError("invalid Skill-specific absence output markers")
        result["skill_specific_output_present"] = any(m in outputs[0].get("content", "") for m in markers)
        result["behavior_present"] = result["behavior_present"] or result["skill_specific_output_present"]
    except (ValueError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def verified_lifecycle_rows(root: Path, suite: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild levels from referenced bytes; a saved boolean does not unlock gate."""
    from .evidence import read_rows
    from .schema import validate_isolation
    cases = read_rows(root / "case-registry.jsonl")
    validate_isolation(cases, suite)
    skills = read_rows(root / "skill-registry.jsonl")
    audits = read_rows(root / "skill-source-audit.jsonl")
    results = []
    for case in cases:
        key = (case["case_id"], case["model_profile"], case["variant"])
        matching = [r for r in audits if tuple(r.get(k) for k in ("case_id", "model_profile", "variant")) == key]
        if len(matching) != 1:
            continue
        row = matching[0]
        if case["variant"] == "normal":
            matching_skills = [r for r in skills if r.get("skill_id") == case["skill_id"]]
            if len(matching_skills) != 1:
                continue
            rebuilt = source_audit(case, matching_skills[0], row.get("evidence_refs", []), root)
        elif case["variant"] == "absent":
            if suite["schema_version"] == 2:
                from .registry import validate_absent_locator
                controls = [r for r in read_rows(root / "absence-registry.jsonl") if r.get("case_id") == case["case_id"]]
                if len(controls) != 1:
                    continue
                validate_absent_locator(controls[0], root, case, live=True)
            rebuilt = absence_audit(case, row.get("evidence_refs", []), row.get("behavior_oracle", {}), root)
        else:
            continue
        # Runtime errors cannot be erased by valid source evidence.
        rebuilt.update({k: row.get(k) for k in ("target_error", "guard_error")})
        results.append(rebuilt)
    return results
