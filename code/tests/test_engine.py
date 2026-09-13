from __future__ import annotations

import csv
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parents[1]
ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from buy_or_wait.engine import DecisionEngine, OUTPUT_COLUMNS  # noqa: E402
from buy_or_wait.evidence import (  # noqa: E402
    parse_confirmed_incomes,
    parse_salary_evidence,
)
from buy_or_wait.models import Message, SpendingChange  # noqa: E402
from buy_or_wait.validation import validate_decisions, validate_input_dataset  # noqa: E402


TEST_IMAGE_AMOUNTS = {
    "image_01": Decimal("4365000"), "image_02": Decimal("100000"),
    "image_03": Decimal("41272"), "image_04": Decimal("2854"),
    "image_05": Decimal("704.05"), "image_06": Decimal("1995"),
    "image_07": Decimal("8528.10"), "image_08": Decimal("15339"),
    "image_09": Decimal("723"), "image_10": Decimal("79679.26"),
    "image_11": Decimal("3650"), "image_12": Decimal("33.50"),
    "image_13": Decimal("2298"), "image_14": Decimal("4593"),
    "image_15": Decimal("9968"), "image_16": Decimal("393.22"),
}


class FixtureEvidenceResolver:
    """Deterministic test double; production always uses an online provider."""

    def extract_image_amount(self, image_path: Path, event: dict[str, str]) -> Decimal:
        del event
        return TEST_IMAGE_AMOUNTS[image_path.stem]

    def normalize_messages(self, messages: list[Message]) -> list[Message]:
        return messages


class DecisionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = ROOT / "dataset"
        cls.engine = DecisionEngine.from_directory(cls.dataset, FixtureEvidenceResolver())

    def test_all_image_backed_amounts_are_available(self) -> None:
        with (self.dataset / "images.csv").open(encoding="utf-8-sig", newline="") as fh:
            image_ids = {row["image_id"] for row in csv.DictReader(fh)}
        self.assertEqual(image_ids, set(TEST_IMAGE_AMOUNTS))

    def test_public_sample_method_accuracy_is_high(self) -> None:
        sample_path = self.dataset / "sample_requests.csv"
        decisions = {item.request_id: item for item in self.engine.run(sample_path)}
        with sample_path.open(encoding="utf-8-sig", newline="") as fh:
            truth = list(csv.DictReader(fh))
        method_matches = sum(
            decisions[row["request_id"]].recommended_payment_method
            == row["recommended_payment_method"]
            for row in truth
        )
        status_matches = sum(
            decisions[row["request_id"]].affordability_status
            == row["affordability_status"]
            for row in truth
        )
        self.assertGreaterEqual(method_matches, 24)
        self.assertGreaterEqual(status_matches, 24)

    def test_full_output_has_exact_contract(self) -> None:
        decisions = self.engine.run(self.dataset / "requests.csv")
        self.assertEqual(250, len(decisions))
        target = Path(__file__).resolve().parent / "_test_output.csv"
        try:
            self.engine.write_output(decisions, target)
            with target.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
            self.assertEqual(OUTPUT_COLUMNS, reader.fieldnames)
            self.assertEqual(250, len(rows))
            self.assertEqual(250, len({row["request_id"] for row in rows}))
        finally:
            target.unlink(missing_ok=True)

    def test_input_and_submission_validation_cover_full_dataset(self) -> None:
        dimensions = validate_input_dataset(self.dataset, "requests.csv")
        self.assertEqual(250, dimensions.rows["requests.csv"])
        self.assertEqual(25342, dimensions.rows["financial_events.csv"])
        requests = self.engine.load_requests(self.dataset / "requests.csv")
        validate_decisions(self.engine.run(self.dataset / "requests.csv"), requests)

    def test_earliest_full_payment_never_precedes_request(self) -> None:
        requests = {
            row.request_id: row
            for row in self.engine.load_requests(self.dataset / "requests.csv")
        }
        for decision in self.engine.run(self.dataset / "requests.csv"):
            if decision.earliest_date_for_full_payment:
                self.assertGreaterEqual(
                    date.fromisoformat(decision.earliest_date_for_full_payment),
                    requests[decision.request_id].request_date,
                    decision.request_id,
                )

    def test_protected_priorities_are_never_offered_as_spending_changes(self) -> None:
        for request in self.engine.load_requests(self.dataset / "requests.csv"):
            profile = self.engine.profiles[request.user_id]
            _, changes = self.engine._build_forecast(request)
            protected = profile.protected_categories | profile.priorities
            self.assertFalse(
                [change.text for change in changes if change.category in protected],
                request.request_id,
            )

    def test_scheduled_school_fee_is_reserved_before_purchase(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "sample_requests.csv")
            if item.request_id == "request_04"
        )
        forecast, _ = self.engine._build_forecast(request)
        school_fees = [flow for flow in forecast.flows if flow.event_id == "event_357"]
        self.assertEqual(1, len(school_fees))
        self.assertEqual(Decimal("-1704300"), school_fees[0].amount)

    def test_explanation_names_reserved_essential_commitments(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "sample_requests.csv")
            if item.request_id == "request_11"
        )
        explanation = self.engine.decide(request).decision_explanation
        self.assertIn("education fees", explanation)
        self.assertIn("housing costs", explanation)
        self.assertIn("normal monthly spending", explanation)

    def test_approved_invoice_message_becomes_one_confirmed_credit(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "requests.csv")
            if item.request_id == "request_26"
        )
        forecast, _ = self.engine._build_forecast(request)
        credits = [flow for flow in forecast.flows if flow.event_id == "message_18"]
        self.assertEqual(1, len(credits))
        self.assertEqual(Decimal("30780000"), credits[0].amount)
        self.assertEqual(date(2025, 8, 15), credits[0].flow_date)

    def test_payroll_arrears_are_counted_once(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "requests.csv")
            if item.request_id == "request_28"
        )
        forecast, _ = self.engine._build_forecast(request)
        arrears = [
            flow for flow in forecast.flows
            if flow.event_id == "message_salary_arrears"
        ]
        self.assertEqual(1, len(arrears))
        self.assertEqual(Decimal("653.40"), arrears[0].amount)

    def test_foreign_salary_and_one_time_arrears_are_distinguished(self) -> None:
        message = Message(
            message_id="m", user_id="u", request_id=None,
            related_event_id=None, sent_at="2026-01-01T00:00:00Z",
            source_type="employer",
            text=(
                "Regular salary for the next payroll is USD 1000. "
                "The same payroll includes a one-time arrears adjustment of USD 250."
            ),
        )
        evidence = parse_salary_evidence([message])
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(Decimal("1000"), evidence.amount)
        self.assertEqual("USD", evidence.currency)
        self.assertEqual(Decimal("250"), evidence.one_time_amount)
        self.assertFalse(evidence.next_only)

    def test_unconfirmed_provider_payout_is_not_income(self) -> None:
        message = Message(
            message_id="m", user_id="u", request_id=None,
            related_event_id=None, sent_at="2026-01-01T00:00:00Z",
            source_type="service_provider",
            text=(
                "The next payout is still pending. The balance is not withdrawable "
                "until it shows as completed."
            ),
        )
        self.assertEqual([], parse_confirmed_incomes([message]))

    def test_indonesian_employment_end_stops_salary(self) -> None:
        message = Message(
            message_id="m", user_id="u", request_id=None,
            related_event_id=None, sent_at="2026-01-01T00:00:00Z",
            source_type="employer",
            text="Hubungan kerja Anda telah berakhir. Tidak ada pembayaran gaji rutin.",
        )
        evidence = parse_salary_evidence([message])
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertTrue(evidence.stopped)

    def test_remaining_household_salary_replaces_ended_income(self) -> None:
        message = Message(
            message_id="m", user_id="u", request_id=None,
            related_event_id=None, sent_at="2026-01-01T00:00:00Z",
            source_type="employer",
            text=(
                "One household employment record has ended. The remaining confirmed "
                "monthly salary is INR 148000.\nNormalized evidence: employment has ended; "
                "Remaining confirmed monthly salary is INR 148000 after one household "
                "employment ended."
            ),
        )
        evidence = parse_salary_evidence([message])
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertFalse(evidence.stopped)
        self.assertEqual(Decimal("148000"), evidence.amount)

    def test_irregular_flexible_budget_uses_latest_category_evidence(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "sample_requests.csv")
            if item.request_id == "request_11"
        )
        _, changes = self.engine._build_forecast(request)
        dining = [change for change in changes if change.category == "dining"]
        self.assertEqual(["reduce_to:event_989:665950"], [item.text for item in dining])

    def test_fractional_spending_change_keeps_currency_precision(self) -> None:
        change = SpendingChange(
            "reduce_to", "event_x", Decimal("47"), Decimal("23.5"), "streaming"
        )
        self.assertEqual("reduce_to:event_x:23.50", change.text)

    def test_failed_debit_with_scheduled_retry_is_reserved_once(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "requests.csv")
            if item.request_id == "request_55"
        )
        forecast, _ = self.engine._build_forecast(request)
        ids = [flow.event_id for flow in forecast.flows]
        self.assertEqual(1, ids.count("event_5169"))
        self.assertNotIn("event_5168", ids)

    def test_scheduled_retry_does_not_double_count_failed_debit(self) -> None:
        request = next(
            item
            for item in self.engine.load_requests(self.dataset / "requests.csv")
            if item.user_id == "user_55"
        )
        forecast, _ = self.engine._build_forecast(request)
        retry_flows = [
            flow for flow in forecast.flows
            if flow.event_id in {"event_5168", "event_5169"}
        ]
        self.assertEqual(["event_5169"], [flow.event_id for flow in retry_flows])


if __name__ == "__main__":
    unittest.main()
