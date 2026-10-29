"""Standing pilot budget continues after row errors but blocks retries and unknown terminals."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from skill_suite.pilot_ledger import PilotBudgetError, PilotLedger


LIMITS = {"target": 3, "management": 5, "recovery": 2, "cleanup": 2,
          "generation": 0, "judge": 0, "retry": 0}


class PilotLedgerContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.json"
        self.ledger = PilotLedger(self.path, LIMITS)

    def test_row_error_is_soft_but_retry_and_generation_are_blocked(self):
        self.ledger.reserve("target", "target:a")
        self.ledger.bind("target:a", case_id="case-a", row_id="row-a")
        self.ledger.finish("target:a", "target-error")
        self.ledger.stop("case-a target error")
        self.ledger.reserve("target", "target:b")
        with self.assertRaises(PilotBudgetError): self.ledger.reserve("target", "target:a")
        with self.assertRaises(PilotBudgetError): self.ledger.reserve("generation", "generation:a")
        self.assertEqual(self.ledger.case_counts("case-a")["target"], 1)

    def test_pending_terminal_blocks_targets_until_budgeted_recovery(self):
        self.ledger.reserve("target", "target:a")
        self.ledger.bind("target:a", case_id="case-a", row_id="row-a")
        self.ledger.finish("target:a", "unknown-terminal")
        self.ledger.mark_pending("run-a", "chat:usr:a", "target:a")
        with self.assertRaisesRegex(PilotBudgetError, "recovery"):
            self.ledger.reserve("target", "target:b")
        self.ledger.reserve("recovery", "recover:a")
        self.ledger.bind("recover:a", case_id="case-a", row_id="row-a")
        self.ledger.finish("recover:a", "completed")
        self.ledger.resolve_pending("run-a", "chat:usr:a",
                                    evidence_ref={"file": "live.json", "sha256": "a" * 64})
        self.ledger.reserve("target", "target:b")
        self.assertEqual(self.ledger.state["counts"]["management"], 1)
        self.assertEqual(self.ledger.state["counts"]["recovery"], 1)


if __name__ == "__main__":
    unittest.main()
