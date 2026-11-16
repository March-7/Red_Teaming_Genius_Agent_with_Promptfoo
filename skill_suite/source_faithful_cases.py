"""Validate the 23 offline source-faithful case blueprints."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from sweep.resource_naming import validate_neutral_resource_name, validate_neutral_user_question
from sweep.runtime import sha256_file


FORBIDDEN_VISIBLE = re.compile(
    r"\b(?:test|mock|synthetic|demo|canary|attack|malware|evaluation|probe)\b",
    re.IGNORECASE,
)
MODELS = [{"model_profile": "default", "reasoning_effort": "high", "thinking": "on"},
          {"model_profile": "deepseek-v4.1-flash", "reasoning_effort": "high",
           "thinking": "on"}]
CASE_STATUSES = {"offline-reviewed-awaiting-user", "user-approved"}
REVIEW_STATUSES = {"pending", "approved"}


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _ref(root: Path, value: Any, label: str) -> Path:
    _exact(value, {"file", "sha256"}, label)
    path = (root / value["file"]).resolve()
    if (not path.is_relative_to(root.resolve()) or not path.is_file()
            or sha256_file(path) != value["sha256"]):
        raise ValueError(f"{label} missing or changed")
    return path


def validate_case(path: Path, selection: dict[str, Any], raw_keys: set[str]) -> dict[str, Any]:
    case = json.loads(path.read_text())
    _exact(case, {"schema_version", "kind", "case_id", "family_id", "status",
        "source_anchor", "source_chain", "genius_case", "oracle", "impact",
        "residual", "review", "target_calls", "generation_calls", "judge_calls"},
        "source-faithful case")
    if (case["schema_version"] != 1 or case["kind"] != "genius-source-faithful-case-blueprint"
            or case["status"] not in CASE_STATUSES
            or case["family_id"] not in selection["selected_family_ids"]
            or case["case_id"] != "source-faithful-" + case["family_id"] + "-01"
            or any(case[key] != 0 for key in ("target_calls", "generation_calls", "judge_calls"))):
        raise ValueError("source-faithful case identity or online boundary drift")
    anchor = _exact(case["source_anchor"], {"raw_key", "source_id", "label", "axis",
        "evidence_path", "reuse_tier"}, "case source anchor")
    if anchor["raw_key"] not in raw_keys or not anchor["source_id"]:
        raise ValueError("case source anchor is not in the complete catalogue")
    chain = _exact(case["source_chain"], {"carrier", "trigger", "action", "sink", "effect"},
                   "case source chain")
    if any(not isinstance(value, str) or not value.strip() for value in chain.values()):
        raise ValueError("complete source chain required")
    genius = _exact(case["genius_case"], {"title_zh", "skill_name_template", "carrier",
        "activation", "language", "user_task", "skill_behavior", "resource_templates",
        "model_matrix", "payload_status"}, "Genius case blueprint")
    rendered_name = genius["skill_name_template"].replace("{nonce}", "a124b5c6")
    validate_neutral_resource_name(rendered_name, "case Skill name")
    if (FORBIDDEN_VISIBLE.search(rendered_name) or FORBIDDEN_VISIBLE.search(genius["user_task"])
            or genius["language"] != "upstream-language"
            or genius["model_matrix"] != MODELS
            or genius["payload_status"] != "blueprint-no-executable-payload"
            or genius["carrier"] not in {"text-skill", "package-script", "package-asset",
                                          "catalogue-selection"}
            or genius["activation"] not in {"explicit-exact-skill-name",
                                              "natural-task-selection"}):
        raise ValueError("case naming, language, carrier, or payload boundary drift")
    if case["family_id"] == "skill-impersonation":
        if genius["activation"] != "natural-task-selection":
            raise ValueError("Skill impersonation requires natural selection")
    elif genius["activation"] != "explicit-exact-skill-name":
        raise ValueError("non-selection risks require exact Skill activation")
    validate_neutral_user_question(genius["user_task"])
    resources = genius["resource_templates"]
    if not isinstance(resources, list):
        raise ValueError("resource templates must be a list")
    for resource in resources:
        _exact(resource, {"kind", "name_template", "ownership", "disposition"}, "case resource")
        validate_neutral_resource_name(resource["name_template"].replace("{nonce}", "a124b5c6"))
        if resource["ownership"] != "run-owned-disposable" or resource["disposition"] not in {
                "deleted", "destroyed-owned-resource", "retained-quarantined", "restored",
                "no-persistent-effect"}:
            raise ValueError("case resource ownership or disposition drift")
    oracle = _exact(case["oracle"], {"kind", "success_condition", "evidence_required",
        "invalid_or_unresolved"}, "case oracle")
    if any(not isinstance(value, str) or not value.strip() for value in oracle.values()):
        raise ValueError("case oracle required")
    impact = _exact(case["impact"], {"severity", "real_world_analogue", "bounded_effect",
        "disposable_only"}, "case impact")
    if impact["severity"] not in {"medium", "high"} or impact["disposable_only"] is not True:
        raise ValueError("case must retain material but bounded harm")
    residual = _exact(case["residual"], {"allowed_dispositions", "active_processes_allowed",
        "cross_run_effect_allowed"}, "case residual")
    if (not residual["allowed_dispositions"] or residual["active_processes_allowed"] is not False
            or residual["cross_run_effect_allowed"] is not False):
        raise ValueError("case residual is not contained")
    review = _exact(case["review"], {"reviewer", "decision", "user_review",
        "source_fidelity", "distinct_from"}, "case review")
    if (review["reviewer"] != "codex-evidence-review" or review["decision"] != "accepted"
            or review["user_review"] not in REVIEW_STATUSES
            or review["source_fidelity"] != "carrier-trigger-action-sink-effect-preserved"):
        raise ValueError("case review boundary drift")
    return {"valid": True, "case_id": case["case_id"], "family_id": case["family_id"],
            "carrier": genius["carrier"], "source_id": anchor["source_id"]}


HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
METADATA_ONLY_SOURCES = {"skill-inject", "skilllifebench", "agent-skill-security"}


def validate_anchor_evidence(path: Path, results: list[dict[str, Any]],
                              inventory: dict[tuple[str, str], tuple[str, int]],
                              registry: dict[str, dict[str, Any]]) -> None:
    doc = json.loads(path.read_text())
    _exact(doc, {"schema_version", "kind", "status", "created_at",
        "verification_method", "anchors", "unavailable", "skilllifebench_anchor",
        "findings", "genius_calls"}, "source anchor evidence")
    if (doc["schema_version"] != 1
            or doc["kind"] != "genius-source-faithful-anchor-evidence"
            or doc["status"] != "verified-22-of-23"
            or doc["genius_calls"] != {"target": 0, "generation": 0, "judge": 0}
            or not isinstance(doc["anchors"], list) or len(doc["anchors"]) != 22
            or doc["unavailable"] != []
            or not isinstance(doc["skilllifebench_anchor"], dict)):
        raise ValueError("source anchor evidence boundary drift")
    mirror = _exact(doc["skilllifebench_anchor"], {
        "case_id", "family_id", "raw_key", "status", "official_attempt",
        "mirror_fetch", "cross_check", "note"},
        "skilllifebench mirror corroboration")
    if (mirror["case_id"] != "source-faithful-unsafe-skill-code-01"
            or mirror["status"] != "mirror-corroborated-official-unreachable"
            or "third-party" not in json.dumps(mirror, ensure_ascii=False)):
        raise ValueError("skilllifebench corroboration boundary drift")
    seen: set[str] = set()
    for anchor in doc["anchors"]:
        _exact(anchor, {"case_id", "family_id", "raw_key", "source_id", "reuse_ceiling",
            "fetch", "inventory_check", "upstream_anchor", "notes"}, "anchor evidence entry")
        if (anchor["case_id"] in seen
                or anchor["case_id"] != "source-faithful-" + anchor["family_id"] + "-01"):
            raise ValueError("duplicate or malformed anchor case id")
        seen.add(anchor["case_id"])
        fetch = _exact(anchor["fetch"], {"url", "pinned_commit", "path", "content_sha256",
            "fetched_at", "method"}, "anchor fetch")
        commit = registry[anchor["source_id"]]["pinned_commit"]
        if (fetch["pinned_commit"] != commit or commit not in fetch["url"]
                or fetch["path"] not in fetch["url"]
                or not HEX64.fullmatch(fetch["content_sha256"])
                or "read-only HTTPS fetch" not in fetch["method"]):
            raise ValueError("anchor fetch is not pinned to the registered revision")
        check = _exact(anchor["inventory_check"], {"path", "stored_hash",
            "stored_hash_kind", "size_bytes", "match"}, "anchor inventory check")
        stored = inventory.get((anchor["source_id"], check["path"]))
        if (stored is None or stored[0] != check["stored_hash"]
                or check["match"] is not True
                or check["stored_hash_kind"] not in {"sha256", "git-blob-sha1"}
                or not (HEX64.fullmatch(check["stored_hash"])
                        if check["stored_hash_kind"] == "sha256"
                        else HEX40.fullmatch(check["stored_hash"]))):
            raise ValueError("anchor inventory hash mismatch or malformed")
        if anchor["reuse_ceiling"] != registry[anchor["source_id"]]["content_reuse_ceiling"]:
            raise ValueError("anchor reuse ceiling drift")
        upstream = anchor["upstream_anchor"]
        if anchor["source_id"] in METADATA_ONLY_SOURCES:
            _exact(upstream, {"kind", "summary", "verbatim"}, "anchor upstream")
            if upstream["kind"] != "scenario-metadata" or upstream["verbatim"] is not False:
                raise ValueError("metadata-only source must not carry verbatim quotes")
        else:
            _exact(upstream, {"kind", "quote", "verbatim"}, "anchor upstream")
            if upstream["kind"] != "taxonomy-definition" or upstream["verbatim"] is not True:
                raise ValueError("non-metadata source must carry a verbatim quote")
    expected = {row["case_id"] for row in results}
    if seen | {doc["skilllifebench_anchor"]["case_id"]} != expected:
        raise ValueError("anchor evidence does not cover the 23 approved cases")


def _load_inventory(path: Path) -> dict[tuple[str, str], tuple[str, int]]:
    inventory: dict[tuple[str, str], tuple[str, int]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        inventory[(row["source_id"], row["path"])] = (row["content_hash"],
                                                      row["size_bytes"])
    return inventory


def validate_index(root: Path, base: Path) -> dict[str, Any]:
    index_path = base / "source-faithful-cases-v1/index.json"
    index = json.loads(index_path.read_text())
    _exact(index, {"schema_version", "kind", "status", "selection_ref", "catalogue_ref",
        "anchor_evidence_ref", "oracle_contracts_ref", "adaptation_manifests_ref",
        "distinction_predicates_ref", "case_count", "family_count", "cases",
        "carrier_counts", "language", "normal_cases", "positive_cases",
        "target_calls", "generation_calls", "judge_calls",
        "user_review_status", "user_decision_ref"},
        "source-faithful case index")
    selection_path = _ref(root, index["selection_ref"], "case selection ref")
    catalogue_path = _ref(root, index["catalogue_ref"], "case catalogue ref")
    anchor_path = _ref(index_path.parent, index["anchor_evidence_ref"],
                       "source anchor evidence ref")
    selection = json.loads(selection_path.read_text())
    catalogue = json.loads(catalogue_path.read_text())
    raw_keys = {entry["raw_key"] for source in catalogue["sources"] for entry in source["entries"]}
    if (index["schema_version"] != 1 or index["kind"] != "genius-source-faithful-case-index"
            or index["status"] not in CASE_STATUSES
            or index["case_count"] != 23 or index["family_count"] != 23
            or index["normal_cases"] != 0 or index["positive_cases"] != 0
            or index["target_calls"] != 0 or index["generation_calls"] != 0
            or index["judge_calls"] != 0 or index["language"] != "upstream-language"
            or index["user_review_status"] not in REVIEW_STATUSES
            or not isinstance(index["user_decision_ref"], str)
            or not index["user_decision_ref"].strip()):
        raise ValueError("source-faithful index boundary drift")
    results = []
    for ref in index["cases"]:
        _exact(ref, {"family_id", "case_id", "file", "sha256"}, "case ref")
        path = _ref(index_path.parent, {"file": ref["file"], "sha256": ref["sha256"]},
                    "case ref")
        result = validate_case(path, selection, raw_keys)
        if result["family_id"] != ref["family_id"] or result["case_id"] != ref["case_id"]:
            raise ValueError("case ref identity drift")
        results.append(result)
    if ({row["family_id"] for row in results} != set(selection["selected_family_ids"])
            or len({row["case_id"] for row in results}) != 23
            or index["carrier_counts"] != dict(sorted(__import__("collections").Counter(
                row["carrier"] for row in results).items()))):
        raise ValueError("case coverage or carrier counts drift")
    inventory = _load_inventory(base / "source-inventory.jsonl")
    registry_doc = json.loads((base / "source-registry.json").read_text())
    registry = {row["source_id"]: row for row in registry_doc["sources"]}
    validate_anchor_evidence(anchor_path, results, inventory, registry)
    return {"valid": True, "case_count": 23, "family_count": 23,
        "carrier_counts": index["carrier_counts"], "target_calls": 0,
        "generation_calls": 0, "judge_calls": 0,
        "user_review_status": index["user_review_status"]}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(validate_index(args.root.resolve(), args.base.resolve()),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
