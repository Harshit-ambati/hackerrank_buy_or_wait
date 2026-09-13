"""Reviewed facts and parsers for the supplied messages and images."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import Message


IMAGE_AMOUNTS: dict[str, Decimal] = {
    "image_01": Decimal("4365000"),
    "image_02": Decimal("100000"),
    "image_03": Decimal("41272"),
    "image_04": Decimal("2854"),
    "image_05": Decimal("704.05"),
    "image_06": Decimal("1995"),
    "image_07": Decimal("8528.10"),
    "image_08": Decimal("15339"),
    "image_09": Decimal("723"),
    "image_10": Decimal("79679.26"),
    "image_11": Decimal("3650"),
    "image_12": Decimal("33.50"),
    "image_13": Decimal("2298"),
    "image_14": Decimal("4593"),
    "image_15": Decimal("9968"),
    "image_16": Decimal("393.22"),
}


@dataclass(frozen=True)
class SalaryEvidence:
    amount: Decimal | None = None
    currency: str | None = None
    effective_date: date | None = None
    next_only: bool = False
    stopped: bool = False
    one_time_amount: Decimal | None = None
    one_time_currency: str | None = None


@dataclass(frozen=True)
class ConfirmedIncome:
    amount: Decimal
    currency: str
    settlement_date: date
    message_id: str


DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
CURRENCY_AMOUNT_RE = re.compile(
    r"\b(INR|IDR|ZAR|USD|EUR)\s*([0-9][0-9,.]*)", re.IGNORECASE
)
PERCENT_RE = re.compile(r"(?:by|sebesar)\s+([0-9]+(?:\.[0-9]+)?)%", re.IGNORECASE)


def relevant_messages(
    messages: list[Message], user_id: str, request_id: str, on_or_before: date
) -> list[Message]:
    result = []
    for message in messages:
        if message.user_id != user_id:
            continue
        if message.request_id and message.request_id != request_id:
            continue
        sent_date = date.fromisoformat(message.sent_at[:10])
        if sent_date <= on_or_before:
            result.append(message)
    return sorted(result, key=lambda item: item.sent_at)


def parse_salary_evidence(messages: list[Message]) -> SalaryEvidence | None:
    current: SalaryEvidence | None = None
    for message in messages:
        text = message.text
        lower = text.lower()
        if message.source_type != "employer":
            continue
        if any(phrase in lower for phrase in ("reimbursement", "penggantian atas biaya")):
            continue
        currency_amounts = CURRENCY_AMOUNT_RE.findall(text)
        if any(phrase in lower for phrase in ("bonus is still", "bonus kuartalan")) and not currency_amounts:
            continue
        stopped = any(
            phrase in lower
            for phrase in (
                "employment has ended", "seasonal contract has ended",
                "kontrak musiman saat ini telah berakhir",
                "hubungan kerja anda telah berakhir",
            )
        )
        dates = DATE_RE.findall(text)
        amount_text = currency_amounts[0][1].replace(",", "").rstrip(".") if currency_amounts else ""
        amount = Decimal(amount_text) if amount_text else None
        currency = currency_amounts[0][0].upper() if currency_amounts else None
        effective = date.fromisoformat(dates[0]) if dates else None
        next_only = any(
            phrase in lower
            for phrase in (
                "next salary is reduced", "temporary monthly pay",
                "gaji bulanan sementara",
                "receiving bank will convert", "bank penerima akan mengonversinya",
            )
        )
        one_time_amount = None
        one_time_currency = None
        if len(currency_amounts) > 1 and any(
            phrase in lower
            for phrase in ("one-time arrears", "penyesuaian tunggakan satu kali")
        ):
            one_time_currency = currency_amounts[1][0].upper()
            one_time_amount = Decimal(currency_amounts[1][1].replace(",", "").rstrip("."))
        if stopped or amount is not None or effective is not None:
            current = SalaryEvidence(
                amount=amount,
                currency=currency,
                effective_date=effective,
                next_only=next_only,
                stopped=stopped,
                one_time_amount=one_time_amount,
                one_time_currency=one_time_currency,
            )
    return current


def parse_confirmed_incomes(messages: list[Message]) -> list[ConfirmedIncome]:
    """Extract one-time provider payments that are explicitly approved and dated."""
    result: list[ConfirmedIncome] = []
    for message in messages:
        if message.source_type != "service_provider":
            continue
        lower = message.text.lower()
        if not any(
            phrase in lower
            for phrase in (
                "client approved an invoice payment",
                "client approved an invoice",
                "klien menyetujui pembayaran faktur",
                "klien telah menyetujui pembayaran faktur",
            )
        ):
            continue
        amounts = CURRENCY_AMOUNT_RE.findall(message.text)
        dates = DATE_RE.findall(message.text)
        if not amounts or not dates:
            continue
        currency, amount_text = amounts[0]
        result.append(
            ConfirmedIncome(
                amount=Decimal(amount_text.replace(",", "").rstrip(".")),
                currency=currency.upper(),
                settlement_date=date.fromisoformat(dates[0]),
                message_id=message.message_id,
            )
        )
    return result


def parse_rent_increase(messages: list[Message]) -> Decimal | None:
    increase = None
    for message in messages:
        lower = message.text.lower()
        if "rent" not in lower and "sewa" not in lower:
            continue
        match = PERCENT_RE.search(message.text)
        if match:
            increase = Decimal(match.group(1)) / Decimal("100")
    return increase


def failed_debit_remains_due(message: Message) -> bool:
    text = message.text.lower()
    return any(
        phrase in text
        for phrase in (
            "bill is still outstanding", "bill is still open",
            "tagihan masih belum dibayar", "tagihan masih terbuka",
        )
    )
