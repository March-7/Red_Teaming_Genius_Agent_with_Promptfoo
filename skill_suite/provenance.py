"""Asset lineage and use limits. An asset label is never Genius ground truth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from sweep.runtime import sha256_file
from .campaign import exact, nonempty
from .evidence import local_file, read_ref
from .schema import identifier

MATERIALS = {"skill-artifact", "research-seed", "trajectory", "scanner-template", "mock"}
USES = {"runtime-skill", "generation-seed", "reference-only", "offline-fixture"}


def file_set(root: Path, refs: Any) -> dict[str, str]:
    if not isinstance(refs, list) or not refs:
        raise ValueError("nonempty asset files required")
    result = {}
    for ref in refs:
        exact(ref, {"file", "sha256"}, "asset file reference")
        if not isinstance(ref["file"], str) or ".." in Path(ref["file"]).parts:
            raise ValueError("asset path aliases are forbidden")
        path = local_file(root, ref["file"])
        if path.stat().st_size == 0 or sha256_file(path) != ref["sha256"]:
            raise ValueError("asset file missing, empty or changed")
        if ref["file"] in result: raise ValueError("duplicate asset file")
        result[ref["file"]] = ref["sha256"]
    return result


def validate_asset(record: Any, root: Path, *, runtime: bool = False) -> dict[str, Any]:
    exact(record, {"schema_version", "kind", "asset_id", "origin", "material_kind", "intended_use",
                   "files", "adaptation", "genius_ground_truth"}, "asset provenance")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1 or record["kind"] != "skill-asset-provenance":
        raise ValueError("unsupported asset provenance")
    identifier(record["asset_id"], "asset id")
    if record["material_kind"] not in MATERIALS or record["intended_use"] not in USES:
        raise ValueError("unknown asset role")
    if record["genius_ground_truth"] is not False:
        raise ValueError("asset metadata cannot assert Genius ground truth")
    origin = exact(record["origin"], {"kind", "author", "source_format", "source_locator", "commit",
                                      "license_status", "license_note", "authoring_note"}, "asset origin")
    for field in ("author", "source_format", "license_note", "authoring_note"): nonempty(origin[field], field)
    if origin["kind"] == "local-original":
        if origin["source_locator"] is not None or origin["commit"] is not None or origin["license_status"] != "project-original":
            raise ValueError("local original may not invent upstream source or license")
    elif origin["kind"] == "external":
        if not isinstance(origin["commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", origin["commit"]):
            raise ValueError("external source requires pinned commit")
        url = urlsplit(nonempty(origin["source_locator"], "external source locator"))
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment
                or origin["commit"] not in url.path):
            raise ValueError("external source must identify the pinned commit without credentials")
        if origin["license_status"] not in {"confirmed", "unverified"}:
            raise ValueError("external license observation missing")
        if origin["license_status"] == "unverified" and record["intended_use"] not in {"reference-only", "offline-fixture"}:
            raise ValueError("unknown license blocks use of optional external material")
    else:
        raise ValueError("unsupported origin; generation provenance must be linked by the generation pipeline")
    files = file_set(root, record["files"])
    adaptation = record["adaptation"]
    if adaptation is None:
        runtime_files = files if record["material_kind"] == "skill-artifact" else {}
    else:
        exact(adaptation, {"method", "input_hashes", "output_files", "notes"}, "asset adaptation")
        identifier(adaptation["method"], "adaptation method"); nonempty(adaptation["notes"], "adaptation difference")
        if adaptation["input_hashes"] != sorted(files.values()): raise ValueError("adaptation input hash drift")
        runtime_files = file_set(root, adaptation["output_files"])
        if set(runtime_files.values()) & set(files.values()): raise ValueError("adapted output must differ from original research material")
    if record["material_kind"] == "mock" and record["intended_use"] != "offline-fixture":
        raise ValueError("mock assets are fixture-only")
    if record["intended_use"] == "runtime-skill" and not runtime_files:
        raise ValueError("research material needs explicit Skill adaptation before runtime use")
    if runtime and (record["intended_use"] != "runtime-skill" or record["material_kind"] == "mock" or not runtime_files):
        raise ValueError("asset is not a runtime Skill")
    return {"asset_id": record["asset_id"], "origin": origin["kind"], "material_kind": record["material_kind"],
            "intended_use": record["intended_use"], "original_files": files, "runtime_files": runtime_files,
            "genius_ground_truth": False}


def validate_runtime_asset(root: Path, row: dict[str, Any]) -> dict[str, Any] | None:
    ref = row.get("provenance_ref")
    if ref is None:
        if row.get("environment") == "live": raise ValueError("live Skill requires asset provenance")
        return None
    record = read_ref(root, ref)
    result = validate_asset(record, local_file(root, ref["file"]).parent, runtime=True)
    artifact = local_file(root, row["artifact_file"])
    if sha256_file(artifact) != row["asset_hash"] or row["asset_hash"] not in result["runtime_files"].values():
        raise ValueError("imported source is not a pinned runtime asset")
    return result


def validate_index(path: Path) -> dict[str, Any]:
    index = json.loads(path.read_text()); root = path.resolve().parent
    exact(index, {"schema_version", "kind", "assets"}, "asset index")
    if type(index["schema_version"]) is not int or index["schema_version"] != 1 or index["kind"] != "skill-asset-index":
        raise ValueError("unsupported asset index")
    if not isinstance(index["assets"], list) or not index["assets"]: raise ValueError("asset index empty")
    results = [validate_asset(read_ref(root, ref), local_file(root, ref["file"]).parent) for ref in index["assets"]]
    if len({row["asset_id"] for row in results}) != len(results): raise ValueError("duplicate provenance asset id")
    return {"offline": True, "kind": "skill-asset-index-validation", "asset_count": len(results), "assets": results,
            "genius_ground_truth": False, "actual_calls": {"target": 0, "generation": 0, "judge": 0}}


def snapshot_asset(root: Path, ref: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Copy lineage into a new local directory; never mutate original assets."""
    exact(ref, {"file", "sha256"}, "provenance reference")
    if not isinstance(ref["file"], str) or ".." in Path(ref["file"]).parts:
        raise ValueError("provenance path aliases are forbidden")
    manifest = local_file(root, ref["file"]); bundle_root = manifest.parent
    record = read_ref(root, ref); result = validate_asset(record, bundle_root)
    copied_ref = {"file": manifest.name, "sha256": ref["sha256"]}
    files = {**result["original_files"], **result["runtime_files"], manifest.name: ref["sha256"]}
    if destination.exists() or destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("provenance snapshot must be new and outside original assets")
    destination.mkdir(parents=True, exist_ok=False)
    for name, expected in files.items():
        target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle: handle.write(local_file(bundle_root, name).read_bytes())
        if sha256_file(target) != expected: raise ValueError("asset changed during snapshot")
    validate_asset(read_ref(destination, copied_ref), destination)
    return copied_ref


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--index", type=Path, required=True)
    args = parser.parse_args(argv); print(json.dumps(validate_index(args.index), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
