"""Build and validate the completed package runtime-only capability result."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file, write_json
from .stage_e_pilot import TOTAL_LIMITS


STAGE_CALLS = {"target": 2, "management": 54, "recovery": 1,
               "cleanup": 12, "generation": 0, "judge": 0, "retry": 0}
INCREMENT_CALLS = {"target": 2, "management": 11, "recovery": 0,
                   "cleanup": 3, "generation": 0, "judge": 0, "retry": 0}
RESOURCES = {"private_package_skills_created": 1,
             "private_package_skills_deleted_404": 1,
             "general_sessions_created": 2,
             "general_sessions_deleted_404": 2,
             "projects": 0, "resource_cap_compliant": True}


def _ref(base: Path, path: Path) -> dict[str, str]:
    return {"file": str(path.resolve().relative_to(base.resolve())),
            "sha256": sha256_file(path)}


def build(root: Path, run: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("new package runtime summary required")
    base = root / "skill-suites/benchmark-multi-risk"
    run_summary = json.loads((run / "summary.json").read_text())
    manifest = json.loads((run / "run-manifest.json").read_text())
    package = json.loads((run / "runtime-package.json").read_text())
    if (run_summary.get("status") != "runtime-supported-source-partial"
            or run_summary.get("actual_calls") != STAGE_CALLS
            or run_summary.get("resources") != RESOURCES):
        raise ValueError("runtime-only run boundary drift")
    models = []
    for tag, profile in (("q", "default"), ("d", "deepseek-v4.1-flash")):
        result = json.loads((run / f"result-{tag}.json").read_text())
        evidence = result.get("runtime_evidence", {})
        models.append({"model_profile": profile, "status": result.get("status"),
            "runtime_evidence": evidence,
            "target_http_attempts": result.get("target_http_attempts"),
            "final_answer_shape": "json-fenced" if tag == "q"
                                  else "warning-not-json"})
    evidence_names = ["run-manifest.json", "ledger.json", "runtime-package.json",
        "validate-upload.json", "confirm-upload.json", "read-skill.json",
        "read-sharing.json", "result-q.json", "result-d.json",
        "delete-skill.json", "verify-skill-absent.json",
        "live-q.json", "delete-session-q.json", "verify-session-absent-q.json",
        "live-d.json", "delete-session-d.json", "verify-session-absent-d.json",
        "summary.json"]
    if any(not (run / name).is_file() for name in evidence_names):
        raise ValueError("package runtime evidence missing")
    value = {"schema_version": 1,
        "kind": "genius-package-runtime-only-summary",
        "run_id": run.name, "status": "runtime-supported-source-partial",
        "plan_ref": _ref(base, run / "frozen-runtime-plan.json"),
        "authorization_ref": _ref(base, run / "frozen-runtime-authorization.json"),
        "evidence_refs": [_ref(base, run / name) for name in evidence_names],
        "package_identity": {key: package[key] for key in
            ("package_sha256", "mode", "skill_name", "entrypoint_path", "nonce",
             "asset_sha256")},
        "models": models,
        "capabilities": {"private_package_control_plane": True,
            "package_skill_read_both_models": True,
            "package_entrypoint_runtime_both_models": True,
            "package_asset_runtime_both_models": True,
            "source_byte_readback_complete": False,
            "formal_package_track_ready": False},
        "resources": RESOURCES,
        "increment_calls": INCREMENT_CALLS,
        "actual_calls": STAGE_CALLS,
        "global_calls": run_summary["global_calls"],
        "guard_sha256": manifest["code_hashes"]["sweep/sensitive_output_guard.cjs"],
        "pending_compute_ownership": 0,
        "formal_target_calls": 0,
        "generation_calls": 0, "judge_calls": 0, "retry_calls": 0,
        "formal_asr_eligible": False}
    write_json(output, value)
    return validate(root, output)


def validate(root: Path, output: Path) -> dict[str, Any]:
    base = root / "skill-suites/benchmark-multi-risk"
    value = json.loads(output.read_text())
    caps = value.get("capabilities", {})
    if (value.get("kind") != "genius-package-runtime-only-summary"
            or value.get("status") != "runtime-supported-source-partial"
            or value.get("actual_calls") != STAGE_CALLS
            or value.get("increment_calls") != INCREMENT_CALLS
            or value.get("resources") != RESOURCES
            or caps != {"private_package_control_plane": True,
                "package_skill_read_both_models": True,
                "package_entrypoint_runtime_both_models": True,
                "package_asset_runtime_both_models": True,
                "source_byte_readback_complete": False,
                "formal_package_track_ready": False}
            or value.get("pending_compute_ownership") != 0
            or value.get("formal_target_calls") != 0
            or value.get("generation_calls") != 0 or value.get("judge_calls") != 0
            or value.get("retry_calls") != 0
            or value.get("formal_asr_eligible") is not False):
        raise ValueError("package runtime summary boundary drift")
    if [row.get("model_profile") for row in value.get("models", [])] != [
            "default", "deepseek-v4.1-flash"]:
        raise ValueError("package runtime model matrix drift")
    for row in value["models"]:
        ev = row.get("runtime_evidence", {})
        if (row.get("status") != "package-runtime-valid"
                or ev.get("skill_read_verified") is not True
                or ev.get("package_script_call_count") != 1
                or ev.get("package_script_result_count") != 1
                or ev.get("ordinary_tool_substitute") is not False
                or ev.get("package_entrypoint_bound") is not True
                or ev.get("nonce_verified") is not True
                or ev.get("asset_sha256_verified") is not True
                or ev.get("tool_name") != "execute_shell_command"
                or row.get("target_http_attempts") != [{"method": "POST",
                    "path_sha256": "4f82c21bc55e34fa34be97fe2b4a8112849a273fb3f487a746d93de4d952e237",
                    "kind": "target", "outcome": "completed", "status_code": 200}]):
            raise ValueError("package runtime trace evidence drift")
    for ref in [value["plan_ref"], value["authorization_ref"],
                *value["evidence_refs"]]:
        path = base / ref["file"]
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError("package runtime evidence ref drift")
    standing = json.loads((base / "runs/pilot-standing-ledger.json").read_text())
    current, historical = standing.get("counts", {}), value.get("global_calls", {})
    if (standing.get("limits") != TOTAL_LIMITS or set(current) != set(historical)
            or any(historical[key] > current[key] for key in current)):
        raise ValueError("package runtime global ledger drift")
    return {"valid": True, "status": value["status"],
        "package_runtime_supported": True,
        "package_asset_runtime_supported": True,
        "source_byte_readback_complete": False,
        "formal_package_track_ready": False,
        "models": 2, "target_calls": 2,
        "formal_target_calls": 0, "formal_asr_eligible": False}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    result = build(root, args.run.resolve(), output) if args.command == "build" \
        else validate(root, output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
