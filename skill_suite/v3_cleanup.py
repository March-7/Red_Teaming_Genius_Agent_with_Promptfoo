"""Option-A cleanup: exact-scope deletion of all v3 round resources.

Reads v1-cleanup-plan.json (skills + sessions registered in the formal-r1
run registries), verifies each identity server-side (GET name/visibility/
owner match), DELETEs, and verifies 404. Every step writes a receipt into
the cleanup run directory; counts go through the stage ledger.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from sweep.runtime import sha256_file, write_json
from .package_gate_live import LivePackageGate


BASE = Path("skill-suites/benchmark-multi-risk")
AUTH_PATH = BASE / "v3-round-authorization.json"
CLEANUP_LIMITS = {"target": 0, "management": 400, "recovery": 4,
                  "cleanup": 140, "generation": 0, "judge": 0, "retry": 0}
USER_DECISION_REF = "user-message:2026-10-09-approve-v3-round-budget"


def _verify_auth(root: Path) -> None:
    auth = json.loads((root / AUTH_PATH).read_text())
    if (auth["kind"] != "genius-v3-round-authorization"
            or auth["user_decision_ref"] != USER_DECISION_REF
            or auth["active"] is not True
            or auth["authorized_actions"]["v2_cleanup_first"] != "A"
            or sha256_file(root / auth["plan_file"]) != auth["plan_sha256"]):
        raise ValueError("v2 authorization drift")


def run_cleanup(root: Path, run: Path) -> dict[str, Any]:
    _verify_auth(root)
    if (run / "summary.json").exists():
        raise ValueError("cleanup already executed; no retry")
    run.mkdir(parents=True, exist_ok=True)
    plan = json.loads((root / BASE / "formal-round1"
                       / "v3-cleanup-plan.json").read_text())
    skills: dict[str, str] = plan["skills"]
    sessions: list[str] = plan["sessions"]
    results = {"skills_deleted": 0, "skills_already_absent": 0,
               "sessions_deleted": 0, "sessions_already_absent": 0,
               "problems": []}
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        live = LivePackageGate(root, run, stage_limits=CLEANUP_LIMITS,
            global_limits=json.loads((root / BASE / "runs"
                / "pilot-standing-ledger.json").read_text())["limits"])
        try:
            for index, (skill_id, expected_name) in enumerate(sorted(
                    skills.items())):
                label = f"v1c-skill-{index:03d}"
                encoded = quote(skill_id, safe="")
                try:
                    body, _ = live.request(
                        run.name + ":" + label + "-get", "GET",
                        "/api/skills/" + encoded)
                    skill = (body or {}).get("skill") or {}
                    if (skill.get("name") != expected_name
                            or skill.get("visibility") != "private"
                            or skill.get("source") != "user"):
                        results["problems"].append(
                            f"identity mismatch {skill_id}")
                        continue
                    live.request(run.name + ":" + label + "-delete", "DELETE",
                        "/api/skills/" + encoded, kind="cleanup")
                    live.request(run.name + ":" + label + "-verify404", "GET",
                        "/api/skills/" + encoded, expected={404})
                    results["skills_deleted"] += 1
                    live.registry.record(skill_id, "skill", expected_name,
                        "deleted", owner_run_id=run.name, shared=False,
                        environment="live", variant="v3-cleanup")
                except ValueError as exc:
                    if "returned 404" in str(exc):
                        results["skills_already_absent"] += 1
                    else:
                        results["problems"].append(f"{skill_id}: {exc}")
            for index, session_id in enumerate(sorted(sessions)):
                label = f"v1c-session-{index:03d}"
                encoded = quote(session_id, safe="")
                try:
                    state, _ = live.request(
                        run.name + ":" + label + "-live", "GET",
                        "/api/sessions/" + encoded + "/live")
                    if state.get("active") is not False:
                        results["problems"].append(
                            f"session still active {session_id}")
                        continue
                    live.request(run.name + ":" + label + "-delete", "DELETE",
                        "/api/sessions/" + encoded, kind="cleanup",
                        expected={200, 204})
                    live.request(run.name + ":" + label + "-verify404", "GET",
                        "/api/sessions/" + encoded + "/live",
                        expected={404})
                    results["sessions_deleted"] += 1
                    live.registry.record(session_id, "session",
                        "v1-formal-session", "deleted",
                        owner_run_id=run.name, shared=False,
                        environment="live")
                except ValueError as exc:
                    if "returned 404" in str(exc):
                        results["sessions_already_absent"] += 1
                    else:
                        results["problems"].append(f"{session_id}: {exc}")
            summary = {"schema_version": 1,
                "kind": "genius-v3-cleanup-summary",
                "run_id": run.name, **results,
                "actual_calls": live.stage.state["counts"],
                "problems_count": len(results["problems"]),
                "user_decision_ref": USER_DECISION_REF}
            write_json(run / "summary.json", summary)
            return summary
        finally:
            live.close()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_cleanup(args.root.resolve(), args.run.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
