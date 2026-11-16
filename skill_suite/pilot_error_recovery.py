"""Read-only state reconciliation and cleanup after a terminal pilot row error."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from sweep import runtime
from .pilot_runtime import _call_limits, _verify_run, LiveTransport


def reconcile(root: Path, run: Path, case_id: str, row_id: str) -> dict:
    _manifest, master, ledger = _verify_run(root, run)
    worker = next((row for row in master["workers"] if row["case_id"] == case_id), None)
    if worker is None:
        raise ValueError("pilot worker missing")
    case = json.loads(Path(worker["case_file"]).read_text())
    row_dir = run / case_id / row_id
    result_path = row_dir / "row-result.json"
    result = json.loads(result_path.read_text())
    if (not result.get("status", "").startswith("target-error")
            or (row_dir / "error-recovery.json").exists()):
        raise ValueError("one unreconciled terminal pilot row error required")
    binding = json.loads((row_dir / "binding.json").read_text())
    with runtime.sweep_lock(root) as lease:
        runtime.require_free_shim_port()
        transport = LiveTransport(root, run, case_id, lease, ledger)
        try:
            limits = _call_limits(case)
            path = "/api/sessions/" + quote(binding["session_id"], safe="") + "/artifacts"
            artifacts = transport.json_request(row_dir, row_id, limits,
                "error-recovery-artifacts", "GET", path, kind="recovery")
            observed = []
            ids = []
            for index, item in enumerate(artifacts.get("artifacts", [])):
                if item.get("scope_id") != binding["session_id"] or not item.get("id"):
                    raise ValueError("error recovery artifact identity drift")
                ids.append(item["id"])
                token = item.get("file_token")
                body_hash = None
                if token:
                    body = transport.download(row_dir, row_id, limits,
                        "error-recovery-download-" + str(index).zfill(2), token)
                    body_hash = hashlib.sha256(body).hexdigest()
                observed.append({"artifact_id": item["id"], "filename": item.get("filename"),
                                 "content_sha256": body_hash})
            if ids:
                transport.json_request(row_dir, row_id, limits, "error-recovery-cleanup",
                    "DELETE", path, {"ids": ids}, kind="cleanup")
            restored = transport.json_request(row_dir, row_id, limits,
                "error-recovery-restored", "GET", path, kind="recovery")
            if restored.get("artifacts"):
                raise ValueError("error recovery did not restore empty artifact state")
        finally:
            transport.close()
    recovery = {"kind": "skill-pilot-error-recovery", "case_id": case_id,
        "row_id": row_id, "target_resubmitted": False, "question_answered": False,
        "observed_artifacts": observed, "cleanup_count": len(ids),
        "restored_empty": True, "actual_calls": ledger.case_counts(case_id),
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(row_dir / "error-recovery.json", recovery)
    result["error_recovery_ref"] = {"file": "error-recovery.json",
        "sha256": runtime.sha256_file(row_dir / "error-recovery.json")}
    result["post_error_effect_observed"] = bool(observed)
    runtime.write_json(result_path, result)
    return recovery


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--row-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(reconcile(args.root.resolve(), args.run.resolve(), args.case_id, args.row_id),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
