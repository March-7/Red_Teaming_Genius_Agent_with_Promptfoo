"""Session artifact state derived only from a complete first-party listing and bytes."""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any

from .schema import canonical_hash, identifier


def accepted_note_hashes(text: str) -> list[str]:
    """Freeze exact UTF-8 bytes with no terminator or one terminal LF."""
    if not isinstance(text, str) or not text or "\r" in text or "\n" in text:
        raise ValueError("note text must be a nonempty single line without a terminator")
    return sorted(hashlib.sha256(value.encode("utf-8")).hexdigest()
                  for value in (text, text + "\n"))


def _name(item: dict[str, Any]) -> str:
    for key in ("name", "filename", "display_name", "logical_path", "path"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return PurePosixPath(value).name
    raise ValueError("artifact filename absent from first-party list")


def normalize_session_artifacts(payload: Any, *, expected_name: str,
                                downloaded_sha256: str | None = None) -> tuple[dict[str, Any], str, str | None]:
    """Return state, locally derived snapshot digest, and the matched artifact id.

    The digest is deliberately labelled derived; it is not a backend version.
    A matching artifact requires an independently downloaded byte hash.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        raise ValueError("complete session artifacts list required")
    identifier(expected_name, "expected artifact name")
    normalized = []
    for item in payload["artifacts"]:
        if not isinstance(item, dict):
            raise ValueError("artifact entry must be an object")
        artifact_id = identifier(item.get("id"), "artifact id")
        name = _name(item)
        normalized.append({"id": artifact_id, "name": name})
    if len({row["id"] for row in normalized}) != len(normalized):
        raise ValueError("duplicate artifact ids in list")
    matches = [row for row in normalized if row["name"] == expected_name]
    if len(matches) > 1:
        raise ValueError("artifact name is ambiguous")
    match = matches[0] if matches else None
    if match:
        from .schema import content_hash
        content_hash(downloaded_sha256, "independent artifact bytes")
    elif downloaded_sha256 is not None:
        raise ValueError("download bytes have no matching listed artifact")
    other = sorted((row for row in normalized if row is not match), key=lambda row: (row["name"], row["id"]))
    state = {"artifact_state": downloaded_sha256 if match else None, "other_artifacts": other}
    version = "derived-list-sha256:" + canonical_hash(sorted(normalized, key=lambda row: row["id"]))
    return state, version, match["id"] if match else None
