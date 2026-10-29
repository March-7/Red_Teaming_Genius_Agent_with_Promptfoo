"""Build and verify a non-executable multi-risk formal start bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file, write_json
from .multi_risk_formal import provisioning_plan, validate_plan


def _ref(path: Path) -> dict[str, str]:
    return {"file": str(path.resolve()), "sha256": sha256_file(path)}


def prepare(plan_path: Path, pilot_summary_path: Path, source_registry_path: Path,
            risk_card_index_path: Path, case_registry_path: Path, review_index_path: Path,
            output: Path, *, budget: dict[str, int]) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new multi-risk formal bundle directory required")
    checked = validate_plan(plan_path)
    plan = json.loads(plan_path.read_text())
    pilots = json.loads(pilot_summary_path.read_text())
    if pilots.get("kind") == "genius-skill-ten-risk-prevalidation-summary":
        eligible = pilots.get("eligible_risk_families")
        pilot_gate = pilots.get("breadth_formal_gate")
        pilot_kind_valid = (plan.get("schema_version") == 2
            and plan.get("prevalidation_summary_sha256") == sha256_file(pilot_summary_path))
    else:
        eligible = pilots.get("formal_eligible_risk_families",
                              pilots.get("formal_eligible_case_ids"))
        pilot_gate = pilots.get("formal_portfolio_gate")
        pilot_kind_valid = pilots.get("kind") == "genius-skill-multi-risk-pilot-summary"
    eligible_count_valid = (isinstance(eligible, list)
        and ((4 <= len(eligible) <= 6) if plan.get("schema_version") == 1
             else (6 <= len(eligible) <= 10)))
    if (not pilot_kind_valid or pilot_gate != "passed" or not eligible_count_valid
            or set(plan["risk_families"]) != set(eligible)):
        raise ValueError("real pilot-eligible risk families required before formal bundle")
    cases = json.loads(case_registry_path.read_text())
    reviews = json.loads(review_index_path.read_text())
    breadth = plan.get("schema_version") == 2
    expected_case_kind = ("skill-breadth-formal-case-index" if breadth
                          else "skill-multi-risk-formal-case-index")
    expected_case_status = ("codex-reviewed-user-pending" if breadth
                            else "reviewed-frozen")
    expected_review_kind = ("skill-breadth-formal-review-index" if breadth
                            else "skill-multi-risk-formal-review-index")
    if (plan.get("source_registry_sha256") != sha256_file(source_registry_path)
            or plan.get("risk_cards_sha256") != sha256_file(risk_card_index_path)
            or plan.get("pilot_summary_sha256") != sha256_file(pilot_summary_path)
            or cases.get("kind") != expected_case_kind
            or cases.get("status") != expected_case_status
            or cases.get("case_count") != checked["case_count"]
            or cases.get("formal_target_authorized") is not False
            or reviews.get("kind") != expected_review_kind
            or reviews.get("reviewed_count") != checked["case_count"]
            or reviews.get("accepted_count") != checked["case_count"]):
        raise ValueError("formal source, case registry or review index drift")
    required_budget = {"target", "management", "recovery", "cleanup", "generation", "judge", "retry"}
    if (set(budget) != required_budget or budget["target"] != checked["target_row_count"]
            or any(type(value) is not int or value < 0 for value in budget.values())
            or budget["generation"] != 0 or budget["retry"] != 0):
        raise ValueError("explicit zero-generation/zero-retry formal budget required")
    provision = provisioning_plan(plan_path)
    output.mkdir()
    write_json(output / "provisioning-plan.json", provision)
    bundle_status = ("ready-for-user-case-review" if breadth
                     else "ready-to-request-formal-start")
    bundle = {"schema_version": 1, "kind": "skill-multi-risk-formal-start-bundle",
        "status": bundle_status, "execution_enabled": False,
        "evaluation_stage": "formal-prepared", "target_context": "global-general",
        "portfolio_mode": checked["portfolio_mode"],
        "risk_family_count": checked["risk_family_count"], "risk_families": plan["risk_families"],
        "case_count": checked["case_count"], "target_row_count": checked["target_row_count"],
        "family_cases": checked["family_cases"], "source_cases": checked["source_cases"],
        "formal_plan_ref": _ref(plan_path), "pilot_summary_ref": _ref(pilot_summary_path),
        "source_registry_ref": _ref(source_registry_path),
        "risk_card_index_ref": _ref(risk_card_index_path),
        "case_registry_ref": _ref(case_registry_path),
        "review_index_ref": _ref(review_index_path),
        "provisioning_plan_ref": _ref(output / "provisioning-plan.json"),
        "budget": budget, "data_flow": {"genius": "frozen synthetic tasks, private Skills and run-owned resources",
            "judge": "guarded outputs and deterministic oracle summary only",
            "credentials_or_raw_management_receipts_externalized": False},
        "cleanup": {"scope": "run-owned-resources-only", "non_owned_resources": 0},
        "target_calls": 0, "judge_calls": 0, "formal_start_authorized": False,
        "judge_authorized": False, "stop_condition": (
            "user case review and separate exact-bundle target authorization required"
            if breadth else "separate exact-bundle target authorization required")}
    write_json(output / "formal-start-bundle.json", bundle)
    write_json(output / "formal-start-authorization.json", {"status": "not-authorized",
        "bundle_sha256": sha256_file(output / "formal-start-bundle.json")})
    write_json(output / "judge-authorization.json", {"status": "not-authorized",
        "bundle_sha256": sha256_file(output / "formal-start-bundle.json")})
    return verify(output)


def verify(output: Path) -> dict[str, Any]:
    bundle_path = output / "formal-start-bundle.json"
    supersession_path = output / "supersession.json"
    if supersession_path.exists():
        supersession = json.loads(supersession_path.read_text())
        common = (supersession.get("schema_version") == 1
            and supersession.get("kind") == "skill-formal-bundle-supersession"
            and supersession.get("prior_bundle_sha256") == sha256_file(bundle_path)
            and supersession.get("formal_target_calls") == 0
            and supersession.get("judge_calls") == 0)
        if supersession.get("status") == "superseded-for-stage-e":
            expected_fields = {"schema_version", "kind", "status", "prior_bundle_sha256",
                "replacement_stage", "stage_master_sha256", "stage_authorization_sha256",
                "formal_target_calls", "judge_calls"}
            valid = (set(supersession) == expected_fields and common
                and supersession.get("replacement_stage") == "stage-e-ten-risk-prevalidation")
            message = "multi-risk formal bundle superseded for stage E"
        elif supersession.get("status") == "superseded-for-source-complete-rescreen":
            expected_fields = {"schema_version", "kind", "status", "prior_bundle_sha256",
                "replacement_stage", "source_registry_sha256", "category_catalogue_sha256",
                "dual_screening_sha256", "formal_target_calls", "judge_calls"}
            base = output.parent
            valid = (set(supersession) == expected_fields and common
                and supersession.get("replacement_stage") == "source-complete-dual-gate-review"
                and supersession.get("source_registry_sha256") == sha256_file(
                    base / "source-registry.json")
                and supersession.get("category_catalogue_sha256") == sha256_file(
                    base / "source-category-catalogue.json")
                and supersession.get("dual_screening_sha256") == sha256_file(
                    base / "dual-gate-screening.json"))
            message = "multi-risk formal bundle superseded for source-complete rescreen"
        else:
            valid, message = False, "invalid formal bundle supersession evidence"
        if not valid:
            raise ValueError("invalid formal bundle supersession evidence")
        raise ValueError(message)
    bundle = json.loads(bundle_path.read_text())
    target_auth = json.loads((output / "formal-start-authorization.json").read_text())
    judge_auth = json.loads((output / "judge-authorization.json").read_text())
    expected_status = ("ready-for-user-case-review"
                       if bundle.get("portfolio_mode") == "breadth-first"
                       else "ready-to-request-formal-start")
    if (bundle.get("kind") != "skill-multi-risk-formal-start-bundle"
            or bundle.get("status") != expected_status
            or bundle.get("execution_enabled") is not False
            or bundle.get("target_calls") != 0 or bundle.get("judge_calls") != 0
            or bundle.get("formal_start_authorized") is not False
            or bundle.get("judge_authorized") is not False
            or not 4 <= bundle.get("risk_family_count", 0) <= 10
            or (bundle.get("portfolio_mode") == "breadth-first"
                and not 6 <= bundle.get("risk_family_count", 0) <= 10)
            or bundle.get("target_row_count") != bundle.get("budget", {}).get("target")
            or bundle.get("budget", {}).get("generation") != 0
            or bundle.get("budget", {}).get("retry") != 0
            or bundle.get("cleanup", {}).get("non_owned_resources") != 0):
        raise ValueError("multi-risk formal bundle execution or budget boundary drift")
    for key in ("formal_plan_ref", "pilot_summary_ref", "source_registry_ref",
                "risk_card_index_ref", "case_registry_ref", "review_index_ref",
                "provisioning_plan_ref"):
        ref = bundle[key]
        path = Path(ref["file"])
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError("multi-risk bundle source hash drift")
    expected = {"status": "not-authorized", "bundle_sha256": sha256_file(bundle_path)}
    if target_auth != expected or judge_auth != expected:
        raise ValueError("target and Judge must remain separately not-authorized")
    return {"verified": True, "status": bundle["status"],
        "risk_family_count": bundle["risk_family_count"], "case_count": bundle["case_count"],
        "target_row_count": bundle["target_row_count"], "target_calls": 0, "judge_calls": 0,
        "formal_start_authorized": False, "judge_authorized": False,
        "bundle_sha256": sha256_file(bundle_path)}


def reject_execution(output: Path) -> None:
    verify(output)
    raise ValueError("multi-risk formal bundle is prepared but target execution is not authorized")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "reject-execution"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--pilot-summary", type=Path)
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--risk-card-index", type=Path)
    parser.add_argument("--case-registry", type=Path)
    parser.add_argument("--review-index", type=Path)
    parser.add_argument("--budget-json")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if not all((args.plan, args.pilot_summary, args.source_registry,
                    args.risk_card_index, args.case_registry, args.review_index,
                    args.budget_json)):
            raise ValueError("prepare requires plan, pilot/source/risk/case/review refs and budget JSON")
        result = prepare(args.plan, args.pilot_summary, args.source_registry,
                         args.risk_card_index, args.case_registry, args.review_index,
                         args.output, budget=json.loads(args.budget_json))
    elif args.command == "verify": result = verify(args.output)
    else:
        reject_execution(args.output)
        raise AssertionError("unreachable")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
