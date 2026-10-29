"""Metered, one-shot byte readback for an observed general session artifact.

The caller owns the project lock, session/resource registry and approved budget.
This function has no retry, refresh or target path. It preserves only hashes of
capability and authorization material in its local receipt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from sweep.runtime import sha256_file, utc_now, write_json
from .budget import Ledger
from .http_accounting import meter_client
from .schema import identifier, text_hash


def download_artifact(service: Any, ledger: Ledger, run: Path, receipt_name: str,
                      *, session_id: str, artifact_id: str, filename: str,
                      file_token: str) -> tuple[bytes, dict[str, Any]]:
    """Fetch bounded raw bytes from the exact endpoint observed in B5."""
    identifier(receipt_name, "download receipt")
    identifier(session_id, "session_id")
    identifier(artifact_id, "artifact_id")
    identifier(filename, "filename")
    if not isinstance(file_token, str) or not file_token:
        raise ValueError("listed file capability required")
    if not session_id.startswith("chat:") or not isinstance(service._client, httpx.Client):
        raise ValueError("native general session and metered httpx client required")
    base = service.config.upstream_base_url
    url = urlsplit(base)
    if url.scheme != "https" or not url.netloc or url.query or url.fragment:
        raise ValueError("approved HTTPS Genius origin required")
    receipt_path = run / (receipt_name + ".json")
    body_path = run / (receipt_name + ".bin")
    if receipt_path.exists() or body_path.exists() or not run.is_dir():
        raise ValueError("new owned download receipt/body paths required; no retry")
    receipt: dict[str, Any] = {"kind": "session-artifact-download",
        "environment": "live", "session_id": session_id, "artifact_id": artifact_id,
        "filename": filename, "endpoint": "/api/files/download",
        "query_keys": ["token", "auth_token"], "file_token_sha256": text_hash(file_token),
        "observed_at": utc_now(), "http_status": None, "content_sha256": None,
        "body_ref": None, "bytes": None, "status": "reserved"}
    write_json(receipt_path, receipt)
    records: list[dict[str, Any]] = []
    try:
        with meter_client(service._client, ledger, "download:" + receipt_name) as records:
            with service._client.stream("GET", base.rstrip("/") + "/api/files/download",
                    params={"token": file_token, "auth_token": service.credentials.raw_token},
                    headers=service._headers(), follow_redirects=False) as response:
                receipt["http_status"] = response.status_code
                if response.status_code != 200:
                    raise ValueError("artifact byte readback HTTP status mismatch")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 4096:
                        raise ValueError("artifact byte readback exceeds small synthetic scope")
        if not data:
            raise ValueError("artifact byte readback is empty")
        body_path.write_bytes(data)
        digest = sha256_file(body_path)
        receipt.update(status="completed", content_sha256=digest,
                       body_ref={"file": body_path.name, "sha256": digest}, bytes=len(data),
                       http_attempts=records)
        write_json(receipt_path, receipt)
        return bytes(data), receipt
    except Exception as exc:
        ledger.stop("artifact-download-error:" + type(exc).__name__)
        receipt.update(status="error", error_type=type(exc).__name__, http_attempts=records)
        write_json(receipt_path, receipt)
        raise
