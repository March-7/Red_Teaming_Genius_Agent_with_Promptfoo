"""Account all requests made by the injected Genius client's internal lifecycle."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from typing import Any
import httpx
from .budget import BudgetError, Ledger


@contextmanager
def meter_client(client: Any, ledger: Ledger, target_operation: str, *, fixture: bool = False,
                 management_kind: str = "management"):
    if management_kind not in {"management", "recovery", "cleanup"}:
        raise ValueError("invalid management accounting kind")
    records: list[dict[str, Any]] = []
    if not isinstance(client, httpx.Client):
        if not fixture:
            raise ValueError("metered Genius httpx client required")
        yield records
        return
    sent_target = False
    pending: dict[int, str] = {}

    def before(request: httpx.Request) -> None:
        nonlocal sent_target
        target = request.method == "POST" and request.url.path.rstrip("/").endswith("/chat/stream")
        record = {"method": request.method, "path_sha256": hashlib.sha256(request.url.path.encode()).hexdigest(),
                  "kind": "target" if target else management_kind, "outcome": "unknown"}
        if target:
            if sent_target:
                raise BudgetError("zero retries: hidden target resubmission rejected")
            sent_target = True  # The outer ledger reserved this target before complete().
        else:
            operation = target_operation + ":http:" + str(len(records) + 1)
            ledger.reserve(management_kind, operation)
            pending[id(request)] = operation
        request.extensions["skill_http_record"] = record
        records.append(record)

    def after(response: httpx.Response) -> None:
        record = response.request.extensions.get("skill_http_record")
        if record is not None:
            record["status_code"] = response.status_code
            record["outcome"] = "completed" if response.status_code < 400 else "upstream-http-error"
            if response.status_code >= 400:
                ledger.stop("upstream-http-error; no hidden refresh/retry")
        operation = pending.pop(id(response.request), None)
        if operation:
            ledger.finish(operation, record["outcome"])

    client.event_hooks["request"].append(before)
    client.event_hooks["response"].append(after)
    try:
        yield records
    finally:
        client.event_hooks["request"].remove(before)
        client.event_hooks["response"].remove(after)
        for operation in pending.values():
            ledger.finish(operation, "transport-error")
