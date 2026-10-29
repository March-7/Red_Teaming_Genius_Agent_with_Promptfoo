"""Validate source-bound benchmark adaptations before a Genius case exists."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from sweep.runtime import sha256_file
from .benchmark_registry import validate_inventory
from .schema import identifier


REUSE_TIERS = {"direct-reuse", "minimal-adaptation", "pattern-only", "not-applicable"}
CEILING = {
    "direct-reuse": {"direct-reuse", "minimal-adaptation", "pattern-only", "not-applicable"},
    "minimal-adaptation": {"minimal-adaptation", "pattern-only", "not-applicable"},
    "pattern-only": {"pattern-only", "not-applicable"},
    "metadata-only": {"not-applicable"},
}
HASH40 = re.compile(r"^[a-f0-9]{40}$")
HASH64 = re.compile(r"^[a-f0-9]{64}$")


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _asset_lookup(inventory_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = [json.loads(line) for line in inventory_path.read_text().splitlines() if line]
    return {(row["source_id"], row["path"]): row for row in rows}


def validate_manifest(path: Path, registry_path: Path, inventory_path: Path,
                      summary_path: Path) -> dict[str, Any]:
    validate_inventory(registry_path, inventory_path, summary_path)
    registry = json.loads(registry_path.read_text())
    sources = {row["source_id"]: row for row in registry["sources"]}
    inventory = _asset_lookup(inventory_path)
    manifest = json.loads(path.read_text())
    _exact(manifest, {"schema_version", "kind", "adaptation_id", "source_id",
        "source_assets", "reuse_tier", "license_disposition", "source_content_copied",
        "field_differences", "adapted_files", "genius_case_generated", "applicability",
        "upstream_claim_only", "genius_finding"}, "adaptation manifest")
    if manifest["schema_version"] != 1 or manifest["kind"] != "skill-benchmark-adaptation":
        raise ValueError("unsupported adaptation manifest")
    identifier(manifest["adaptation_id"], "adaptation id")
    source = sources.get(manifest["source_id"])
    if source is None or manifest["license_disposition"] != source["license_disposition"]:
        raise ValueError("source or license disposition drift")
    tier = manifest["reuse_tier"]
    if tier not in REUSE_TIERS or tier not in CEILING[source["content_reuse_ceiling"]]:
        raise ValueError("reuse tier exceeds the audited source ceiling")
    if (manifest["upstream_claim_only"] is not True or manifest["genius_finding"] is not None
            or manifest["applicability"] not in {"candidate", "blocked", "not-applicable"}):
        raise ValueError("adaptation cannot assert a Genius finding")
    if not isinstance(manifest["source_assets"], list) or not manifest["source_assets"]:
        raise ValueError("source assets required")
    source_hashes = set()
    for ref in manifest["source_assets"]:
        _exact(ref, {"path", "hash_algorithm", "content_hash"}, "source asset reference")
        row = inventory.get((manifest["source_id"], ref["path"]))
        if row is None or any(ref[key] != row[key]
                              for key in ("hash_algorithm", "content_hash")):
            raise ValueError("source asset missing or hash drift")
        source_hashes.add((ref["hash_algorithm"], ref["content_hash"]))
    differences = manifest["field_differences"]
    if not isinstance(differences, list):
        raise ValueError("field differences must be a list")
    for difference in differences:
        _exact(difference, {"field", "before_hash", "after_hash", "reason"},
               "field difference")
        if (not isinstance(difference["field"], str) or not difference["field"]
                or not isinstance(difference["reason"], str) or not difference["reason"]
                or (difference["before_hash"] is not None
                    and not (HASH40.fullmatch(str(difference["before_hash"]))
                             or HASH64.fullmatch(str(difference["before_hash"]))))
                or (difference["after_hash"] is not None
                    and not HASH64.fullmatch(str(difference["after_hash"])))):
            raise ValueError("field difference hashes invalid")
    output_hashes = set()
    if not isinstance(manifest["adapted_files"], list):
        raise ValueError("adapted files must be a list")
    for ref in manifest["adapted_files"]:
        _exact(ref, {"file", "sha256", "role", "authorship"}, "adapted file")
        if (not isinstance(ref["file"], str) or ".." in Path(ref["file"]).parts
                or ref["authorship"] not in {"source-copy", "adapted", "local-original"}):
            raise ValueError("adapted file metadata invalid")
        target = (path.parent / ref["file"]).resolve()
        if not target.is_relative_to(path.parent.resolve()) or not target.is_file():
            raise ValueError("adapted file missing")
        if not HASH64.fullmatch(str(ref["sha256"])) or sha256_file(target) != ref["sha256"]:
            raise ValueError("adapted file hash drift")
        output_hashes.add(ref["sha256"])
    if tier == "direct-reuse":
        if (manifest["source_content_copied"] is not True or differences
                or len(manifest["source_assets"]) != 1 or len(manifest["adapted_files"]) != 1
                or manifest["adapted_files"][0]["authorship"] != "source-copy"
                or ("sha256", manifest["adapted_files"][0]["sha256"]) not in source_hashes):
            raise ValueError("direct reuse must preserve one SHA-256 source byte-for-byte")
    elif tier == "minimal-adaptation":
        if (manifest["source_content_copied"] is not True or not differences
                or not manifest["adapted_files"]
                or any(ref["authorship"] != "adapted" for ref in manifest["adapted_files"])
                or not any(diff["after_hash"] in output_hashes for diff in differences)):
            raise ValueError("minimal adaptation requires explicit changed fields and output hashes")
    elif tier == "pattern-only":
        if (manifest["source_content_copied"] is not False or not differences
                or any(ref["authorship"] != "local-original" for ref in manifest["adapted_files"])
                or not manifest["adapted_files"]):
            raise ValueError("pattern-only cases must be locally authored without source copying")
    else:
        if (manifest["source_content_copied"] is not False or differences
                or manifest["adapted_files"] or manifest["genius_case_generated"] is not False
                or manifest["applicability"] == "candidate"):
            raise ValueError("not-applicable assets cannot generate a Genius case")
    if tier != "not-applicable" and (manifest["genius_case_generated"] is not True
                                      or manifest["applicability"] != "candidate"):
        raise ValueError("applicable adaptation must produce one candidate case")
    return {"valid": True, "adaptation_id": manifest["adaptation_id"],
            "source_id": manifest["source_id"], "reuse_tier": tier,
            "source_asset_count": len(manifest["source_assets"]),
            "adapted_file_count": len(manifest["adapted_files"]),
            "genius_ground_truth": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_manifest(args.manifest, args.registry, args.inventory, args.summary)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
