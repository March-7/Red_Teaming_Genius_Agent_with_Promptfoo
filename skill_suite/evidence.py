"""Run-local references checked against bytes, never arbitrary paths or URLs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sweep.runtime import sha256_file


def local_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("run-relative evidence path required")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("missing or out-of-run evidence")
    return path


def read_ref(root: Path, ref: dict[str, Any]) -> Any:
    if not isinstance(ref, dict) or set(ref) - {"file", "sha256", "line"}:
        raise ValueError("invalid evidence reference")
    path = local_file(root, ref.get("file"))
    if sha256_file(path) != ref.get("sha256"):
        raise ValueError("evidence hash mismatch")
    if "line" in ref:
        number = ref["line"]
        if type(number) is not int or number < 1:
            raise ValueError("invalid evidence line")
        lines = path.read_text().splitlines()
        if number > len(lines):
            raise ValueError("evidence line missing")
        return json.loads(lines[number - 1])
    return json.loads(path.read_text())


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL rows must be objects")
            rows.append(value)
    return rows


def append_row(path: Path, row: dict[str, Any]) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
