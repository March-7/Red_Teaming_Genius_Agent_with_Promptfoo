"""Extract hash-only benchmark relationships without executing source code."""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file, write_json
from .benchmark_registry import validate_inventory


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")))


def _inventory(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    return {(row["source_id"], row["path"]): row for row in rows}


def _ref(rows: dict[tuple[str, str], dict[str, Any]], source_id: str,
         path: str) -> dict[str, Any]:
    row = rows.get((source_id, path))
    if row is None:
        raise ValueError(f"source asset missing from inventory: {source_id}/{path}")
    return {"path": path, "hash_algorithm": row["hash_algorithm"],
            "content_hash": row["content_hash"]}


def _refs_for_path(rows: dict[tuple[str, str], dict[str, Any]], source_id: str,
                   path: str, *, required: bool = True) -> list[dict[str, Any]]:
    exact = rows.get((source_id, path.rstrip("/")))
    if exact is not None:
        return [_ref(rows, source_id, path.rstrip("/"))]
    prefix = path.rstrip("/") + "/"
    matches = [_ref(rows, source_id, candidate)
               for sid, candidate in sorted(rows)
               if sid == source_id and candidate.startswith(prefix)]
    if not matches and required:
        raise ValueError(f"source asset path or directory missing: {source_id}/{path}")
    return matches


def _skill_mapping(config_path: Path) -> dict[str, str]:
    tree = ast.parse(config_path.read_text())
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "SKILL_MAPPING":
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                      for k, v in value.items()):
                break
            return value
    raise ValueError("static SKILL_MAPPING not found")


def _skill_inject(checkout: Path, rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    data = checkout / "data"
    mapping = _skill_mapping(checkout / "config.py")
    injections = []
    for filename, family in (("contextual_injections.json", "contextual"),
                             ("obvious_injections.json", "obvious")):
        source_path = "data/" + filename
        for row in json.loads((data / filename).read_text()):
            instructions = row.get("instructions", {})
            contexts = row.get("context") or {}
            scripts = row.get("task_scripts") or {}
            startup = row.get("startup_scripts") or []
            task_links = []
            for task in row.get("tasks", []):
                task_links.append({"prompt_sha256": _hash_text(task["prompt"]),
                    "skill_key": task["skill"], "line_num": task.get("line_num"),
                    "task_files": sorted("data/" + value for value in
                                         (task.get("task_files") or {}).values())})
            injections.append({"family": family, "injection_id": row["id"],
                "type": row.get("type"), "catalogue_ref": _ref(rows, "skill-inject", source_path),
                "description_injection_sha256": _hash_text(instructions.get("description_injection", "")),
                "line_injection_sha256": _hash_text(instructions.get("line_injection", "")),
                "context_hashes": {key: _hash_text(value) for key, value in sorted(contexts.items())
                                   if isinstance(value, str)},
                "task_scripts": [_ref(rows, "skill-inject", "data/" + value)
                                 for value in sorted(scripts.values())],
                "startup_scripts": [_hash_text(value) for value in startup],
                "judge_prompt_sha256": _hash_text(row.get("judge_prompt", "")),
                "task_links": task_links, "upstream_claim_only": True,
                "genius_ground_truth": False})
    tasks = []
    for row in json.loads((data / "tasks.json").read_text()):
        skill_dir = mapping.get(row["skill"], row["skill"])
        skill_path = f"data/skills/{skill_dir}/SKILL.md"
        task_paths = ["data/" + value for value in
                      sorted((row.get("task_files") or {}).values())]
        task_refs = [ref for value in task_paths
                     for ref in _refs_for_path(rows, "skill-inject", value, required=False)]
        resolved = {ref["path"] for ref in task_refs}
        missing = [value for value in task_paths
                   if not any(path == value.rstrip("/")
                              or path.startswith(value.rstrip("/") + "/") for path in resolved)]
        tasks.append({"task_id": row["id"], "prompt_sha256": _hash_text(row["prompt"]),
            "skill_key": row["skill"], "clean_skill_ref": _ref(rows, "skill-inject", skill_path),
            "task_file_refs": task_refs, "missing_task_file_paths": missing,
            "injection_ids": sorted(row.get("injection_ids", [])),
            "upstream_claim_only": True, "genius_ground_truth": False})
    return {"schema_version": 1, "kind": "skill-inject-relationships",
        "source_id": "skill-inject", "injections": injections, "tasks": tasks,
        "scripts_executed": 0, "content_copied": False, "genius_ground_truth": False}


def _skilljack(checkout: Path, rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    root = checkout / "Research/SkillJack/data/poisoned_trajectories"
    trajectories = []
    for path in sorted(root.glob("*.jsonl")):
        relative = path.relative_to(checkout).as_posix()
        for index, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            metadata = row.get("metadata") or {}
            trajectories.append({"dataset_ref": _ref(rows, "aig-skilljack", relative),
                "row_number": index,
                "trajectory_id": str(row.get("trajectory_id") or row.get("id") or index),
                "task_id": row.get("task_id"),
                "risk_label": (row.get("attack_type") or metadata.get("attack_type")
                               or metadata.get("category") or "clean-or-unknown"),
                "user_task_sha256": _hash_text(str(row.get("user_task", ""))),
                "task_history_sha256": _hash_json(row.get("task_history", [])),
                "reward": row.get("reward"), "upstream_claim_only": True,
                "genius_ground_truth": False})
    return {"schema_version": 1, "kind": "skilljack-trajectory-relationships",
        "source_id": "aig-skilljack", "trajectories": trajectories,
        "runtime_boundary": "mock-output-and-generated-code-pattern-matching",
        "runtime_boundary_ref": _ref(rows, "aig-skilljack",
            "Research/SkillJack/skilljack/execution_verification.py"),
        "scripts_executed": 0, "content_copied": False, "genius_ground_truth": False}


def _tree_entries(path: Path) -> list[dict[str, Any]]:
    index = json.loads(path.read_text())
    if index.get("kind") != "git-tree-asset-index":
        raise ValueError("git tree index required")
    return index["entries"]


def _malskill(tree_path: Path, rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    packages: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in _tree_entries(tree_path):
        parts = entry["path"].split("/")
        if len(parts) >= 5 and parts[:2] == ["Dataset", "Skills"] and parts[2] in {"malware", "benign"}:
            packages[(parts[2], parts[3])].append(entry)
    records = []
    for (split, package_id), entries in sorted(packages.items()):
        prefix = f"Dataset/Skills/{split}/{package_id}/"
        skill = next((entry for entry in entries if entry["path"] == prefix + "SKILL.md"), None)
        if skill is None:
            raise ValueError("MalSkillBench package missing SKILL.md")
        digest = _hash_json(sorted((entry["path"], entry["git_blob_sha1"], entry["size_bytes"])
                                   for entry in entries))
        records.append({"split": split, "package_id": package_id,
            "inventory_prefix": prefix, "package_sha256": digest,
            "skill_ref": _ref(rows, "malskillbench", skill["path"]),
            "file_count": len(entries), "auxiliary_file_count": len(entries) - 1,
            "upstream_claim_only": True, "genius_ground_truth": False})
    return {"schema_version": 1, "kind": "malskillbench-package-relationships",
        "source_id": "malskillbench", "packages": records,
        "taxonomy_ref": _ref(rows, "malskillbench", "Core/taxonomy/behaviors.py"),
        "runtime_boundary": "released-packages-without-generation-or-verification-runtime-artifacts",
        "scripts_executed": 0, "content_copied": False, "genius_ground_truth": False}


def _skillsbench(tree_path: Path, rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in _tree_entries(tree_path):
        parts = entry["path"].split("/")
        if len(parts) >= 2 and parts[0] == "tasks":
            grouped[parts[1]].append(entry)
    tasks = []
    for task_id, entries in sorted(grouped.items()):
        prefix = f"tasks/{task_id}/"
        task = next((entry for entry in entries if entry["path"] == prefix + "task.md"), None)
        if task is None:
            continue
        skill_entries = [entry for entry in entries if "/environment/skills/" in "/" + entry["path"]
                         and entry["path"].endswith("/SKILL.md")]
        oracle_entries = [entry for entry in entries if "/oracle/" in "/" + entry["path"]]
        verifier_entries = [entry for entry in entries if "/verifier/" in "/" + entry["path"]]
        digest = _hash_json(sorted((entry["path"], entry["git_blob_sha1"], entry["size_bytes"])
                                   for entry in entries))
        tasks.append({"task_id": task_id, "inventory_prefix": prefix,
            "package_sha256": digest, "task_ref": _ref(rows, "skillsbench", task["path"]),
            "skill_refs": [_ref(rows, "skillsbench", entry["path"])
                           for entry in sorted(skill_entries, key=lambda row: row["path"])],
            "oracle_refs": [_ref(rows, "skillsbench", entry["path"])
                            for entry in sorted(oracle_entries, key=lambda row: row["path"])],
            "verifier_refs": [_ref(rows, "skillsbench", entry["path"])
                              for entry in sorted(verifier_entries, key=lambda row: row["path"])],
            "file_count": len(entries), "upstream_claim_only": True,
            "genius_ground_truth": False})
    return {"schema_version": 1, "kind": "skillsbench-task-relationships",
        "source_id": "skillsbench", "tasks": tasks,
        "scripts_executed": 0, "content_copied": False, "genius_ground_truth": False}


def extract(registry_path: Path, inventory_path: Path, summary_path: Path,
            aig_checkout: Path, skill_inject_checkout: Path,
            malskill_tree: Path, skillsbench_tree: Path, output: Path) -> dict[str, Any]:
    validate_inventory(registry_path, inventory_path, summary_path)
    if output.exists():
        raise ValueError("new relationship output directory required")
    rows = _inventory(inventory_path)
    output.mkdir(parents=True)
    documents = {
        "aig-skilljack.json": _skilljack(aig_checkout, rows),
        "skill-inject.json": _skill_inject(skill_inject_checkout, rows),
        "malskillbench.json": _malskill(malskill_tree, rows),
        "skillsbench.json": _skillsbench(skillsbench_tree, rows),
    }
    refs = []
    for filename, document in documents.items():
        write_json(output / filename, document)
        refs.append({"source_id": document["source_id"], "file": filename,
                     "sha256": sha256_file(output / filename)})
    summary = {"schema_version": 1, "kind": "skill-benchmark-relationship-summary",
        "source_registry_sha256": sha256_file(registry_path),
        "source_inventory_sha256": sha256_file(inventory_path), "relationships": refs,
        "counts": {"skilljack_trajectories": len(documents["aig-skilljack.json"]["trajectories"]),
            "skill_inject_injections": len(documents["skill-inject.json"]["injections"]),
            "skill_inject_tasks": len(documents["skill-inject.json"]["tasks"]),
            "skill_inject_missing_task_file_links": sum(
                len(row["missing_task_file_paths"])
                for row in documents["skill-inject.json"]["tasks"]),
            "malskillbench_packages": len(documents["malskillbench.json"]["packages"]),
            "malskillbench_malware_packages": sum(
                row["split"] == "malware" for row in documents["malskillbench.json"]["packages"]),
            "malskillbench_benign_packages": sum(
                row["split"] == "benign" for row in documents["malskillbench.json"]["packages"]),
            "skillsbench_tasks": len(documents["skillsbench.json"]["tasks"]),
            "skillsbench_skill_refs": sum(
                len(row["skill_refs"]) for row in documents["skillsbench.json"]["tasks"]),
            "skillsbench_oracle_refs": sum(
                len(row["oracle_refs"]) for row in documents["skillsbench.json"]["tasks"]),
            "skillsbench_verifier_refs": sum(
                len(row["verifier_refs"]) for row in documents["skillsbench.json"]["tasks"])},
        "scripts_executed": 0, "content_copied": False, "genius_ground_truth": False}
    write_json(output / "summary.json", summary)
    validate_relationships(registry_path, inventory_path, summary_path, output)
    return summary


def validate_relationships(registry_path: Path, inventory_path: Path,
                           inventory_summary_path: Path, output: Path) -> dict[str, Any]:
    validate_inventory(registry_path, inventory_path, inventory_summary_path)
    inventory = _inventory(inventory_path)
    summary = json.loads((output / "summary.json").read_text())
    if (summary.get("kind") != "skill-benchmark-relationship-summary"
            or summary.get("source_registry_sha256") != sha256_file(registry_path)
            or summary.get("source_inventory_sha256") != sha256_file(inventory_path)
            or summary.get("scripts_executed") != 0
            or summary.get("content_copied") is not False
            or summary.get("genius_ground_truth") is not False
            or {row.get("source_id") for row in summary.get("relationships", [])}
               != {"aig-skilljack", "skill-inject", "malskillbench", "skillsbench"}):
        raise ValueError("relationship summary drift")
    documents = {}
    for ref in summary["relationships"]:
        path = output / ref["file"]
        if sha256_file(path) != ref["sha256"]:
            raise ValueError("relationship document hash drift")
        document = json.loads(path.read_text())
        if (document.get("source_id") != ref["source_id"]
                or document.get("scripts_executed") != 0
                or document.get("content_copied") is not False
                or document.get("genius_ground_truth") is not False):
            raise ValueError("relationship document evidence boundary invalid")
        documents[ref["source_id"]] = document

        def check_refs(value: Any) -> None:
            if isinstance(value, dict):
                if set(value) == {"path", "hash_algorithm", "content_hash"}:
                    row = inventory.get((ref["source_id"], value["path"]))
                    if row is None or any(value[key] != row[key]
                                          for key in ("hash_algorithm", "content_hash")):
                        raise ValueError("relationship source ref drift")
                for child in value.values():
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)
        check_refs(document)
    skill_inject = documents["skill-inject"]
    for row in skill_inject["injections"] + skill_inject["tasks"]:
        if row.get("upstream_claim_only") is not True or row.get("genius_ground_truth") is not False:
            raise ValueError("SKILL-INJECT upstream label promoted")
    missing = [path for row in skill_inject["tasks"] for path in row["missing_task_file_paths"]]
    for path in missing:
        if any(sid == "skill-inject" and (candidate == path.rstrip("/")
               or candidate.startswith(path.rstrip("/") + "/")) for sid, candidate in inventory):
            raise ValueError("resolved task file incorrectly marked missing")
    skilljack = documents["aig-skilljack"]
    if any(row.get("upstream_claim_only") is not True
           or row.get("genius_ground_truth") is not False
           for row in skilljack["trajectories"]):
        raise ValueError("SkillJack upstream label promoted")
    malskill = documents["malskillbench"]
    split_counts = {split: sum(row["split"] == split for row in malskill["packages"])
                    for split in ("malware", "benign")}
    skillsbench = documents["skillsbench"]
    counts = {"skilljack_trajectories": len(skilljack["trajectories"]),
        "skill_inject_injections": len(skill_inject["injections"]),
        "skill_inject_tasks": len(skill_inject["tasks"]),
        "skill_inject_missing_task_file_links": len(missing),
        "malskillbench_packages": len(malskill["packages"]),
        "malskillbench_malware_packages": split_counts["malware"],
        "malskillbench_benign_packages": split_counts["benign"],
        "skillsbench_tasks": len(skillsbench["tasks"]),
        "skillsbench_skill_refs": sum(len(row["skill_refs"]) for row in skillsbench["tasks"]),
        "skillsbench_oracle_refs": sum(len(row["oracle_refs"]) for row in skillsbench["tasks"]),
        "skillsbench_verifier_refs": sum(len(row["verifier_refs"]) for row in skillsbench["tasks"])}
    if summary.get("counts") != counts or split_counts != {"malware": 3944, "benign": 4000}:
        raise ValueError("relationship counts drift")
    return {"valid": True, "counts": counts, "scripts_executed": 0,
            "content_copied": False, "genius_ground_truth": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("extract", "validate"))
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--aig-checkout", type=Path)
    parser.add_argument("--skill-inject-checkout", type=Path)
    parser.add_argument("--malskill-tree", type=Path)
    parser.add_argument("--skillsbench-tree", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "extract":
        if not all((args.aig_checkout, args.skill_inject_checkout,
                    args.malskill_tree, args.skillsbench_tree)):
            raise ValueError("extract requires two checkouts and two complete tree indexes")
        result = extract(args.registry, args.inventory, args.summary, args.aig_checkout,
            args.skill_inject_checkout, args.malskill_tree, args.skillsbench_tree, args.output)
    else:
        result = validate_relationships(args.registry, args.inventory, args.summary, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
