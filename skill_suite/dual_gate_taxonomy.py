"""Validate the source-complete taxonomy and offline A/B screening artifacts."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from sweep.runtime import sha256_file
from .benchmark_registry import SOURCE_IDS, validate_inventory


EXPECTED_RAW_COUNTS = {
    "aig-skilljack": 4,
    "skill-inject": 84,
    "malskillbench": 28,
    "skillsbench": 63,
    "malicious-agent-skills": 14,
    "skillleakbench": 10,
    "skillfortifybench": 13,
    "oasb": 9,
    "agent-skill-security": 3,
    "scr-bench": 3,
    "skilllifebench": 22,
    "harmfulskillbench": 21,
}
SUCCESS = {"observed-success", "no-observed-success", "no-valid-prior-run"}
TESTABILITY = {"source-faithful-testable", "blocked-prerequisite",
               "not-applicable", "separate-policy-track"}
FAMILY = re.compile(r"^[a-z][a-z0-9-]{2,95}$")


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


def validate_catalogue(root: Path, catalogue_path: Path, registry_path: Path,
                       inventory_path: Path, inventory_summary_path: Path) -> dict[str, Any]:
    validate_inventory(registry_path, inventory_path, inventory_summary_path)
    value = json.loads(catalogue_path.read_text())
    _exact(value, {"schema_version", "kind", "source_registry_ref",
        "source_inventory_ref", "source_count", "raw_entry_count",
        "taxonomy_cell_count", "sources", "scripts_executed",
        "external_payloads_executed", "genius_calls"}, "source category catalogue")
    if (value["schema_version"] != 1
            or value["kind"] != "genius-skill-source-category-catalogue"
            or value["source_count"] != len(SOURCE_IDS)
            or value["raw_entry_count"] != sum(EXPECTED_RAW_COUNTS.values())
            or value["taxonomy_cell_count"] != 108
            or value["scripts_executed"] != 0
            or value["external_payloads_executed"] != 0
            or value["genius_calls"] != 0):
        raise ValueError("source category catalogue boundary drift")
    if _ref(root, value["source_registry_ref"], "catalogue registry ref") != registry_path.resolve():
        raise ValueError("catalogue registry identity drift")
    if _ref(root, value["source_inventory_ref"], "catalogue inventory ref") != inventory_path.resolve():
        raise ValueError("catalogue inventory identity drift")
    sources = value["sources"]
    if (not isinstance(sources, list)
            or {row.get("source_id") for row in sources} != SOURCE_IDS):
        raise ValueError("catalogue source set drift")
    raw_keys: set[str] = set()
    family_links: dict[str, set[str]] = {}
    counts = {}
    cells = 0
    for source in sources:
        _exact(source, {"source_id", "raw_entry_count", "entries",
            "taxonomy_cells", "evidence_boundaries"}, "catalogue source")
        sid = source["source_id"]
        entries = source["entries"]
        if source["raw_entry_count"] != len(entries):
            raise ValueError("catalogue source count drift")
        counts[sid] = len(entries)
        cells += len(source["taxonomy_cells"])
        if not isinstance(source["evidence_boundaries"], list):
            raise ValueError("source evidence boundaries required")
        for entry in entries:
            _exact(entry, {"source_id", "raw_key", "axis", "raw_id", "label",
                "description", "evidence_path", "risk_semantics", "family_ids"},
                "raw category entry")
            key = entry["raw_key"]
            if (entry["source_id"] != sid or not isinstance(key, str)
                    or key in raw_keys or not entry["label"] or not entry["axis"]
                    or not isinstance(entry["risk_semantics"], bool)
                    or not isinstance(entry["family_ids"], list)
                    or any(not FAMILY.fullmatch(str(fid)) for fid in entry["family_ids"])):
                raise ValueError("raw category entry invalid")
            if entry["risk_semantics"] and not entry["family_ids"]:
                raise ValueError("risk category silently unmapped")
            raw_keys.add(key)
            for family_id in entry["family_ids"]:
                family_links.setdefault(family_id, set()).add(key)
    if counts != EXPECTED_RAW_COUNTS or cells != 108 or len(raw_keys) != value["raw_entry_count"]:
        raise ValueError("source category coverage drift")
    return {"valid": True, "raw_keys": raw_keys, "family_links": family_links,
            "raw_entry_count": len(raw_keys), "source_count": len(sources),
            "taxonomy_cell_count": cells}


def validate_family_map(root: Path, path: Path, catalogue_path: Path,
                        catalogue: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    _exact(value, {"schema_version", "kind", "catalogue_ref", "families",
        "unmapped_review", "raw_entry_count", "mapped_risk_entry_count"},
        "risk family map")
    if (value["schema_version"] != 1 or value["kind"] != "genius-skill-risk-family-map"
            or _ref(root, value["catalogue_ref"], "family catalogue ref") != catalogue_path.resolve()
            or value["raw_entry_count"] != catalogue["raw_entry_count"]
            or value["unmapped_review"] != []):
        raise ValueError("risk family map boundary drift")
    families = value["families"]
    ids = set()
    linked = set()
    for row in families:
        _exact(row, {"family_id", "label", "source_raw_keys", "source_ids",
            "impact", "carriers", "material_harm", "notes"}, "risk family")
        family_id = row["family_id"]
        if (not FAMILY.fullmatch(str(family_id)) or family_id in ids
                or row["material_harm"] not in {"low", "medium", "high"}
                or not row["source_raw_keys"] or not row["source_ids"]
                or not row["carriers"]):
            raise ValueError("risk family invalid")
        if not set(row["source_raw_keys"]) <= catalogue["raw_keys"]:
            raise ValueError("risk family references unknown raw category")
        ids.add(family_id)
        linked.update(row["source_raw_keys"])
        if set(row["source_raw_keys"]) != catalogue["family_links"].get(family_id, set()):
            raise ValueError("raw-to-family reverse mapping drift")
    risk_keys = set().union(*catalogue["family_links"].values()) if catalogue["family_links"] else set()
    if linked != risk_keys or value["mapped_risk_entry_count"] != len(risk_keys):
        raise ValueError("risk family map is not lossless")
    return {"valid": True, "family_ids": ids, "families": families,
            "family_count": len(ids), "mapped_risk_entry_count": len(linked)}


def validate_screening(root: Path, path: Path, family_map_path: Path,
                       family_map: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    _exact(value, {"schema_version", "kind", "family_map_ref", "historical_refs",
        "families", "quadrants", "counts", "new_online_calls",
        "formal_execution_enabled"}, "dual gate screening")
    if (value["schema_version"] != 1 or value["kind"] != "genius-skill-dual-gate-screening"
            or _ref(root, value["family_map_ref"], "screening family map ref") != family_map_path.resolve()
            or value["new_online_calls"] != {"target": 0, "generation": 0, "judge": 0}
            or value["formal_execution_enabled"] is not False):
        raise ValueError("dual gate screening boundary drift")
    for ref in value["historical_refs"]:
        _ref(root, ref, "historical screening ref")
    rows = value["families"]
    if {row.get("family_id") for row in rows} != family_map["family_ids"]:
        raise ValueError("screening family coverage drift")
    quadrants = {"a_and_b": [], "a_only": [], "b_only": [], "neither": []}
    for row in rows:
        _exact(row, {"family_id", "success_evidence", "success_evidence_refs",
            "success_reason", "source_testability", "testability_reason",
            "capability_basis", "success_oracle", "impact_limit",
            "residual_disposition", "material_harm", "fidelity_status"},
            "dual gate family")
        if (row["success_evidence"] not in SUCCESS
                or row["source_testability"] not in TESTABILITY
                or row["material_harm"] not in {"low", "medium", "high"}
                or row["fidelity_status"] not in {"source-faithful", "adaptation-drift",
                                                    "not-assessed"}):
            raise ValueError("dual gate family disposition invalid")
        for ref in row["success_evidence_refs"]:
            _ref(root, ref, "success evidence ref")
        if row["success_evidence"] == "observed-success" and not row["success_evidence_refs"]:
            raise ValueError("observed success requires immutable evidence")
        a = row["success_evidence"] == "observed-success"
        b = row["source_testability"] == "source-faithful-testable"
        quadrants["a_and_b" if a and b else "a_only" if a else "b_only" if b else "neither"].append(row["family_id"])
    canonical = {key: sorted(values) for key, values in quadrants.items()}
    if value["quadrants"] != canonical:
        raise ValueError("dual gate quadrant drift")
    counts = {"family_count": len(rows), "observed_success": len(canonical["a_and_b"]) + len(canonical["a_only"]),
        "source_faithful_testable": len(canonical["a_and_b"]) + len(canonical["b_only"]),
        **{key: len(values) for key, values in canonical.items()}}
    if value["counts"] != counts:
        raise ValueError("dual gate counts drift")
    return {"valid": True, "rows": rows, "quadrants": canonical, "counts": counts,
            "testable_ids": set(canonical["a_and_b"] + canonical["b_only"]),
            "observed_ids": set(canonical["a_and_b"] + canonical["a_only"])}


def validate_trajectories(root: Path, path: Path, screening_path: Path,
                          screening: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    _exact(value, {"schema_version", "kind", "screening_ref", "trajectories",
        "trajectory_count", "executable_payloads", "new_online_calls"},
        "trajectory index")
    if (value["schema_version"] != 1 or value["kind"] != "genius-skill-dual-gate-trajectories"
            or _ref(root, value["screening_ref"], "trajectory screening ref") != screening_path.resolve()
            or value["executable_payloads"] != 0
            or value["new_online_calls"] != {"target": 0, "generation": 0, "judge": 0}):
        raise ValueError("trajectory index boundary drift")
    expected = screening["testable_ids"] | screening["observed_ids"]
    rows = value["trajectories"]
    if value["trajectory_count"] != len(rows) or {row.get("family_id") for row in rows} != expected:
        raise ValueError("trajectory coverage drift")
    for row in rows:
        _exact(row, {"family_id", "source_raw_key", "upstream_chain",
            "genius_adaptation_path", "oracle", "fidelity_delta", "impact_limit",
            "residual_disposition", "success_evidence", "source_testability",
            "missing_evidence", "executable_payload"}, "trajectory")
        _exact(row["upstream_chain"], {"carrier", "trigger", "action", "sink", "effect"},
               "upstream trajectory")
        if (row["executable_payload"] is not False or not row["source_raw_key"]
                or not row["genius_adaptation_path"] or not row["oracle"]):
            raise ValueError("trajectory is not a safe review example")
    return {"valid": True, "trajectory_count": len(rows),
            "executable_payloads": 0, "new_online_calls": value["new_online_calls"]}


def validate_all(root: Path, base: Path) -> dict[str, Any]:
    registry = base / "source-registry.json"
    inventory = base / "source-inventory.jsonl"
    inventory_summary = base / "source-inventory-summary.json"
    catalogue_path = base / "source-category-catalogue.json"
    family_path = base / "risk-family-map.json"
    screening_path = base / "dual-gate-screening.json"
    trajectories_path = base / "dual-gate-trajectories.json"
    catalogue = validate_catalogue(root, catalogue_path, registry, inventory, inventory_summary)
    family_map = validate_family_map(root, family_path, catalogue_path, catalogue)
    screening = validate_screening(root, screening_path, family_path, family_map)
    trajectories = validate_trajectories(root, trajectories_path, screening_path, screening)
    return {"valid": True, "source_count": catalogue["source_count"],
        "raw_entry_count": catalogue["raw_entry_count"],
        "taxonomy_cell_count": catalogue["taxonomy_cell_count"],
        "family_count": family_map["family_count"], "counts": screening["counts"],
        "trajectory_count": trajectories["trajectory_count"],
        "new_online_calls": trajectories["new_online_calls"]}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(validate_all(args.root.resolve(), args.base.resolve()),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
