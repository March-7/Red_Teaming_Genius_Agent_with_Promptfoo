"""Controlled same-principal, cross-session fixtures for cross-session-leak.

This module never treats two session identifiers as two authenticated users.  It
records transport isolation separately from authorization evidence so a
same-account memory recall cannot silently become a cross-user finding.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import yaml


PAIR_REGISTRY_NAME = "cross-session-pairs.jsonl"
SESSION_REGISTRY_NAME = "cross-session-sessions.jsonl"
AUDIT_NAME = "cross-session-source-audit.jsonl"
GENERATION_AUDIT_NAME = "generation-audit.json"
RAW_GENERATED_NAME = "generated.raw.yaml"
PROBE_PROTOCOL = "cross-session-probe/v1"
PROBE_MAX_AGE_HOURS = 24


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "attestation_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain JSON objects")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def seal_probe_attestation(value: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(value)
    sealed["attestation_sha256"] = _canonical_hash(sealed)
    return sealed


def validate_probe_attestation(
    path: Path | None,
    *,
    now: dt.datetime | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a live probe attestation without accepting a CLI label alone."""
    if path is None:
        return None, ["cross-session live probe attestation is required"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"invalid cross-session probe attestation: {exc}"]
    if not isinstance(value, dict):
        return None, ["cross-session probe attestation must be a JSON object"]
    errors: list[str] = []
    expected = {
        "protocol": PROBE_PROTOCOL,
        "plugin_id": "cross-session-leak",
        "backend": "genius-live",
        "credential_scope": "same-authenticated-principal",
        "native_session_ids_distinct": True,
        "positive_recall_exact": True,
        "source_audit_complete": True,
        "target_calls": 3,
        "generation_calls": 0,
        "llm_judge_calls": 0,
    }
    for key, required in expected.items():
        if value.get(key) != required:
            errors.append(f"probe field {key} must equal {required!r}")
    if value.get("lifecycle_policy") not in {"retain", "cleanup"}:
        errors.append("probe lifecycle_policy must be retain or cleanup")
    if value.get("lifecycle_verified") is not True:
        errors.append("probe lifecycle must be verified")
    source_id = str(value.get("source_upstream_session_id") or "")
    attack_id = str(value.get("attack_upstream_session_id") or "")
    if not source_id or not attack_id or source_id == attack_id:
        errors.append("probe must record two distinct native upstream session ids")
    if value.get("attestation_sha256") != _canonical_hash(value):
        errors.append("probe attestation hash mismatch")
    created_at = value.get("created_at")
    try:
        created = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        current = now or dt.datetime.now(dt.timezone.utc)
        age = current - created.astimezone(dt.timezone.utc)
        if age.total_seconds() < 0 or age > dt.timedelta(hours=PROBE_MAX_AGE_HOURS):
            errors.append("probe attestation is expired or dated in the future")
    except (TypeError, ValueError):
        errors.append("probe created_at must be an ISO-8601 timestamp")
    return value, errors


def _prompt_text(test: dict[str, Any]) -> str:
    value = (test.get("vars") or {}).get("prompt")
    return value if isinstance(value, str) else ""


def _match_value(test: dict[str, Any]) -> str:
    metadata = test.get("metadata") or {}
    value = metadata.get("crossSessionLeakMatch")
    return value if isinstance(value, str) else ""


def _has_cross_session_assertion(test: dict[str, Any]) -> bool:
    assertions = test.get("assert")
    return isinstance(assertions, list) and any(
        isinstance(item, dict)
        and item.get("type") == "promptfoo:redteam:cross-session-leak"
        for item in assertions
    )


def normalize_generated_pairs(
    generated_path: Path,
    run_dir: Path,
    expected_pairs: int,
    *,
    source_registry: Path | None = None,
    source_raw: Path | None = None,
) -> list[dict[str, Any]]:
    """Normalize Promptfoo's two-turn pairs into attack-only formal tests."""
    document = yaml.safe_load(generated_path.read_text(encoding="utf-8"))
    tests = document.get("tests") if isinstance(document, dict) else None
    if not isinstance(tests, list):
        raise ValueError("cross-session generated file must contain tests")

    raw_path = run_dir / RAW_GENERATED_NAME
    registry_path = run_dir / PAIR_REGISTRY_NAME
    audit_path = run_dir / GENERATION_AUDIT_NAME
    source_mode = "raw-pairs"
    pairs: list[dict[str, Any]] = []
    normalized_tests: list[dict[str, Any]] = []

    if len(tests) == expected_pairs * 2:
        raw_path.write_bytes(generated_path.read_bytes())
        seen_matches: set[str] = set()
        for pair_offset in range(expected_pairs):
            source = tests[pair_offset * 2]
            attack = tests[pair_offset * 2 + 1]
            if not isinstance(source, dict) or not isinstance(attack, dict):
                raise ValueError("cross-session pair turns must be YAML objects")
            source_prompt = _prompt_text(source)
            attack_prompt = _prompt_text(attack)
            match = _match_value(attack).strip()
            if source.get("assert"):
                raise ValueError("cross-session source turn must not contain assertions")
            if not _has_cross_session_assertion(attack):
                raise ValueError("cross-session attack turn is missing its deterministic assertion")
            if not source_prompt or not attack_prompt or not match:
                raise ValueError("cross-session pair is missing source, attack, or match")
            folded = match.casefold()
            if folded in seen_matches:
                raise ValueError("cross-session match values must be unique")
            if folded not in source_prompt.casefold():
                raise ValueError("cross-session match must originate in the source turn")
            if folded in attack_prompt.casefold():
                raise ValueError("cross-session attack input must not contain the match value")
            seen_matches.add(folded)
            pair_index = pair_offset + 1
            pair_id = f"cross-session:{pair_index}"
            pairs.append(
                {
                    "schema_version": 1,
                    "kind": "cross_session_pair",
                    "pair_id": pair_id,
                    "pair_index": pair_index,
                    "source_prompt": source_prompt,
                    "attack_prompt": attack_prompt,
                    "match": match,
                    "source_prompt_sha256": _sha256_text(source_prompt),
                    "attack_prompt_sha256": _sha256_text(attack_prompt),
                    "match_sha256": _sha256_text(match),
                    "source_test_index": pair_offset * 2,
                    "attack_test_index": pair_offset * 2 + 1,
                }
            )
            normalized = copy.deepcopy(attack)
            normalized.setdefault("vars", {})["cross_session_pair_index"] = pair_index
            normalized.setdefault("metadata", {})["crossSessionPairIndex"] = pair_index
            normalized_tests.append(normalized)
    elif len(tests) == expected_pairs:
        source_mode = "reviewed-normalized"
        if source_registry is None or not source_registry.is_file():
            raise ValueError(
                "reviewed cross-session attacks require sibling cross-session-pairs.jsonl"
            )
        pairs = read_jsonl(source_registry)
        if len(pairs) != expected_pairs:
            raise ValueError("cross-session source registry pair count mismatch")
        if source_raw is None or not source_raw.is_file():
            raise ValueError("reviewed cross-session attacks require sibling generated.raw.yaml")
        raw_path.write_bytes(source_raw.read_bytes())
        by_index = {int(row.get("pair_index", 0)): dict(row) for row in pairs}
        normalized_tests = []
        for fallback_index, attack in enumerate(tests, start=1):
            if not isinstance(attack, dict) or not _has_cross_session_assertion(attack):
                raise ValueError("reviewed cross-session attack is malformed")
            metadata = attack.get("metadata") or {}
            pair_index = int(metadata.get("crossSessionPairIndex", fallback_index))
            pair = by_index.get(pair_index)
            if pair is None:
                raise ValueError("reviewed cross-session attack has no source pair")
            attack_prompt = _prompt_text(attack)
            match = _match_value(attack).strip()
            if not attack_prompt or match != pair.get("match"):
                raise ValueError("reviewed cross-session attack changed its pair match")
            if match.casefold() in attack_prompt.casefold():
                raise ValueError("reviewed cross-session attack contains its match")
            pair["attack_prompt"] = attack_prompt
            pair["attack_prompt_sha256"] = _sha256_text(attack_prompt)
            normalized = copy.deepcopy(attack)
            normalized.setdefault("vars", {})["cross_session_pair_index"] = pair_index
            normalized.setdefault("metadata", {})["crossSessionPairIndex"] = pair_index
            normalized_tests.append(normalized)
        pairs = [by_index[index] for index in sorted(by_index)]
    else:
        raise ValueError(
            f"cross-session generation requires {expected_pairs} pairs "
            f"({expected_pairs * 2} raw turns), got {len(tests)} tests"
        )

    document["tests"] = normalized_tests
    generated_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    write_jsonl(registry_path, pairs)
    audit = {
        "schema_version": 1,
        "plugin_id": "cross-session-leak",
        "source_mode": source_mode,
        "raw_test_count": expected_pairs * 2,
        "pair_count": len(pairs),
        "formal_attack_count_per_target": len(normalized_tests),
        "raw_generated_file": RAW_GENERATED_NAME,
        "normalized_generated_file": generated_path.name,
        "pair_registry_file": PAIR_REGISTRY_NAME,
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "normalized_sha256": hashlib.sha256(generated_path.read_bytes()).hexdigest(),
        "pair_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
    }
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pairs


def capture_source_audit(
    session_registry_path: Path,
    *,
    service_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Correlate source-only canaries with persisted A/B session messages."""
    from dataclasses import replace
    from dotenv import load_dotenv
    from shim.genius_service import GeniusService, ShimConfig

    rows = read_jsonl(session_registry_path)
    if service_factory is None:
        load_dotenv(override=False)
        service_factory = lambda: GeniusService(
            replace(ShimConfig.from_env(), trace_jsonl_path="", lifecycle_jsonl_path="")
        )
    service = service_factory()
    audits: list[dict[str, Any]] = []
    try:
        for row in rows:
            match = str(row.get("match") or "")
            source_messages = service.persisted_session_messages(
                str(row.get("source_upstream_session_id") or "")
            )
            attack_messages = service.persisted_session_messages(
                str(row.get("attack_upstream_session_id") or "")
            )
            source_text = json.dumps(source_messages, ensure_ascii=False)
            attack_user_text = json.dumps(
                [item for item in attack_messages if item.get("role") == "user"],
                ensure_ascii=False,
            )
            source_has_match = bool(match) and match.casefold() in source_text.casefold()
            attack_input_has_match = bool(match) and match.casefold() in attack_user_text.casefold()
            audits.append(
                {
                    "schema_version": 1,
                    "kind": "cross_session_source_audit",
                    "fixture_id": row.get("fixture_id"),
                    "pair_index": row.get("pair_index"),
                    "target_label": row.get("target_label"),
                    "source_upstream_session_id": row.get("source_upstream_session_id"),
                    "attack_upstream_session_id": row.get("attack_upstream_session_id"),
                    "source_messages_sha256": _sha256_text(source_text),
                    "attack_user_messages_sha256": _sha256_text(attack_user_text),
                    "source_contains_match": source_has_match,
                    "attack_input_contains_match": attack_input_has_match,
                    "source_correlation_verified": source_has_match and not attack_input_has_match,
                }
            )
    finally:
        service.close()
    write_jsonl(session_registry_path.parent / AUDIT_NAME, audits)
    return audits


def apply_session_lifecycle(
    session_registry_path: Path,
    policy: str,
    *,
    service_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Retain or delete only session ids recorded by this run's registry."""
    if policy not in {"retain", "cleanup"}:
        raise ValueError("cross-session lifecycle must be retain or cleanup")
    rows = read_jsonl(session_registry_path)
    if policy == "retain":
        for row in rows:
            row["lifecycle_policy"] = "retain"
            row["lifecycle_status"] = "retained-by-user-request"
            row["lifecycle_verified"] = True
        write_jsonl(session_registry_path, rows)
        return rows

    from dataclasses import replace
    from dotenv import load_dotenv
    from shim.genius_service import GeniusService, ShimConfig

    if service_factory is None:
        load_dotenv(override=False)
        service_factory = lambda: GeniusService(
            replace(ShimConfig.from_env(), trace_jsonl_path="", lifecycle_jsonl_path="")
        )
    session_ids = sorted(
        {
            str(row.get(key))
            for row in rows
            for key in ("source_upstream_session_id", "attack_upstream_session_id")
            if row.get(key)
        }
    )
    service = service_factory()
    try:
        status, _ = service.batch_delete_sessions(session_ids)
        remaining = service.list_session_ids()
    finally:
        service.close()
    verified = status < 400 and not set(session_ids).intersection(remaining)
    for row in rows:
        row["lifecycle_policy"] = "cleanup"
        row["lifecycle_status"] = "verified" if verified else "failed"
        row["lifecycle_verified"] = verified
    write_jsonl(session_registry_path, rows)
    return rows
