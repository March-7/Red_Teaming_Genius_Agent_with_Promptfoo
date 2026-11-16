"""Stage-2 driver: 3 families × 10 groups, full evidence capture.

Budget: <=340 chat calls total across all families. Family-serial
execution; per-group cleanup with evidence persisted before deletion.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skill_suite.scale_runner import run_group, RUNS

BUDGET = 340
counter_path = RUNS / "stage2-chat-counter.json"


def chat_calls_so_far() -> int:
    if counter_path.exists():
        return json.loads(counter_path.read_text()).get("calls", 0)
    return 0


def record_calls(n: int) -> None:
    counter_path.write_text(json.dumps({"calls": chat_calls_so_far() + n}))


def main() -> None:
    groups = json.loads(Path("/tmp/stage2-groups.json").read_text())
    print(f"stage2: {len(groups)} groups (3 families), budget {BUDGET} chat calls",
          flush=True)

    completed = []
    current_family = None
    for i, gdir in enumerate(groups, 1):
        used = chat_calls_so_far()
        if used >= BUDGET:
            print(f"BUDGET EXHAUSTED ({used}/{BUDGET}) before group {i} — stopping",
                  flush=True)
            break
        m = json.loads((Path(gdir) / "manifest.json").read_text())
        fam = m.get("family")
        if fam != current_family:
            current_family = fam
            print(f"\n########## FAMILY: {fam} ##########", flush=True)
        print(f"=== group {i}/{len(groups)}: {Path(gdir).name} "
              f"({m.get('design_id')}, budget {used}/{BUDGET}) ===", flush=True)
        try:
            summary = run_group(Path(gdir))
            calls = len(summary.get("results", []))
            for v in m.get("variants", []):
                if isinstance(v.get("prompts"), list) and len(v["prompts"]) > 1:
                    calls += len(v["prompts"]) - 1
            record_calls(calls)
            # evidence_full completeness check
            ev_missing = sum(
                1 for r in summary.get("results", [])
                if r.get("status") != "error" and not r.get("evidence_full"))
            completed.append({
                "group": Path(gdir).name,
                "family": fam,
                "design": m.get("design_id"),
                "total": summary.get("total"),
                "effect_confirmed": summary.get("effect_confirmed"),
                "chat_calls": calls,
                "evidence_missing": ev_missing,
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

    print(f"\nstage2 driver complete: {len(completed)}/{len(groups)} groups, "
          f"{chat_calls_so_far()}/{BUDGET} chat calls", flush=True)
    (RUNS / "stage2-driver-summary.json").write_text(
        json.dumps(completed, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
