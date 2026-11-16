"""Evidence-gated risk cards for benchmark-derived Genius Skill pilots."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from sweep.runtime import sha256_file
from .benchmark_registry import validate_registry
from .schema import identifier


STATUSES = {"verified", "partial", "blocked", "unavailable"}
DISPOSITIONS = {"eligible-for-pilot", "blocked-prerequisite", "not-applicable",
                "calibration-only"}
REUSE_TIERS = {"direct-reuse", "minimal-adaptation", "pattern-only", "not-applicable"}
GATE_FIELDS = {"license_clear", "capability_reachable", "material_harm_boundary",
               "normal_control", "positive_control", "independent_oracle_and_recovery",
               "coverage_increment"}
HASH64 = re.compile(r"^[a-f0-9]{64}$")


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} required")
    return value


def _local_ref(root: Path, ref: Any, label: str) -> Path:
    _exact(ref, {"file", "sha256"}, label)
    if (not isinstance(ref["file"], str) or ".." in Path(ref["file"]).parts
            or not HASH64.fullmatch(str(ref["sha256"]))):
        raise ValueError(f"{label} invalid")
    path = (root / ref["file"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256_file(path) != ref["sha256"]:
        raise ValueError(f"{label} missing or changed")
    return path


def validate_capabilities(path: Path, project_root: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    _exact(data, {"schema_version", "kind", "target_context", "checked_at", "capabilities"},
           "capability registry")
    if (data["schema_version"] != 1 or data["kind"] != "genius-capability-registry"
            or data["target_context"] != "global-general"
            or not isinstance(data["capabilities"], list) or not data["capabilities"]):
        raise ValueError("unsupported capability registry")
    seen = set()
    for row in data["capabilities"]:
        _exact(row, {"capability_id", "status", "evidence_refs", "limits"}, "capability")
        identifier(row["capability_id"], "capability id")
        if row["capability_id"] in seen or row["status"] not in STATUSES:
            raise ValueError("duplicate capability or unknown status")
        seen.add(row["capability_id"])
        if not isinstance(row["evidence_refs"], list):
            raise ValueError("capability evidence refs must be a list")
        for ref in row["evidence_refs"]:
            _local_ref(project_root, ref, "capability evidence")
        _text(row["limits"], "capability limits")
        if row["status"] == "verified" and not row["evidence_refs"]:
            raise ValueError("verified capability requires evidence")
    return data


def _control(value: Any, label: str) -> dict[str, Any]:
    row = _exact(value, {"task", "expected_behavior", "evidence_required"}, label)
    for field in row:
        _text(row[field], f"{label} {field}")
    return row


def validate_card(path: Path, capability_path: Path, source_registry_path: Path,
                  relationship_summary_path: Path, project_root: Path) -> dict[str, Any]:
    capabilities = validate_capabilities(capability_path, project_root)
    capability_by_id = {row["capability_id"]: row for row in capabilities["capabilities"]}
    sources = {row["source_id"]: row
               for row in validate_registry(source_registry_path)["sources"]}
    relationship_summary = json.loads(relationship_summary_path.read_text())
    relationships = {row["source_id"]: row for row in relationship_summary["relationships"]}
    card = json.loads(path.read_text())
    _exact(card, {"schema_version", "kind", "card_id", "risk_family", "evaluation_stage",
        "protected_asset", "legitimate_task", "trust_boundary", "attack_behavior",
        "material_harm", "required_capabilities", "capability_evidence", "controls",
        "independent_oracle", "recovery", "sources", "coverage_increment", "model_role",
        "gates", "disposition", "exclusion_reason", "review"}, "risk card")
    if (card["schema_version"] != 1 or card["kind"] != "genius-skill-risk-card"
            or card["evaluation_stage"] != "pre-pilot"):
        raise ValueError("unsupported risk card")
    identifier(card["card_id"], "card id")
    identifier(card["risk_family"], "risk family")
    protected = _exact(card["protected_asset"], {"kind", "description", "synthetic_only"},
                       "protected asset")
    _text(protected["kind"], "protected asset kind")
    _text(protected["description"], "protected asset description")
    if protected["synthetic_only"] is not True:
        raise ValueError("risk card may use synthetic protected assets only")
    legitimate = _exact(card["legitimate_task"], {"summary", "user_boundary", "task_family"},
                        "legitimate task")
    boundary = _exact(card["trust_boundary"], {"request_boundary", "principal_scope",
                                                "excluded_claims"}, "trust boundary")
    attack = _exact(card["attack_behavior"], {"action", "skill_carrier", "success_condition"},
                    "attack behavior")
    for label, row in (("legitimate task", legitimate), ("trust boundary", boundary),
                       ("attack behavior", attack)):
        for field, value in row.items():
            if field == "excluded_claims":
                if not isinstance(value, list) or not value:
                    raise ValueError("excluded claims required")
            else:
                _text(value, f"{label} {field}")
    harm = _exact(card["material_harm"], {"severity", "impact", "calibration_only"},
                  "material harm")
    if harm["severity"] not in {"low", "medium", "high"}:
        raise ValueError("material harm severity invalid")
    _text(harm["impact"], "material harm impact")
    if not isinstance(card["required_capabilities"], list) or not card["required_capabilities"]:
        raise ValueError("required capabilities missing")
    if len(set(card["required_capabilities"])) != len(card["required_capabilities"]):
        raise ValueError("duplicate required capability")
    evidence = {}
    for row in card["capability_evidence"]:
        _exact(row, {"capability_id", "use", "pilot_positive_control_required"},
               "capability mapping")
        capability_id = row["capability_id"]
        if capability_id in evidence or capability_id not in capability_by_id:
            raise ValueError("unknown or duplicate capability mapping")
        _text(row["use"], "capability use")
        if not isinstance(row["pilot_positive_control_required"], bool):
            raise ValueError("capability positive control flag required")
        evidence[capability_id] = capability_by_id[capability_id]
    if set(evidence) != set(card["required_capabilities"]):
        raise ValueError("required capability mapping incomplete")
    controls = _exact(card["controls"], {"normal", "positive"}, "controls")
    _control(controls["normal"], "normal control")
    _control(controls["positive"], "positive control")
    oracle = _exact(card["independent_oracle"], {"signal", "control_plane", "target_independent",
                                                  "before_after"}, "independent oracle")
    _text(oracle["signal"], "oracle signal")
    _text(oracle["control_plane"], "oracle control plane")
    if oracle["target_independent"] is not True or not isinstance(oracle["before_after"], bool):
        raise ValueError("oracle must be target independent")
    recovery = _exact(card["recovery"], {"procedure", "verified_api", "run_owned_only"},
                      "recovery")
    _text(recovery["procedure"], "recovery procedure")
    if recovery["run_owned_only"] is not True or not isinstance(recovery["verified_api"], bool):
        raise ValueError("recovery contract invalid")
    if not isinstance(card["sources"], list) or not card["sources"]:
        raise ValueError("risk card source links required")
    for row in card["sources"]:
        _exact(row, {"source_id", "relationship_ref", "upstream_label", "reuse_tier"},
               "risk source")
        source = sources.get(row["source_id"])
        relation = relationships.get(row["source_id"])
        if source is None or relation is None or row["reuse_tier"] not in REUSE_TIERS:
            raise ValueError("risk source mapping invalid")
        relationship_path = relationship_summary_path.parent / row["relationship_ref"]["file"]
        if (row["relationship_ref"] != {"file": relation["file"], "sha256": relation["sha256"]}
                or sha256_file(relationship_path) != relation["sha256"]):
            raise ValueError("risk relationship hash drift")
        _text(row["upstream_label"], "upstream label")
        if source["content_reuse_ceiling"] == "metadata-only" and row["reuse_tier"] != "not-applicable":
            raise ValueError("metadata-only source cannot generate a risk case")
    coverage = _exact(card["coverage_increment"], {"dimension", "distinct_from"},
                      "coverage increment")
    _text(coverage["dimension"], "coverage dimension")
    if not isinstance(coverage["distinct_from"], list):
        raise ValueError("coverage comparison list required")
    model = _exact(card["model_role"], {"proposed_by", "evidence_reviewed_by",
                                        "model_decides"}, "model role")
    if model["model_decides"] is not False or model["evidence_reviewed_by"] != "codex-evidence-review":
        raise ValueError("model cannot decide risk eligibility")
    gates = _exact(card["gates"], GATE_FIELDS, "risk gates")
    if any(not isinstance(value, bool) for value in gates.values()):
        raise ValueError("risk gates must be boolean")
    review = _exact(card["review"], {"reviewer", "reviewed_at", "decision", "reason"},
                    "risk review")
    if review["reviewer"] != "codex-evidence-review" or review["decision"] not in DISPOSITIONS:
        raise ValueError("risk review invalid")
    _text(review["reason"], "review reason")
    disposition = card["disposition"]
    if disposition not in DISPOSITIONS or disposition != review["decision"]:
        raise ValueError("risk disposition/review mismatch")
    all_gates = all(gates.values())
    statuses = {capability["status"] for capability in evidence.values()}
    if disposition == "eligible-for-pilot":
        if (not all_gates or harm["severity"] == "low" or harm["calibration_only"] is not False
                or "unavailable" in statuses or "blocked" in statuses
                or card["exclusion_reason"] is not None):
            raise ValueError("eligible risk does not pass every hard gate")
    else:
        if disposition == "calibration-only" and harm["calibration_only"] is not True:
            raise ValueError("calibration disposition requires calibration harm flag")
        if not isinstance(card["exclusion_reason"], str) or not card["exclusion_reason"]:
            raise ValueError("ineligible risk requires exclusion reason")
    return {"valid": True, "card_id": card["card_id"], "risk_family": card["risk_family"],
            "disposition": disposition, "source_ids": sorted({row["source_id"] for row in card["sources"]}),
            "capability_statuses": sorted(statuses), "all_gates": all_gates,
            "model_decides": False}


def validate_index(index_path: Path, capability_path: Path, source_registry_path: Path,
                   relationship_summary_path: Path, project_root: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text())
    _exact(index, {"schema_version", "kind", "cards"}, "risk card index")
    if index["schema_version"] != 1 or index["kind"] != "genius-skill-risk-card-index":
        raise ValueError("unsupported risk card index")
    results = []
    for ref in index["cards"]:
        path = _local_ref(index_path.parent, ref, "risk card ref")
        results.append(validate_card(path, capability_path, source_registry_path,
                                     relationship_summary_path, project_root))
    if len({row["card_id"] for row in results}) != len(results):
        raise ValueError("duplicate risk card id")
    if len({row["risk_family"] for row in results}) != len(results):
        raise ValueError("duplicate risk family")
    counts = Counter(row["disposition"] for row in results)
    return {"valid": True, "card_count": len(results), "dispositions": dict(sorted(counts.items())),
            "eligible_cards": [row["card_id"] for row in results
                               if row["disposition"] == "eligible-for-pilot"],
            "model_decides": False}


def validate_shortlist(shortlist_path: Path, index_path: Path, capability_path: Path,
                       source_registry_path: Path, relationship_summary_path: Path,
                       project_root: Path) -> dict[str, Any]:
    result = validate_index(index_path, capability_path, source_registry_path,
                            relationship_summary_path, project_root)
    shortlist = json.loads(shortlist_path.read_text())
    _exact(shortlist, {"schema_version", "kind", "standing_authorization",
        "selected_for_pilot", "excluded", "calibration", "selection_rule",
        "model_decides"}, "risk shortlist")
    if (shortlist["schema_version"] != 1 or shortlist["kind"] != "genius-skill-risk-shortlist"
            or shortlist["standing_authorization"] != {
                "max_candidate_risk_families": 10, "target": 96, "management": 1200,
                "recovery": 120, "cleanup": 180, "generation": 0, "judge": 0,
                "retry": 0}
            or shortlist["model_decides"] is not False):
        raise ValueError("shortlist authorization or model boundary drift")
    index = json.loads(index_path.read_text())
    cards = {}
    for ref in index["cards"]:
        card = json.loads((index_path.parent / ref["file"]).read_text())
        cards[card["card_id"]] = (card, ref)
    selected_ids = []
    sources = set()
    for row in shortlist["selected_for_pilot"]:
        _exact(row, {"card_id", "risk_family", "card_ref", "source_ids"},
               "selected risk")
        if row["card_id"] not in cards:
            raise ValueError("selected risk card missing")
        card, ref = cards[row["card_id"]]
        expected_sources = sorted({item["source_id"] for item in card["sources"]
                                   if item["reuse_tier"] != "not-applicable"})
        if (card["disposition"] != "eligible-for-pilot"
                or row["risk_family"] != card["risk_family"]
                or row["card_ref"] != ref or row["source_ids"] != expected_sources):
            raise ValueError("selected risk does not match its evidence-reviewed card")
        selected_ids.append(row["card_id"])
        sources.update(expected_sources)
    if (selected_ids != result["eligible_cards"] or len(selected_ids) > 10
            or len(sources) < 3):
        raise ValueError("shortlist count or public-source coverage invalid")
    for row in shortlist["excluded"] + shortlist["calibration"]:
        _exact(row, {"card_id", "risk_family", "disposition", "reason", "card_ref"},
               "excluded or calibration risk")
        if row["card_id"] not in cards:
            raise ValueError("excluded risk card missing")
        card, ref = cards[row["card_id"]]
        if (row["risk_family"] != card["risk_family"]
                or row["disposition"] != card["disposition"]
                or row["reason"] != card["exclusion_reason"] or row["card_ref"] != ref):
            raise ValueError("excluded risk does not match its evidence-reviewed card")
    excluded_ids = {row["card_id"] for row in shortlist["excluded"]}
    calibration_ids = {row["card_id"] for row in shortlist["calibration"]}
    expected_excluded = {card_id for card_id, (card, _) in cards.items()
                         if card["disposition"] in {"blocked-prerequisite", "not-applicable"}}
    expected_calibration = {card_id for card_id, (card, _) in cards.items()
                            if card["disposition"] == "calibration-only"}
    if excluded_ids != expected_excluded or calibration_ids != expected_calibration:
        raise ValueError("shortlist exclusions or calibration set incomplete")
    return {"valid": True, "selected_count": len(selected_ids),
            "selected_cards": selected_ids, "source_ids": sorted(sources),
            "excluded_count": len(excluded_ids), "calibration_count": len(calibration_ids),
            "model_decides": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--relationships", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--shortlist", type=Path)
    args = parser.parse_args(argv)
    if args.shortlist:
        result = validate_shortlist(args.shortlist, args.index, args.capabilities,
            args.sources, args.relationships, args.project_root)
    else:
        result = validate_index(args.index, args.capabilities, args.sources,
                                args.relationships, args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
