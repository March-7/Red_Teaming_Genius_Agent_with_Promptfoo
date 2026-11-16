"""Budgeted lifecycle adapter. A live backend must be supplied after interface confirmation."""
from __future__ import annotations

from pathlib import Path
import secrets
from typing import Any, Protocol

from sweep.resource_naming import validate_neutral_resource_name
from .budget import Ledger
from .registry import ResourceRegistry, validate_interface
from sweep.runtime import RunLease


class ControlPlane(Protocol):
    def provision(self, kind: str, name: str, context: dict[str, Any]) -> dict[str, Any]: ...
    def bind(self, skill_id: str, scope_id: str) -> dict[str, Any]: ...
    def cleanup(self, resource_id: str, kind: str) -> dict[str, Any]: ...
    def inspect(self, resource_id: str, kind: str) -> dict[str, Any]: ...


class FixtureAdapter:
    def __init__(self, backend: ControlPlane, attestation: dict[str, Any], root: Path,
                 registry: ResourceRegistry, ledger: Ledger, *, live: bool = True, project_root: Path | None = None):
        validate_interface(attestation, root, live=live)
        if registry.path.parent.resolve() != root.resolve() or ledger.path.parent.resolve() != root.resolve():
            raise ValueError("registry/ledger must belong to the attested run")
        self.backend, self.registry, self.ledger = backend, registry, ledger
        self.attestation = attestation
        self.project_root = (project_root or root).resolve()
        self.lease: RunLease | None = None

    def under_lock(self, lease: RunLease) -> "FixtureAdapter":
        lease.require_active()
        if lease.root != self.project_root:
            raise RuntimeError("lifecycle lease belongs to another project")
        self.lease = lease
        return self

    def _require_lock(self) -> None:
        if self.lease is None:
            raise RuntimeError("active project run lock required before lifecycle operation")
        self.lease.require_active()

    def provision(self, kind: str, context: dict[str, Any]) -> dict[str, Any]:
        self._require_lock()
        if kind not in {"skill", "scope", "session"}:
            raise ValueError("unknown resource kind")
        latest = {row["resource_id"]: row for row in self.registry.rows if row["kind"] == kind}
        current = {rid for rid, row in latest.items() if row["state"] != "creation-resolved"}
        cap = self.ledger.limits[{"skill": "skills", "scope": "scopes", "session": "sessions"}[kind]]
        if len(current) >= cap:
            raise ValueError("resource cap reached")
        name = "Research Notes " + secrets.token_hex(5)
        validate_neutral_resource_name(name)
        operation = "provision:" + kind + ":" + name
        self.ledger.reserve("management", operation)
        # An intent survives a failed request even when the server returned no id.
        intent = "pending-" + secrets.token_hex(8)
        self.registry.record(intent, kind, name, "creation-pending", owner_run_id=self.registry.run_id, shared=False)
        try:
            result = self.backend.provision(kind, name, {**context, "run_id": self.registry.run_id})
            if result.get("owner_run_id") != self.registry.run_id or result.get("shared") is not False:
                raise ValueError("server resource ownership not confirmed")
            self.registry.record(result["resource_id"], kind, name, "created", **{
                k: result[k] for k in ("owner_run_id", "shared")})
            self.registry.record(intent, kind, name, "creation-resolved", owner_run_id=self.registry.run_id,
                                 shared=False, resolved_id=result["resource_id"])
            self.ledger.finish(operation, "completed")
            return result
        except Exception:
            self.ledger.finish(operation, "provision-error")
            raise

    def bind(self, skill_id: str, scope_id: str) -> None:
        self._require_lock()
        skill, scope = self.registry.owned(skill_id), self.registry.owned(scope_id)
        if skill["kind"] != "skill" or scope["kind"] != "scope":
            raise ValueError("incorrect binding resource kinds")
        operation = "bind:" + skill_id + ":" + scope_id
        self.ledger.reserve("management", operation)
        try:
            result = self.backend.bind(skill_id, scope_id)
            if result != {"skill_id": skill_id, "scope_id": scope_id, "bound": True}:
                raise ValueError("binding response mismatch")
            self.registry.record(skill_id, "skill", skill["name"], "bound", owner_run_id=self.registry.run_id,
                                 shared=False, scope_id=scope_id)
            self.ledger.finish(operation, "completed")
        except Exception:
            self.ledger.finish(operation, "binding-error")
            raise

    def lifecycle(self, resource_id: str, mode: str) -> None:
        self._require_lock()
        row = self.registry.owned(resource_id)
        if row["state"].startswith("creation-"):
            raise ValueError("creation intent needs read-only reconciliation, not deletion")
        if mode not in {"retain", "cleanup"}:
            raise ValueError("explicit lifecycle choice required")
        operation = mode + ":" + resource_id
        self.ledger.reserve("cleanup" if mode == "cleanup" else "recovery" if self.ledger.state["stopped"] else "management", operation)
        try:
            result = (self.backend.cleanup if mode == "cleanup" else self.backend.inspect)(resource_id, row["kind"])
            expected = "absent" if mode == "cleanup" else "present"
            if result.get("resource_id") != resource_id or result.get("state") != expected:
                raise ValueError("lifecycle result unverified")
            if mode == "cleanup":
                self.ledger.reserve("cleanup", operation + ":verify")
                observed = self.backend.inspect(resource_id, row["kind"])
                if observed.get("resource_id") != resource_id or observed.get("state") != "absent":
                    self.ledger.finish(operation + ":verify", "cleanup-readback-error")
                    raise ValueError("cleanup has no independent absent readback")
                self.ledger.finish(operation + ":verify", "completed")
            state = "cleaned" if mode == "cleanup" else "retained"
            self.registry.record(resource_id, row["kind"], row["name"], state,
                                 owner_run_id=self.registry.run_id, shared=False)
            self.ledger.finish(operation, state)
        except Exception:
            self.registry.record(resource_id, row["kind"], row["name"], "lifecycle-error",
                                 owner_run_id=self.registry.run_id, shared=False)
            self.ledger.finish(operation, "cleanup-error")
            raise
