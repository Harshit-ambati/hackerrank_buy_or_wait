"""Input-dataset and prediction-contract validation."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Decision, Request


INPUT_SCHEMAS = {
    "financial_profiles.csv": {
        "user_id", "home_currency", "current_available_balance",
        "minimum_balance_to_keep", "financial_priorities",
        "expense_categories_to_protect", "expense_categories_user_is_willing_to_reduce",
        "expense_categories_user_is_willing_to_stop", "payment_methods_user_will_consider",
        "max_installment_months",
    },
    "financial_events.csv": {
        "event_id", "user_id", "event_type", "description", "category", "direction",
        "amount", "currency", "event_date", "settlement_date", "status",
        "linked_event_id", "flexibility", "minimum_allowed_amount",
    },
    "exchange_rates.csv": {"rate_date", "from_currency", "to_currency", "rate"},
    "request_payment_options.csv": {
        "payment_option_id", "request_id", "payment_method", "payment_amount",
        "number_of_payments", "first_payment_date", "payment_frequency_days",
        "financing_fee", "total_payable_amount",
    },
    "messages.csv": {
        "message_id", "user_id", "request_id", "related_event_id", "sent_at",
        "source_type", "message_text",
    },
    "images.csv": {"image_id", "user_id", "request_id", "related_event_id"},
}
REQUEST_COLUMNS = {
    "request_id", "user_id", "request_date", "request_type", "requested_amount",
    "desired_completion_date", "allows_partial_payment", "request_text",
}
ALLOWED_STATUSES = {
    "affordable_now", "affordable_with_plan", "affordable_later", "not_affordable",
}
ALLOWED_METHODS = {
    "full_payment", "partial_payment", "installments", "wait", "not_recommended",
}


@dataclass(frozen=True)
class DatasetDimensions:
    rows: dict[str, int]

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


def _read(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"Missing required dataset file: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
        return list(reader)


def validate_input_dataset(dataset: Path, requests_name: str) -> DatasetDimensions:
    """Validate schemas, identifiers, and cross-file relationships before inference."""
    dataset = dataset.resolve()
    tables = {
        name: _read(dataset / name, columns)
        for name, columns in INPUT_SCHEMAS.items()
    }
    requests = _read(dataset / requests_name, REQUEST_COLUMNS)
    tables[requests_name] = requests

    profiles = tables["financial_profiles.csv"]
    events = tables["financial_events.csv"]
    options = tables["request_payment_options.csv"]
    messages = tables["messages.csv"]
    images = tables["images.csv"]
    profile_ids = {row["user_id"] for row in profiles}
    event_ids = {row["event_id"] for row in events}
    request_ids = {row["request_id"] for row in requests}
    known_request_ids = set(request_ids)
    for name in ("requests.csv", "sample_requests.csv"):
        path = dataset / name
        if path.is_file():
            known_request_ids.update(row["request_id"] for row in _read(path, REQUEST_COLUMNS))

    id_specs = (
        (profiles, "user_id", "financial_profiles.csv"),
        (events, "event_id", "financial_events.csv"),
        (requests, "request_id", requests_name),
        (options, "payment_option_id", "request_payment_options.csv"),
        (messages, "message_id", "messages.csv"),
        (images, "image_id", "images.csv"),
    )
    for rows, field, name in id_specs:
        values = [row[field] for row in rows]
        if any(not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f"{name} contains blank or duplicate {field} values")

    if any(row["user_id"] not in profile_ids for row in requests + events + messages + images):
        raise ValueError("A request, event, message, or image references an unknown user")
    if any(row["request_id"] not in known_request_ids for row in options):
        raise ValueError("A payment option references an unknown request")
    if any(row["request_id"] and row["request_id"] not in known_request_ids for row in messages):
        raise ValueError("A message references an unknown request")
    if any(row["related_event_id"] and row["related_event_id"] not in event_ids for row in messages):
        raise ValueError("A message references an unknown event")
    if any(row["request_id"] not in known_request_ids for row in images):
        raise ValueError("An image references an unknown request")
    if any(row["related_event_id"] not in event_ids for row in images):
        raise ValueError("An image references an unknown event")
    image_event_ids = {row["related_event_id"] for row in images}
    if any(not row["amount"] and row["event_id"] not in image_event_ids for row in events):
        raise ValueError("An event with a blank amount has no linked image evidence")
    return DatasetDimensions({name: len(rows) for name, rows in tables.items()})


def validate_decisions(decisions: Iterable[Decision], requests: Iterable[Request]) -> None:
    """Validate generated rows before writing a submission."""
    decision_rows = list(decisions)
    request_rows = list(requests)
    request_by_id = {row.request_id: row for row in request_rows}
    ids = [row.request_id for row in decision_rows]
    if len(ids) != len(request_rows) or len(ids) != len(set(ids)) or set(ids) != set(request_by_id):
        raise ValueError("Predictions must contain exactly one row for every request_id")
    for row in decision_rows:
        if row.affordability_status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid affordability status for {row.request_id}")
        if row.recommended_payment_method not in ALLOWED_METHODS:
            raise ValueError(f"Invalid payment method for {row.request_id}")
        try:
            safe = Decimal(row.amount_safe_to_pay)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid safe amount for {row.request_id}") from exc
        if safe < 0 or safe > request_by_id[row.request_id].amount:
            raise ValueError(f"Safe amount is outside request bounds for {row.request_id}")
        if not row.payment_plan or not row.spending_changes_needed or not row.decision_explanation:
            raise ValueError(f"Required output value is blank for {row.request_id}")
