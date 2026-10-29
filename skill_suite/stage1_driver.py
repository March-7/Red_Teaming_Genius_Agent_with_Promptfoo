"""Stage-1 driver: run all 10 behavior-manipulation groups sequentially.

Hard budget: <=110 chat calls total. Counts live chat calls across groups
and stops the whole run when the budget is exhausted. Resource cleanup
happens per group inside run_group (safe delete pattern).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skill_suite.scale_runner import run_group, RUNS

BUDGET = 110
counter_path = RUNS / "stage1-chat-counter.json"


def chat_calls_so_far() -> int:
    if counter_path.exists():
        return json.loads(counter_path.read_text()).get("calls", 0)
    return 0


def record_calls(n: int) -> None:
    counter_path.write_text(json.dumps({"calls": chat_calls_so_far() + n}))


def main() -> None:
    groups = json.loads(Path("/tmp/stage1-groups.json").read_text())
    print(f"stage1: {len(groups)} groups, budget {BUDGET} chat calls", flush=True)

    completed = []
    for i, gdir in enumerate(groups, 1):
        used = chat_calls_so_far()
        if used >= BUDGET:
            print(f"BUDGET EXHAUSTED ({used}/{BUDGET}) before group {i} — stopping",
                  flush=True)
            break
        print(f"\n=== group {i}/{len(groups)}: {Path(gdir).name} "
              f"(budget used {used}/{BUDGET}) ===", flush=True)
        try:
            summary = run_group(Path(gdir))
            # count chat calls from this group's results
            calls = len(summary.get("results", []))
            # two-turn variants cost +1: count prompts per variant
            m = json.loads((Path(gdir) / "manifest.json").read_text())
            for v in m.get("variants", []):
                if isinstance(v.get("prompts"), list) and len(v["prompts"]) > 1:
                    calls += len(v["prompts"]) - 1
            record_calls(calls)
            completed.append({
                "group": Path(gdir).name,
                "design": m.get("design_id"),
                "total": summary.get("total"),
                "effect_confirmed": summary.get("effect_confirmed"),
                "chat_calls": calls,
            })
            print(f"  done: {summary.get('total')} variants, "
                  f"{summary.get('effect_confirmed')} confirmed, +{calls} calls "
                  f"(total {chat_calls_so_far()}/{BUDGET})", flush=True)
        except Exception as e:
            print(f"  GROUP FAILED: {e}", flush=True)
            completed.append({"group": Path(gdir).name, "error": str(e)[:200]})
        # brief pause between groups to be gentle on the platform
        time.sleep(5)

    print(f"\nstage1 driver complete: {len(completed)}/{len(groups)} groups, "
          f"{chat_calls_so_far()}/{BUDGET} chat calls", flush=True)
    (RUNS / "stage1-driver-summary.json").write_text(
        json.dumps(completed, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
