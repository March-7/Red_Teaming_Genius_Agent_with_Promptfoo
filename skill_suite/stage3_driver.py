"""Stage-3 driver: 12 families layered (6 full × 10 groups + 6 probe × 3).

Budget: <=960 chat calls. Family-serial, self-consistent families first.
Recovery: if /tmp/stage3-groups.json is lost, rebuild from disk manifests.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skill_suite.scale_runner import run_group, RUNS

BUDGET = 960
counter_path = RUNS / "stage3-chat-counter.json"
FAMILIES_FULL = ["security-configuration-tampering", "skill-impersonation",
                 "output-reference-poisoning", "security-check-bypass",
                 "resource-abuse", "hidden-instruction-asset-poisoning"]
FAMILIES_PROBE = ["safety-bypass", "instruction-override", "goal-hijacking",
                  "credential-theft", "malware-delivery",
                  "command-parameter-injection"]


def rebuild_groups_from_disk() -> list[str]:
    """Recovery: rebuild the group list from disk manifests."""
    groups = []
    for g in sorted(RUNS.glob("group-*")):
        m = g / "manifest.json"
        if not m.exists():
            continue
        d = json.loads(m.read_text())
        fam = d.get("family")
        if fam in FAMILIES_FULL:
            if not d.get("design_id"):
                continue
            num = int(d["design_id"].split("-d")[-1])
            if num <= 10:
                groups.append((0, FAMILIES_FULL.index(fam), num, str(g)))
        elif fam in FAMILIES_PROBE:
            if not d.get("design_id"):
                continue
            num = int(d["design_id"].split("-d")[-1])
            if num <= 3:
                groups.append(1, FAMILIES_PROBE.index(fam), num, str(g))
    groups.sort()
    return [g[3] for g in groups]


def chat_calls_so_far() -> int:
    if counter_path.exists():
        return json.loads(counter_path.read_text()).get("calls", 0)
    return 0


def record_calls(n: int) -> None:
    counter_path.write_text(json.dumps({"calls": chat_calls_so_far() + n}))


def main() -> None:
    groups_file = Path("/tmp/stage3-groups.json")
    if groups_file.exists():
        groups = json.loads(groups_file.read_text())
    else:
        groups = rebuild_groups_from_disk()
        groups_file.write_text(json.dumps(groups))
        print(f"recovered group list from disk: {len(groups)}", flush=True)
    # drop already-completed groups (recovery resume)
    remaining = [g for g in groups if not (Path(g) / "summary.json").exists()]
    print(f"stage3: {len(remaining)}/{len(groups)} groups to run, "
          f"budget {BUDGET} chat calls", flush=True)

    completed = []
    current_family = None
    for i, gdir in enumerate(remaining, 1):
        used = chat_calls_so_far()
        if used >= BUDGET:
            print(f"BUDGET EXHAUSTED ({used}/{BUDGET}) before group {i} — stop",
                  flush=True)
            break
        m = json.loads((Path(gdir) / "manifest.json").read_text())
        fam = m.get("family")
        if fam != current_family:
            current_family = fam
            layer = "FULL" if fam in FAMILIES_FULL else "PROBE"
            print(f"\n########## FAMILY [{layer}]: {fam} ##########", flush=True)
        print(f"=== group {i}/{len(remaining)}: {Path(gdir).name} "
              f"({m.get('design_id')}, budget {used}/{BUDGET}) ===", flush=True)
        try:
            summary = run_group(Path(gdir))
            calls = len(summary.get("results", []))
            for v in m.get("variants", []):
                if isinstance(v.get("prompts"), list) and len(v["prompts"]) > 1:
                    calls += len(v["prompts"]) - 1
            record_calls(calls)
            ev_missing = sum(
                1 for r in summary.get("results", [])
                if r.get("status") != "error" and not r.get("evidence_full"))
            completed.append({
                "group": Path(gdir).name, "family": fam,
                "design": m.get("design_id"),
                "total": summary.get("total"),
                "effect_confirmed": summary.get("effect_confirmed"),
                "chat_calls": calls, "evidence_missing": ev_missing,
            })
            print(f"  done: {summary.get('total')} vars, "
                  f"{summary.get('effect_confirmed')} confirmed, +{calls} calls "
                  f"(total {chat_calls_so_far()}/{BUDGET}), "
                  f"ev_missing={ev_missing}", flush=True)
        except Exception as e:
            print(f"  GROUP FAILED: {e}", flush=True)
            completed.append({"group": Path(gdir).name, "family": fam,
                              "error": str(e)[:200]})
        time.sleep(5)

    print(f"\nstage3 driver complete: {len(completed)}/{len(remaining)} groups, "
          f"{chat_calls_so_far()}/{BUDGET} chat calls", flush=True)
    (RUNS / "stage3-driver-summary.json").write_text(
        json.dumps(completed, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
