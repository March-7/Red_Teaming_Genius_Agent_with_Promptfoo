"""Freeze and validate the blocked package Skill capability-gate result."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file, write_json
from .stage_e_pilot import TOTAL_LIMITS


def _ref(base: Path, path: Path) -> dict[str, str]:
    return {"file": str(path.resolve().relative_to(base.resolve())),
            "sha256": sha256_file(path)}


def build(root: Path, runs: list[Path], output: Path) -> dict[str, Any]:
    if output.exists() or len(runs) != 5:
        raise ValueError("new package gate summary and five evidence runs required")
    base = root / "skill-suites/benchmark-multi-risk"
    gate = base / "package-capability-gate"
    template_run, validation_run, download_run, schema_run, final_run = runs
    evidence_paths = [
        template_run / "template-inspections.json",
        validation_run / "validate-upload.json",
        validation_run / "cancel-upload.json",
        download_run / "confirm-upload.json",
        download_run / "read-skill.json",
        download_run / "read-sharing.json",
        download_run / "download-package.json",
        schema_run / "test-package.json",
        schema_run / "delete-after-test-error.json",
        schema_run / "verify-absent-after-test-error.json",
        final_run / "test-package.json",
        final_run / "delete-on-error.json",
        final_run / "verify-absent-on-error.json",
        final_run / "cleanup-result.json",
        final_run / "cleanup-unresolved-result.json",
    ]
    if any(not path.is_file() for path in evidence_paths):
        raise ValueError("package gate evidence file missing")
    ledger = json.loads((final_run / "ledger.json").read_text())
    global_ledger = json.loads((base / "runs/pilot-standing-ledger.json").read_text())
    if global_ledger.get("limits") != TOTAL_LIMITS:
        raise ValueError("global standing ledger drift")
    summary = {"schema_version": 1, "kind": "genius-package-skill-capability-summary",
        "status": "blocked-prerequisite",
        "plan_ref": _ref(base, gate / "plan.json"),
        "authorization_ref": _ref(base, gate / "authorization-request.json"),
        "evidence_refs": [_ref(base, path) for path in evidence_paths],
        "capabilities": {
            "official_shell_template_download": True,
            "official_sandbox_template_download": True,
            "private_zip_validate_confirm": True,
            "shell_mode_executable_metadata": True,
            "scripts_and_asset_metadata_readback": True,
            "package_download": False,
            "package_download_blocker": "account-policy-disabled-403",
            "package_test": False,
            "package_test_blocker": "server-500-with-required-script-name",
            "package_runtime": False,
            "package_asset_runtime": False,
            "source_byte_readback_complete": False,
            "formal_package_track_ready": False},
        "models": {"default": "not-submitted-prerequisite-blocked",
                   "deepseek-v4.1-flash": "not-submitted-prerequisite-blocked"},
        "resources": {"package_skills_created": 2, "package_skills_deleted_404": 2,
            "general_sessions_created": 4, "general_sessions_deleted_404": 3,
            "unresolved_session_attempts": 1, "projects": 0,
            "resource_cap_compliant": False},
        "actual_calls": ledger["counts"], "global_calls": global_ledger["counts"],
        "target_calls": 0, "generation_calls": 0, "judge_calls": 0,
        "retry_calls": 0, "pending_compute_ownership": 0,
        "confirmed_findings": 0, "formal_asr_eligible": False}
    write_json(output, summary)
    return validate(root, output)


def validate(root: Path, output: Path) -> dict[str, Any]:
    base = root / "skill-suites/benchmark-multi-risk"
    value = json.loads(output.read_text())
    caps, resources = value.get("capabilities", {}), value.get("resources", {})
    if (value.get("kind") != "genius-package-skill-capability-summary"
            or value.get("status") != "blocked-prerequisite"
            or caps.get("private_zip_validate_confirm") is not True
            or caps.get("shell_mode_executable_metadata") is not True
            or caps.get("package_download") is not False
            or caps.get("package_test") is not False
            or caps.get("package_runtime") is not False
            or caps.get("formal_package_track_ready") is not False
            or resources != {"package_skills_created": 2,
                "package_skills_deleted_404": 2, "general_sessions_created": 4,
                "general_sessions_deleted_404": 3, "unresolved_session_attempts": 1,
                "projects": 0, "resource_cap_compliant": False}
            or value.get("actual_calls") != {"target": 0, "management": 32,
                "recovery": 1, "cleanup": 6, "generation": 0, "judge": 0, "retry": 0}
            or value.get("target_calls") != 0 or value.get("generation_calls") != 0
            or value.get("judge_calls") != 0 or value.get("retry_calls") != 0
            or value.get("pending_compute_ownership") != 0
            or value.get("formal_asr_eligible") is not False):
        raise ValueError("package gate summary boundary drift")
    for key in ("plan_ref", "authorization_ref"):
        ref = value[key]
        path = base / ref["file"]
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError("package gate summary source drift")
    for ref in value["evidence_refs"]:
        path = base / ref["file"]
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError("package gate evidence drift")
    global_ledger = json.loads((base / "runs/pilot-standing-ledger.json").read_text())
    global_counts = global_ledger["counts"]
    historical = value["global_calls"]
    if (global_ledger.get("limits") != TOTAL_LIMITS
            or set(historical) != set(global_counts)
            or any(historical[key] > global_counts[key] for key in global_counts)):
        raise ValueError("package gate global ledger drift")
    return {"valid": True, "status": "blocked-prerequisite",
        "private_zip_control_plane": True, "package_runtime": False,
        "package_asset_runtime": False, "formal_package_track_ready": False,
        "actual_calls": value["actual_calls"], "global_calls": value["global_calls"],
        "resource_cap_compliant": False, "unresolved_session_attempts": 1,
        "target_calls": 0, "generation_calls": 0, "judge_calls": 0}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--runs", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = (build(root, [path.resolve() for path in args.runs], args.output.resolve())
              if args.command == "build" else validate(root, args.output.resolve()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
