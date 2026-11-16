"""Durable, attempt-based accounting and phase-bound confirmation."""
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
from typing import Any

from sweep.runtime import durable_json, utc_now
from .schema import CALL_KINDS, canonical_hash


class BudgetError(RuntimeError):
    pass


def confirmation_scope(suite: dict[str, Any]) -> str:
    return canonical_hash({k: v for k, v in suite.items() if k != "confirmation"})


def require_confirmation(suite: dict[str, Any], run_id: str) -> None:
    record = suite.get("confirmation") or {}
    if (record.get("actor") != "human-user" or record.get("decision") != "start"
            or record.get("phase") != suite["phase"] or record.get("run_id") != run_id
            or record.get("scope_hash") != confirmation_scope(suite)
            or not record.get("message_ref") or not record.get("confirmed_at")):
        raise BudgetError("explicit phase/run/scope-bound user confirmation required")
    if suite["lifecycle"] not in {"retain", "cleanup"}:
        raise BudgetError("retain/cleanup choice required")


class Ledger:
    """Use under the project lock; individual attempts are thread safe and fsynced."""
    def __init__(self, path: Path, limits: dict[str, int]):
        self.path, self.limits = path, dict(limits)
        self._lock = threading.RLock()
        if path.exists():
            self.state = json.loads(path.read_text())
            if self.state["limits"] != limits:
                raise BudgetError("budget drift on resume")
            if any(a["outcome"] == "unknown" for a in self.state["attempts"]):
                self.state["stopped"] = "unfinished attempt; read-only reconciliation required"
                self._save()
        else:
            self.state = {"limits": self.limits, "counts": dict.fromkeys(CALL_KINDS, 0),
                          "activity_s": 0, "stopped": None, "attempts": []}
            self._save()

    def _save(self) -> None:
        durable_json(self.path, self.state)

    def stop(self, reason: str) -> None:
        with self._lock:
            self.state["stopped"] = reason
            self._save()

    def amend_management_limit(self, limit: int, authorization: dict[str, Any]) -> None:
        """Explicit human budget revision, preserving every prior attempt and limit."""
        with self._lock:
            old = self.limits["management"]
            if (type(limit) is not int or limit <= old or authorization.get("actor") != "human-user"
                    or authorization.get("decision") != "amend-management-budget"
                    or authorization.get("previous_limit") != old or authorization.get("new_limit") != limit
                    or not authorization.get("message_ref") or not authorization.get("confirmed_at")
                    or self.state["stopped"] or any(a["outcome"] == "unknown" for a in self.state["attempts"])):
                raise BudgetError("explicit budget amendment on an idle, unstopped ledger required")
            self.state.setdefault("budget_revisions", []).append(dict(authorization))
            self.limits["management"] = limit
            self.state["limits"] = dict(self.limits)
            self._save()

    def reserve(self, kind: str, operation_id: str) -> None:
        with self._lock:
            if kind not in CALL_KINDS:
                raise BudgetError("unknown call kind")
            if any(a["operation_id"] == operation_id for a in self.state["attempts"]):
                raise BudgetError("zero retries: operation already attempted")
            if self.state["stopped"] and kind not in {"recovery", "cleanup"}:
                raise BudgetError("new work stopped: " + self.state["stopped"])
            counts = self.state["counts"]
            if kind == "target" and self.state["activity_s"] >= self.limits["activity_total_s"]:
                self.stop("activity budget exceeded")
                raise BudgetError("activity budget exceeded")
            if counts[kind] >= self.limits[kind]:
                self.stop(kind + " budget exceeded")
                raise BudgetError(kind + " budget exceeded")
            if kind == "recovery" and counts["management"] >= self.limits["management"]:
                self.stop("management budget exceeded")
                raise BudgetError("management budget exceeded")
            if kind == "management" and counts[kind] >= self.limits[kind] - self.limits["recovery"]:
                self.stop("management recovery reserve reached")
                raise BudgetError("management recovery reserve reached")
            counts[kind] += 1
            if kind == "recovery":
                counts["management"] += 1
            self.state["attempts"].append({"kind": kind, "operation_id": operation_id,
                                           "submitted_at": utc_now(), "outcome": "unknown"})
            self._save()

    def finish(self, operation_id: str, outcome: str, *, elapsed_s: float = 0) -> None:
        with self._lock:
            attempt = next(a for a in self.state["attempts"] if a["operation_id"] == operation_id)
            if attempt["outcome"] != "unknown":
                raise BudgetError("attempt already has an outcome")
            if not math.isfinite(elapsed_s) or elapsed_s < 0:
                raise BudgetError("invalid activity duration")
            attempt.update(outcome=outcome, elapsed_s=elapsed_s)
            if attempt["kind"] == "target":
                self.state["activity_s"] += elapsed_s
                if elapsed_s > self.limits["activity_per_call_s"] or self.state["activity_s"] >= self.limits["activity_total_s"]:
                    self.state["stopped"] = "activity budget exceeded; upstream stop unverified"
            if outcome not in {"completed", "retained", "cleaned"}:
                self.state["stopped"] = outcome
            self._save()
