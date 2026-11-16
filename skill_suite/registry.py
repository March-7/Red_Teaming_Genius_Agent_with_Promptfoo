"""Interface attestation, content identity and append-only resource ownership."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit
from sweep.resource_naming import validate_neutral_resource_name
from sweep.runtime import utc_now
from .evidence import append_row, read_ref, read_rows
from .schema import content_hash, identifier, logical_scope_id, resource_identifier

OPERATIONS = ("import", "bind", "read", "cleanup")
CATALOGUE_OPERATIONS = ("import", "selection-intent", "read", "cleanup")


def validate_interface(row: dict[str, Any], root: Path, *, live: bool = True) -> None:
    required = {"schema_version", "attestation_id", "environment", "mode", "observed_at",
                "format", "scope_type", "operations"}
    if set(row) != required or type(row["schema_version"]) is not int or row["schema_version"] not in {1, 2}:
        raise ValueError("invalid interface attestation")
    identifier(row["attestation_id"], "attestation_id")
    scope_type = "private-user-catalogue" if row["schema_version"] == 2 else "private-run-scope"
    operations = CATALOGUE_OPERATIONS if row["schema_version"] == 2 else OPERATIONS
    if row["mode"] not in {"manual-ui", "observed-http"} or row["scope_type"] != scope_type:
        raise ValueError("observed interface with isolated private scope required")
    if live and row["environment"] != "live":
        raise ValueError("offline fixture is not live interface evidence")
    if row["environment"] not in {"live", "offline-fixture"} or not row["observed_at"] or not row["format"]:
        raise ValueError("missing interface provenance")
    if not isinstance(row["operations"], dict) or set(row["operations"]) != set(operations):
        raise ValueError("all lifecycle operations require observed evidence")
    for name, operation in row["operations"].items():
        if set(operation) != {"description", "evidence"} or not operation["description"]:
            raise ValueError("missing operation observation")
        proof = read_ref(root, operation["evidence"])
        if (proof.get("operation") != name or proof.get("environment") != row["environment"]
                or proof.get("attestation_id") != row["attestation_id"] or proof.get("observed") is not True):
            raise ValueError("operation evidence does not match attestation")


def validate_skill(row: dict[str, Any], root: Path, case: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("environment") not in {"live", "offline-fixture"}:
        raise ValueError("unknown Skill evidence origin")
    for key in ("run_id", "case_id", "model_profile", "variant", "scope_id", "skill_id", "skill_version", "skill_hash", "asset_hash"):
        if row.get(key) != case.get(key):
            raise ValueError("Skill registry identity mismatch: " + key)
    catalogue = case.get("target_context") == "global-general"
    if catalogue:
        if row.get("registration_kind") != "private-user-catalogue" or "binding_scope_id" in row or "bind_evidence" in row:
            raise ValueError("general Skill requires catalogue registration, not a Project binding")
    elif row.get("binding_scope_id") != case["scope_id"]:
        raise ValueError("Skill binding scope mismatch")
    for key in ("skill_hash", "asset_hash"):
        content_hash(row[key], key)
    from sweep.runtime import sha256_file
    from .evidence import local_file
    if sha256_file(local_file(root, row["artifact_file"])) != row["asset_hash"]:
        raise ValueError("original Skill artifact changed")
    if sha256_file(local_file(root, row["imported_file"])) != row["skill_hash"]:
        raise ValueError("imported Skill content changed")
    if row["asset_hash"] != row["skill_hash"] and not row.get("conversion_evidence"):
        raise ValueError("platform conversion evidence required")
    if row.get("conversion_evidence"):
        conversion = read_ref(root, row["conversion_evidence"])
        if conversion.get("original_hash") != row["asset_hash"] or conversion.get("imported_hash") != row["skill_hash"]:
            raise ValueError("conversion hashes do not match")
    for operation in (("import",) if catalogue else ("import", "bind")):
        proof = read_ref(root, row[operation + "_evidence"])
        if (proof.get("operation") != operation or proof.get("skill_id") != row["skill_id"]
                or ("scope_id" in proof if catalogue else proof.get("scope_id") != row["scope_id"])
                or proof.get("skill_hash") != row["skill_hash"]
                or proof.get("environment") != row.get("environment") or proof.get("success") is not True):
            raise ValueError("Skill " + operation + " evidence mismatch")
    if catalogue:
        catalogue_proof = read_ref(root, row["catalogue_evidence"])
        if (catalogue_proof.get("operation") != "catalogue-readback"
                or catalogue_proof.get("environment") != row["environment"]
                or catalogue_proof.get("skill_id") != case["skill_id"]
                or catalogue_proof.get("skill_version") != case["skill_version"]
                or catalogue_proof.get("skill_hash") != case["skill_hash"]
                or catalogue_proof.get("visibility") != "private"
                or catalogue_proof.get("scope_type") != "user"
                or not catalogue_proof.get("principal_id")
                or catalogue_proof.get("owner_id") != catalogue_proof["principal_id"]
                or catalogue_proof.get("shared") is not False):
            raise ValueError("private catalogue identity/owner/content proof mismatch")
        receipts = [read_ref(root, ref) for ref in catalogue_proof.get("raw_refs", [])]
        if not catalogue_proof.get("raw_refs"):
            raise ValueError("catalogue raw readback required")
        base_path = "/api/skills/" + quote(case["skill_id"], safe="")
        def body_for(path):
            matches = [r for r in receipts if r.get("request", {}).get("method") == "GET"
                       and r["request"].get("path") == path and r.get("response", {}).get("status") == 200]
            if len(matches) != 1:
                raise ValueError("unique actual catalogue HTTP readback required")
            return matches[0]["response"]["body"]
        metadata = body_for(base_path).get("skill", {})
        sharing = body_for(base_path + "/sharing")
        from .schema import text_hash
        if (metadata.get("skill_id") != case["skill_id"] or metadata.get("name") != case["resource_name"]
                or metadata.get("owner_id") != catalogue_proof["principal_id"] or metadata.get("source") != "user"
                or metadata.get("visibility") != "private" or metadata.get("mode") != "text"
                or metadata.get("shared_with_count") != 0 or metadata.get("scripts") or metadata.get("needs_credentials")
                or str(metadata.get("version")) != case["skill_version"]
                or text_hash(metadata.get("instructions", "")) != case["skill_hash"]
                or sharing.get("skill_id") != case["skill_id"] or sharing.get("scope") != "private"
                or sharing.get("members") != []):
            raise ValueError("actual catalogue response contradicts private identity/content proof")
        intent = read_ref(root, row["selection_intent_evidence"])
        expected = {"operation": "selection-intent", "run_id": case["run_id"], "case_id": case["case_id"],
                    "session_id": case["session_id"], "resource_scope_id": case["scope_id"],
                    "target_context": "global-general", "locator": case["resource_name"],
                    "skill_id": case["skill_id"], "skill_version": case["skill_version"],
                    "skill_hash": case["skill_hash"], "task_hash": case["task_hash"],
                    "environment": row["environment"], "runtime_binding_claim": False}
        if intent != expected:
            raise ValueError("catalogue selection intent differs from pinned case")
    from .provenance import validate_runtime_asset
    return validate_runtime_asset(root, row)


def validate_absent_locator(row: dict[str, Any], root: Path, case: dict[str, Any], *, live: bool = True) -> None:
    """Prove the requested locator was absent from a complete catalogue query."""
    for key in ("run_id", "case_id", "model_profile", "resource_name", "task_hash"):
        if row.get(key) != case[key]:
            raise ValueError("absent locator identity mismatch")
    if row.get("environment") not in {"live", "offline-fixture"} or (live and row["environment"] != "live"):
        raise ValueError("absent locator requires live catalogue evidence")
    receipt = read_ref(root, row["catalogue_query_evidence"])
    request, response = receipt.get("request", {}), receipt.get("response", {})
    url = urlsplit(request.get("path", ""))
    body = response.get("body", {})
    if (request.get("method") != "GET" or url.scheme or url.netloc or url.path != "/api/skills"
            or parse_qs(url.query).get("q") != [case["resource_name"]]
            or response.get("status") != 200 or body.get("skills") != []
            or type(body.get("total")) is not int or body["total"] != 0):
        raise ValueError("complete empty catalogue query for exact absent locator required")


class ResourceRegistry:
    def __init__(self, path: Path, run_id: str):
        identifier(run_id, "run_id")
        self.path, self.run_id = path, run_id
        self.rows = read_rows(path) if path.exists() else []
        if any(row.get("run_id") != run_id for row in self.rows):
            raise ValueError("resource registry belongs to another run")

    def record(self, resource_id: str, kind: str, name: str, state: str, **details: Any) -> None:
        resource_identifier(resource_id)
        if kind not in {"skill", "scope", "session"}:
            raise ValueError("unknown resource kind")
        validate_neutral_resource_name(name)
        row = {**details, "run_id": self.run_id, "resource_id": resource_id, "kind": kind,
               "name": name, "state": state, "timestamp": utc_now()}
        append_row(self.path, row)
        self.rows.append(row)

    def record_logical_scope(self, case_id: str, name: str) -> str:
        """Record an A-only partition without creating a platform resource."""
        scope_id = logical_scope_id(self.run_id, case_id)
        if any(row["resource_id"] == scope_id for row in self.rows):
            raise ValueError("logical scope already registered")
        self.record(scope_id, "scope", name, "created", owner_run_id=self.run_id,
                    shared=False, scope_kind="logical-case-partition", native_platform_resource=False)
        return scope_id

    def owned(self, resource_id: str) -> dict[str, Any]:
        rows = [row for row in self.rows if row["resource_id"] == resource_id]
        if not rows or rows[-1].get("owner_run_id") != self.run_id or rows[-1].get("shared") is not False:
            raise ValueError("resource is not registered as exclusively owned")
        if rows[-1]["state"] == "cleaned":
            raise ValueError("resource already cleaned; no repeated mutation")
        return rows[-1]
