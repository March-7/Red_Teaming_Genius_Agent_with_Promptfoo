"""Pinned, metadata-only inventory for public Skill benchmark sources.

This module reads files as bytes and hashes them. It never imports or executes
code from a benchmark checkout, expands archives, or treats upstream labels as
Genius findings.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit

from sweep.runtime import sha256_file, write_json


SOURCE_IDS = {"aig-skilljack", "skill-inject", "malskillbench", "skillsbench",
    "malicious-agent-skills", "skillleakbench", "skillfortifybench", "oasb",
    "agent-skill-security", "scr-bench", "skilllifebench", "harmfulskillbench"}
REUSE_TIERS = {"direct-reuse", "minimal-adaptation", "pattern-only", "metadata-only"}
LICENSE_DISPOSITIONS = {
    "confirmed-open", "research-only", "academic-research-only", "ambiguous-attribution"
}
HASH40 = re.compile(r"^[a-f0-9]{40}$")
REVISION = re.compile(r"^[a-f0-9]{7,40}$")
HASH64 = re.compile(r"^[a-f0-9]{64}$")
ARCHIVES = {".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z"}
EXECUTABLE_SUFFIXES = {".py", ".sh", ".js", ".mjs", ".cjs", ".ps1"}


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _pinned_url(value: Any, commit: str) -> str:
    if not isinstance(value, str):
        raise ValueError("pinned source URL required")
    parsed = urlsplit(value)
    allowed_host = parsed.hostname == "github.com" or (
        parsed.hostname == "huggingface.co" and parsed.path.startswith("/datasets/"))
    if (parsed.scheme != "https" or not allowed_host
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or commit not in parsed.path):
        raise ValueError("source URL must name the pinned public revision")
    return value


def validate_registry(path: Path) -> dict[str, Any]:
    registry = json.loads(path.read_text())
    _exact(registry, {"schema_version", "kind", "checked_at", "sources"}, "source registry")
    if (registry["schema_version"] != 1
            or registry["kind"] != "skill-benchmark-source-registry"
            or not isinstance(registry["checked_at"], str)):
        raise ValueError("unsupported source registry")
    if not isinstance(registry["sources"], list) or len(registry["sources"]) != len(SOURCE_IDS):
        raise ValueError("complete benchmark source set required")
    seen = set()
    for source in registry["sources"]:
        _exact(source, {"source_id", "repository_url", "pinned_commit", "pinned_ref",
            "pinned_url", "tree_hash", "root_license", "license_expression",
            "license_observation", "license_disposition", "content_reuse_ceiling",
            "third_party_note", "relevant_roots", "upstream_claims"}, "source")
        source_id = source["source_id"]
        if source_id not in SOURCE_IDS or source_id in seen:
            raise ValueError("unknown or duplicate source id")
        seen.add(source_id)
        commit = source["pinned_commit"]
        if not isinstance(commit, str) or not REVISION.fullmatch(commit):
            raise ValueError("pinned commit required")
        _pinned_url(source["pinned_url"], commit)
        repository = urlsplit(source["repository_url"])
        repository_host_ok = repository.hostname == "github.com" or (
            repository.hostname == "huggingface.co"
            and repository.path.startswith("/datasets/"))
        if (repository.scheme != "https" or not repository_host_ok
                or repository.username or repository.password or repository.query
                or repository.fragment):
            raise ValueError("canonical public repository URL required")
        tree_hash = source["tree_hash"]
        if repository.hostname == "github.com" and not HASH40.fullmatch(str(tree_hash)):
            raise ValueError("pinned tree hash required")
        if repository.hostname == "huggingface.co" and tree_hash is not None:
            raise ValueError("Hugging Face metadata source must not invent a Git tree hash")
        license_ref = _exact(source["root_license"], {"path", "sha256"}, "root license")
        license_missing = license_ref["path"] is None and license_ref["sha256"] is None
        license_present = (isinstance(license_ref["path"], str)
            and ".." not in Path(license_ref["path"]).parts
            and HASH64.fullmatch(str(license_ref["sha256"])))
        if not license_missing and not license_present:
            raise ValueError("root license reference invalid")
        disposition = source["license_disposition"]
        ceiling = source["content_reuse_ceiling"]
        if disposition not in LICENSE_DISPOSITIONS or ceiling not in REUSE_TIERS:
            raise ValueError("unknown license or reuse disposition")
        for field in ("pinned_ref", "license_expression", "license_observation",
                      "third_party_note"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ValueError(f"source {field} required")
        if license_missing and disposition == "confirmed-open":
            raise ValueError("missing root license cannot be confirmed open")
        if disposition == "ambiguous-attribution" and ceiling != "metadata-only":
            raise ValueError("ambiguous attribution permits metadata only")
        if disposition in {"research-only", "academic-research-only"} and ceiling not in {
                "pattern-only", "metadata-only"}:
            raise ValueError("restricted research source cannot be copied into runtime assets")
        if not isinstance(source["relevant_roots"], list) or not source["relevant_roots"]:
            raise ValueError("relevant source roots required")
        if any(not isinstance(item, str) or not item or ".." in Path(item).parts
               for item in source["relevant_roots"]):
            raise ValueError("unsafe relevant source root")
        if not isinstance(source["upstream_claims"], list) or not source["upstream_claims"]:
            raise ValueError("upstream claim records required")
        for claim in source["upstream_claims"]:
            _exact(claim, {"kind", "value", "evidence_path", "genius_ground_truth"},
                   "upstream claim")
            if claim["genius_ground_truth"] is not False:
                raise ValueError("upstream claim cannot be Genius ground truth")
    if seen != SOURCE_IDS:
        raise ValueError("benchmark source set incomplete")
    return registry


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=checkout, text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


def _asset_kind(source_id: str, relative: str) -> str:
    name = relative.lower()
    if name.endswith(("license", "license.md", "license.txt")) or "/license" in name:
        return "license"
    if name.endswith(("readme", "readme.md", "readme.txt")) or "/readme" in name:
        return "documentation"
    if source_id == "aig-skilljack":
        if "poisoned_trajectories" in name and name.endswith(".jsonl"):
            return "trajectory"
        if name.endswith("execution_verification.py"):
            return "mock-runtime"
        if name.endswith("security_analyzer.py"):
            return "verifier"
    if source_id == "skill-inject":
        if "contextual_injections" in name or "obvious_injections" in name:
            return "attack-catalogue"
        if name.endswith("data/tasks.json"):
            return "task-catalogue"
        if "/data/skills/" in "/" + name:
            return "skill"
        if "/data/task_files/" in "/" + name:
            return "task-file"
        if "/data/task_scripts/" in "/" + name:
            return "task-script"
        if "/judges/" in "/" + name:
            return "verifier"
        if name.endswith("unified_security_policy.md"):
            return "policy"
    if source_id == "malskillbench":
        if "/dataset/skills/malware/" in "/" + name:
            return "malicious-skill-package-file"
        if "/dataset/skills/benign/" in "/" + name:
            return "benign-skill-package-file"
        if "taxonomy" in name or "category" in name:
            return "taxonomy"
        if "verif" in name or "judge" in name:
            return "verifier"
    if source_id == "skillsbench":
        if name.endswith("task.md"):
            return "task"
        if "/skills/" in "/" + name:
            return "skill"
        if name.endswith(("test.sh", "test_outputs.py")) or "/verifier/" in "/" + name:
            return "verifier"
        if name.endswith("solve.sh") or "/oracle/" in "/" + name:
            return "oracle"
    if name.endswith((".json", ".jsonl", ".yaml", ".yml", ".toml")):
        return "metadata"
    if Path(name).suffix in EXECUTABLE_SUFFIXES:
        return "code"
    return "other"


def _tree_index_records(source: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    index = json.loads(path.read_text())
    _exact(index, {"schema_version", "kind", "source_id", "pinned_commit", "tree_hash",
                   "entries"}, "tree index")
    if (index["schema_version"] != 1 or index["kind"] != "git-tree-asset-index"
            or index["source_id"] != source["source_id"]
            or index["pinned_commit"] != source["pinned_commit"]
            or index["tree_hash"] != source["tree_hash"]):
        raise ValueError("tree index pin drift")
    selected = []
    for entry in index["entries"]:
        _exact(entry, {"path", "git_blob_sha1", "size_bytes"}, "tree entry")
        relative = entry["path"]
        if (not isinstance(relative, str) or not relative or ".." in Path(relative).parts
                or not HASH40.fullmatch(str(entry["git_blob_sha1"]))
                or not isinstance(entry["size_bytes"], int) or entry["size_bytes"] < 0):
            raise ValueError("tree entry invalid")
        if any(relative == root or relative.startswith(root.rstrip("/") + "/")
               for root in source["relevant_roots"]):
            selected.append({"path": relative, "hash_algorithm": "git-blob-sha1",
                             "content_hash": entry["git_blob_sha1"],
                             "size_bytes": entry["size_bytes"]})
    if not selected:
        raise ValueError("tree index contains no relevant assets")
    return selected


def build_inventory(registry_path: Path, checkouts: dict[str, Path],
                    inventory_path: Path, summary_path: Path,
                    tree_indexes: dict[str, Path] | None = None) -> dict[str, Any]:
    registry = validate_registry(registry_path)
    tree_indexes = tree_indexes or {}
    if set(checkouts) & set(tree_indexes) or set(checkouts) | set(tree_indexes) != SOURCE_IDS:
        raise ValueError("one checkout or tree index for every pinned source required")
    records: list[dict[str, Any]] = []
    source_summaries = []
    for source in sorted(registry["sources"], key=lambda row: row["source_id"]):
        source_id = source["source_id"]
        selected: list[dict[str, Any]] = []
        if source_id in checkouts:
            checkout = checkouts[source_id].resolve()
            if _git(checkout, "rev-parse", "HEAD") != source["pinned_commit"]:
                raise ValueError(f"{source_id} checkout commit drift")
            if _git(checkout, "rev-parse", "HEAD^{tree}") != source["tree_hash"]:
                raise ValueError(f"{source_id} checkout tree drift")
            files: dict[str, Path] = {}
            for item in source["relevant_roots"]:
                target = (checkout / item).resolve()
                if not target.is_relative_to(checkout) or not target.exists():
                    raise ValueError(f"{source_id} relevant root missing")
                candidates = [target] if target.is_file() else target.rglob("*")
                for candidate in candidates:
                    if candidate.is_symlink() or not candidate.is_file() or ".git" in candidate.parts:
                        continue
                    files[candidate.relative_to(checkout).as_posix()] = candidate
            selected = [{"path": relative, "hash_algorithm": "sha256",
                         "content_hash": sha256_file(file_path),
                         "size_bytes": file_path.stat().st_size}
                        for relative, file_path in sorted(files.items())]
        else:
            selected = _tree_index_records(source, tree_indexes[source_id])
        counts = Counter()
        bytes_total = 0
        algorithms = Counter()
        for item in sorted(selected, key=lambda row: row["path"]):
            relative = item["path"]
            kind = _asset_kind(source_id, relative)
            size = item["size_bytes"]
            record = {"schema_version": 1, "kind": "skill-benchmark-source-asset",
                "source_id": source_id, "path": relative,
                "hash_algorithm": item["hash_algorithm"], "content_hash": item["content_hash"],
                "size_bytes": size, "asset_kind": kind,
                "executable_content": Path(relative).suffix.lower() in EXECUTABLE_SUFFIXES,
                "archive_not_expanded": Path(relative).suffix.lower() in ARCHIVES,
                "content_stored": False, "genius_ground_truth": False}
            records.append(record)
            counts[kind] += 1
            algorithms[item["hash_algorithm"]] += 1
            bytes_total += size
        source_summaries.append({"source_id": source_id, "pinned_commit": source["pinned_commit"],
            "tree_hash": source["tree_hash"], "asset_count": len(selected),
            "bytes_hashed": bytes_total, "asset_kind_counts": dict(sorted(counts.items())),
            "hash_algorithm_counts": dict(sorted(algorithms.items())),
            "scripts_executed": 0, "archives_expanded": 0})
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                      for row in records))
    summary = {"schema_version": 1, "kind": "skill-benchmark-source-inventory-summary",
        "registry_file": registry_path.resolve().as_posix(),
        "registry_sha256": sha256_file(registry_path),
        "inventory_file": inventory_path.resolve().as_posix(),
        "inventory_sha256": sha256_file(inventory_path),
        "source_count": len(source_summaries), "asset_count": len(records),
        "sources": source_summaries, "scripts_executed": 0, "archives_expanded": 0,
        "network_actions": ("prefetched-git-clone-and-github-tree-api" if tree_indexes
                            else "prefetched-git-clone-only"),
        "genius_ground_truth": False}
    write_json(summary_path, summary)
    validate_inventory(registry_path, inventory_path, summary_path)
    return summary


def validate_inventory(registry_path: Path, inventory_path: Path,
                       summary_path: Path) -> dict[str, Any]:
    registry = validate_registry(registry_path)
    records = [json.loads(line) for line in inventory_path.read_text().splitlines() if line]
    seen = set()
    for record in records:
        _exact(record, {"schema_version", "kind", "source_id", "path", "hash_algorithm",
            "content_hash",
            "size_bytes", "asset_kind", "executable_content", "archive_not_expanded",
            "content_stored", "genius_ground_truth"}, "source asset")
        key = (record["source_id"], record["path"])
        hash_valid = ((record["hash_algorithm"] == "sha256"
                       and HASH64.fullmatch(str(record["content_hash"])))
                      or (record["hash_algorithm"] == "git-blob-sha1"
                          and HASH40.fullmatch(str(record["content_hash"]))))
        if (record["schema_version"] != 1 or record["kind"] != "skill-benchmark-source-asset"
                or record["source_id"] not in SOURCE_IDS or key in seen
                or not hash_valid
                or not isinstance(record["size_bytes"], int) or record["size_bytes"] < 0
                or record["content_stored"] is not False
                or record["genius_ground_truth"] is not False
                or ".." in Path(record["path"]).parts):
            raise ValueError("source asset record invalid")
        seen.add(key)
    summary = json.loads(summary_path.read_text())
    _exact(summary, {"schema_version", "kind", "registry_file", "registry_sha256",
        "inventory_file", "inventory_sha256", "source_count", "asset_count", "sources",
        "scripts_executed", "archives_expanded", "network_actions", "genius_ground_truth"},
        "inventory summary")
    if (summary["schema_version"] != 1
            or summary["kind"] != "skill-benchmark-source-inventory-summary"
            or summary["registry_sha256"] != sha256_file(registry_path)
            or summary["inventory_sha256"] != sha256_file(inventory_path)
            or summary["source_count"] != len(registry["sources"])
            or summary["asset_count"] != len(records)
            or summary["scripts_executed"] != 0 or summary["archives_expanded"] != 0
            or summary["genius_ground_truth"] is not False):
        raise ValueError("inventory summary drift")
    return {"valid": True, "source_count": len(registry["sources"]),
            "asset_count": len(records), "inventory_sha256": sha256_file(inventory_path),
            "scripts_executed": 0, "archives_expanded": 0, "genius_ground_truth": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "validate"))
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--checkout", action="append", default=[])
    parser.add_argument("--tree-index", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "inventory":
        pairs = {}
        for value in args.checkout:
            source_id, separator, path = value.partition("=")
            if not separator or source_id in pairs:
                raise ValueError("checkout must be unique source_id=path")
            pairs[source_id] = Path(path)
        trees = {}
        for value in args.tree_index:
            source_id, separator, path = value.partition("=")
            if not separator or source_id in trees:
                raise ValueError("tree index must be unique source_id=path")
            trees[source_id] = Path(path)
        result = build_inventory(args.registry, pairs, args.inventory, args.summary, trees)
    else:
        result = validate_inventory(args.registry, args.inventory, args.summary)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
