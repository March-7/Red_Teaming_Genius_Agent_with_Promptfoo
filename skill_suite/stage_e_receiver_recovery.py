"""Read one run-owned Promptfoo landing page and recover its exact exfil endpoint."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import httpx

from sweep.runtime import write_json, utc_now
from .pilot_ledger import PilotLedger
from .stage_e_pilot import TOTAL_LIMITS


def recover(root: Path, run: Path, case_id: str, row_id: str) -> dict:
    if case_id != "unrequested-egress-e2" or row_id not in {
            "default-positive", "deepseek-positive"}:
        raise ValueError("stage E receiver recovery is limited to one failed positive row")
    row_dir = run / case_id / row_id
    output = row_dir / "receiver-locator-recovery.json"
    if output.exists():
        raise ValueError("receiver locator recovery already exists")
    binding = json.loads((row_dir / "binding.json").read_text())
    result = json.loads((row_dir / "row-result.json").read_text())
    if result.get("status") != "positive-invalid" or result.get(
            "independent_effect_observed") is not False:
        raise ValueError("failed receiver positive control required")
    url = binding["context"]["receiver_url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "api.promptfoo.app":
        raise ValueError("run-owned Promptfoo landing URL required")
    ledger = PilotLedger(root / "skill-suites/benchmark-multi-risk/runs/pilot-standing-ledger.json",
                         TOTAL_LIMITS)
    operation = run.name + ":" + case_id + ":" + row_id + ":receiver-locator-recovery"
    ledger.reserve("recovery", operation)
    ledger.bind(operation, case_id=case_id, row_id=row_id)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.get(url)
        body = response.text
        matches = re.findall(r"""(?:https://api\.promptfoo\.app)?(/exfil[^\"'<>\s]+)""", body)
        unique = sorted(set(matches))
        receipt = {"kind": "stage-e-receiver-locator-recovery",
            "landing_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "status_code": response.status_code, "body_bytes": len(response.content),
            "body_sha256": hashlib.sha256(response.content).hexdigest(),
            "endpoint_count": len(unique), "endpoint_paths": unique,
            "observed_at": utc_now(), "retry": 0}
        write_json(output, receipt)
        if response.status_code != 200 or len(unique) != 1:
            ledger.finish(operation, "recovery-error", elapsed_s=time.monotonic()-started)
            raise ValueError("one exact exfil endpoint path required")
        endpoint = urljoin(url, unique[0])
        if urlparse(endpoint).netloc != "api.promptfoo.app":
            ledger.finish(operation, "recovery-error", elapsed_s=time.monotonic()-started)
            raise ValueError("exfil endpoint host drift")
        ledger.finish(operation, "completed", elapsed_s=time.monotonic()-started)
        endpoint_file = row_dir / "receiver-endpoint.json"
        write_json(endpoint_file, {"endpoint": endpoint,
            "landing_uuid": binding["receiver_uuid"],
            "eval_id": binding["receiver_eval_id"],
            "recovery_ref": {"file": output.name,
                             "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}})
        return {"recovered": True, "endpoint_path": unique[0].split("?")[0],
                "query_present": "?" in unique[0],
                "actual_calls": ledger.case_counts(case_id)}
    except Exception:
        attempt = ledger._attempt(operation)
        if attempt["outcome"] == "unknown":
            ledger.finish(operation, "recovery-error", elapsed_s=time.monotonic()-started)
        raise


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--row-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(recover(args.root.resolve(), args.run.resolve(), args.case_id, args.row_id),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
