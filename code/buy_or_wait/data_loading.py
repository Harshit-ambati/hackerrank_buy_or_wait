"""Typed loading of all challenge input files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from .models import Event, Message, PaymentOption, Profile, Request


ZERO = Decimal("0")


class EvidenceResolver(Protocol):
    def extract_image_amount(self, image_path: Path, event: dict[str, str]) -> Decimal: ...
    def normalize_messages(self, messages: list[Message]) -> list[Message]: ...


@dataclass(frozen=True)
class LoadedDataset:
    profiles: dict[str, Profile]
    events: list[Event]
    options: list[PaymentOption]
    messages: list[Message]
    image_links: dict[str, str]
    exchange_rates: dict[tuple[date, str, str], Decimal]


def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value.strip().replace(",", ""))


def split_set(value: str) -> frozenset[str]:
    return frozenset(part for part in value.split("|") if part)


def load_requests(path: Path) -> list[Request]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            Request(
                request_id=row["request_id"], user_id=row["user_id"],
                request_date=date.fromisoformat(row["request_date"]),
                request_type=row["request_type"],
                amount=decimal_or_none(row["requested_amount"]) or ZERO,
                desired_completion_date=date.fromisoformat(row["desired_completion_date"]),
                allows_partial=row["allows_partial_payment"].lower() == "true",
                text=row["request_text"],
            )
            for row in csv.DictReader(handle)
        ]


def load_dataset(dataset: Path, evidence_resolver: EvidenceResolver) -> LoadedDataset:
    dataset = dataset.resolve()
    with (dataset / "financial_profiles.csv").open(encoding="utf-8-sig", newline="") as handle:
        profiles = {
            row["user_id"]: Profile(
                user_id=row["user_id"], currency=row["home_currency"],
                balance=decimal_or_none(row["current_available_balance"]) or ZERO,
                minimum_balance=decimal_or_none(row["minimum_balance_to_keep"]) or ZERO,
                priorities=split_set(row["financial_priorities"]),
                protected_categories=split_set(row["expense_categories_to_protect"]),
                reducible_categories=split_set(row["expense_categories_user_is_willing_to_reduce"]),
                stoppable_categories=split_set(row["expense_categories_user_is_willing_to_stop"]),
                payment_methods=split_set(row["payment_methods_user_will_consider"]),
                max_installment_months=(
                    int(row["max_installment_months"])
                    if row["max_installment_months"] else None
                ),
            )
            for row in csv.DictReader(handle)
        }

    with (dataset / "images.csv").open(encoding="utf-8-sig", newline="") as handle:
        image_rows = list(csv.DictReader(handle))
    image_links = {row["related_event_id"]: row["image_id"] for row in image_rows}

    with (dataset / "financial_events.csv").open(encoding="utf-8-sig", newline="") as handle:
        event_rows = list(csv.DictReader(handle))
    unresolved = [
        (dataset / "media" / "images" / f"{image_links[row['event_id']]}.png", row)
        for row in event_rows
        if decimal_or_none(row["amount"]) is None and row["event_id"] in image_links
    ]
    batch_extractor = getattr(evidence_resolver, "extract_image_amounts", None)
    extracted = (
        batch_extractor(unresolved)
        if unresolved and callable(batch_extractor)
        else {
            row["event_id"]: evidence_resolver.extract_image_amount(path, row)
            for path, row in unresolved
        }
    )
    events: list[Event] = []
    for row in event_rows:
        amount = decimal_or_none(row["amount"])
        if amount is None:
            amount = extracted.get(row["event_id"])
        if amount is None:
            raise ValueError(f"Event {row['event_id']} has no resolvable amount")
        events.append(Event(
            event_id=row["event_id"], user_id=row["user_id"], event_type=row["event_type"],
            description=row["description"], category=row["category"], direction=row["direction"],
            amount=amount, currency=row["currency"], event_date=date.fromisoformat(row["event_date"]),
            settlement_date=date.fromisoformat(row["settlement_date"] or row["event_date"]),
            status=row["status"], linked_event_id=row["linked_event_id"] or None,
            flexibility=row["flexibility"],
            minimum_allowed_amount=decimal_or_none(row["minimum_allowed_amount"]),
        ))

    with (dataset / "request_payment_options.csv").open(encoding="utf-8-sig", newline="") as handle:
        options = [
            PaymentOption(
                option_id=row["payment_option_id"], request_id=row["request_id"],
                method=row["payment_method"],
                payment_amount=decimal_or_none(row["payment_amount"]) or ZERO,
                number_of_payments=int(row["number_of_payments"]),
                first_payment_date=date.fromisoformat(row["first_payment_date"]),
                frequency_days=(int(row["payment_frequency_days"]) if row["payment_frequency_days"] else None),
                financing_fee=decimal_or_none(row["financing_fee"]) or ZERO,
                total_payable=decimal_or_none(row["total_payable_amount"]) or ZERO,
            )
            for row in csv.DictReader(handle)
        ]

    with (dataset / "messages.csv").open(encoding="utf-8-sig", newline="") as handle:
        messages = [
            Message(
                message_id=row["message_id"], user_id=row["user_id"],
                request_id=row["request_id"] or None,
                related_event_id=row["related_event_id"] or None, sent_at=row["sent_at"],
                source_type=row["source_type"], text=row["message_text"],
            )
            for row in csv.DictReader(handle)
        ]
    messages = evidence_resolver.normalize_messages(messages)

    with (dataset / "exchange_rates.csv").open(encoding="utf-8-sig", newline="") as handle:
        rates = {
            (date.fromisoformat(row["rate_date"]), row["from_currency"], row["to_currency"]): Decimal(row["rate"])
            for row in csv.DictReader(handle)
        }
    return LoadedDataset(profiles, events, options, messages, image_links, rates)
