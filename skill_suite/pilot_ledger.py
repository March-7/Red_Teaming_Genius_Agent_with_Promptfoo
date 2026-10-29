"""Durable shared accounting for standing-authorized multi-risk pilots."""
from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from sweep.runtime import durable_json, utc_now
from sweep.runtime import sha256_file


KINDS = ("target", "management", "recovery", "cleanup", "generation", "judge", "retry")


class PilotBudgetError(RuntimeError):
    pass


class PilotLedger:
    def __init__(self, path: Path, limits: dict[str, int]):
        if set(limits) != set(KINDS) or any(type(v) is not int or v < 0 for v in limits.values()):
            raise PilotBudgetError("exact nonnegative standing limits required")
        self.path, self.limits = path, dict(limits)
        self._lock = threading.RLock()
        if path.exists():
            self.state = json.loads(path.read_text())
            if self.state.get("limits") != self.limits:
                raise PilotBudgetError("standing budget drift")
        else:
            self.state = {"schema_version": 1, "kind": "skill-pilot-standing-ledger",
                "limits": self.limits, "counts": dict.fromkeys(KINDS, 0),
                "attempts": [], "soft_stops": [], "pending_sessions": []}
            self._save()

    def _save(self) -> None:
        durable_json(self.path, self.state)

    def amend_limits(self, new_limits: dict[str, int], *, authorization_path: Path) -> None:
        """Apply one evidence-bound, monotonic standing-budget amendment."""
        with self._lock:
            if (set(new_limits) != set(KINDS)
                    or any(type(value) is not int or value < 0 for value in new_limits.values())):
                raise PilotBudgetError("exact nonnegative amended limits required")
            if not authorization_path.is_file():
                raise PilotBudgetError("budget amendment authorization missing")
            auth_hash = sha256_file(authorization_path)
            if any(row.get("authorization_sha256") == auth_hash
                   for row in self.state.get("limit_amendments", [])):
                raise PilotBudgetError("budget amendment already applied")
            if any(new_limits[key] < self.limits[key] for key in KINDS):
                raise PilotBudgetError("standing limits may only increase")
            if any(self.state["counts"][key] > new_limits[key] for key in KINDS):
                raise PilotBudgetError("amended limits below actual calls")
            old_limits = dict(self.limits)
            if old_limits == new_limits:
                raise PilotBudgetError("budget amendment must change a limit")
            self.state.setdefault("limit_amendments", []).append({
                "old_limits": old_limits, "new_limits": dict(new_limits),
                "authorization_file": str(authorization_path.resolve()),
                "authorization_sha256": auth_hash, "applied_at": utc_now()})
            self.limits = dict(new_limits)
            self.state["limits"] = dict(new_limits)
            self._save()

    def _attempt(self, operation_id: str) -> dict[str, Any]:
        matches = [row for row in self.state["attempts"] if row["operation_id"] == operation_id]
        if len(matches) != 1:
            raise PilotBudgetError("unique operation attempt required")
        return matches[0]

    def reserve(self, kind: str, operation_id: str) -> None:
        with self._lock:
            if kind not in KINDS or not isinstance(operation_id, str) or not operation_id:
                raise PilotBudgetError("known call kind and operation id required")
            if kind == "retry" or self.limits["retry"] != 0:
                raise PilotBudgetError("all pilot layers require zero retries")
            if any(row["operation_id"] == operation_id for row in self.state["attempts"]):
                raise PilotBudgetError("zero retries: operation already attempted")
            if self.state["pending_sessions"] and kind == "target":
                raise PilotBudgetError("unknown upstream terminal requires read-only recovery")
            increment = {kind: 1}
            if kind == "recovery":
                increment["management"] = 1
            for key, amount in increment.items():
                if self.state["counts"][key] + amount > self.limits[key]:
                    raise PilotBudgetError(key + " standing budget exhausted")
            for key, amount in increment.items():
                self.state["counts"][key] += amount
            self.state["attempts"].append({"kind": kind, "operation_id": operation_id,
                "submitted_at": utc_now(), "outcome": "unknown", "case_id": None,
                "row_id": None, "elapsed_s": None})
            self._save()

    def bind(self, operation_id: str, *, case_id: str, row_id: str) -> None:
        with self._lock:
            row = self._attempt(operation_id)
            if row["case_id"] is not None or row["row_id"] is not None:
                raise PilotBudgetError("attempt already bound")
            row.update(case_id=case_id, row_id=row_id)
            self._save()

    def finish(self, operation_id: str, outcome: str, *, elapsed_s: float = 0) -> None:
        with self._lock:
            row = self._attempt(operation_id)
            if row["outcome"] != "unknown":
                raise PilotBudgetError("attempt already terminal")
            if not isinstance(outcome, str) or not outcome or elapsed_s < 0:
                raise PilotBudgetError("terminal outcome and elapsed time required")
            row.update(outcome=outcome, elapsed_s=elapsed_s, finished_at=utc_now())
            self._save()

    def stop(self, reason: str) -> None:
        """Record an individual soft failure without stopping unrelated risk families."""
        with self._lock:
            self.state["soft_stops"].append({"reason": str(reason), "observed_at": utc_now()})
            self._save()

    def mark_pending(self, run_id: str, session_id: str, operation_id: str) -> None:
        with self._lock:
            item = {"run_id": run_id, "session_id": session_id, "operation_id": operation_id}
            if item in self.state["pending_sessions"]:
                raise PilotBudgetError("pending session already recorded")
            self.state["pending_sessions"].append(item)
            self._save()

    def resolve_pending(self, run_id: str, session_id: str, *, evidence_ref: dict[str, str]) -> None:
        with self._lock:
            matches = [item for item in self.state["pending_sessions"]
                       if item["run_id"] == run_id and item["session_id"] == session_id]
            if len(matches) != 1 or set(evidence_ref) != {"file", "sha256"}:
                raise PilotBudgetError("one pending session and recovery evidence required")
            self.state["pending_sessions"].remove(matches[0])
            self.state.setdefault("recovered_sessions", []).append({**matches[0],
                "evidence_ref": evidence_ref, "resolved_at": utc_now()})
            self._save()

    def case_counts(self, case_id: str) -> dict[str, int]:
        counts = dict.fromkeys(KINDS, 0)
        for row in self.state["attempts"]:
            if row.get("case_id") == case_id:
                counts[row["kind"]] += 1
                if row["kind"] == "recovery":
                    counts["management"] += 1
        return counts
