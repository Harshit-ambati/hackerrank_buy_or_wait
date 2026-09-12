"""Small typed data objects used by the decision engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Profile:
    user_id: str
    currency: str
    balance: Decimal
    minimum_balance: Decimal
    priorities: frozenset[str]
    protected_categories: frozenset[str]
    reducible_categories: frozenset[str]
    stoppable_categories: frozenset[str]
    payment_methods: frozenset[str]
    max_installment_months: int | None


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    amount: Decimal
    desired_completion_date: date
    allows_partial: bool
    text: str


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Decimal | None
    currency: str
    event_date: date
    settlement_date: date
    status: str
    linked_event_id: str | None
    flexibility: str
    minimum_allowed_amount: Decimal | None


@dataclass(frozen=True)
class PaymentOption:
    option_id: str
    request_id: str
    method: str
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    frequency_days: int | None
    financing_fee: Decimal
    total_payable: Decimal


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: str
    source_type: str
    text: str


@dataclass(frozen=True)
class CashFlow:
    flow_date: date
    amount: Decimal
    event_id: str
    category: str
    description: str
    is_recurring: bool = False


@dataclass(frozen=True)
class SpendingChange:
    action: str
    event_id: str
    old_amount: Decimal
    new_amount: Decimal
    category: str

    @property
    def text(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{format_decimal(self.new_amount)}"


@dataclass
class CandidatePlan:
    method: str
    payments: list[tuple[date, Decimal]]
    total_payable: Decimal
    option_id: str = ""
    changes: tuple[SpendingChange, ...] = ()
    minimum_projected_balance: Decimal | None = None

    @property
    def starts_on(self) -> date:
        return self.payments[0][0]


@dataclass(frozen=True)
class Decision:
    request_id: str
    amount_safe_to_pay: str
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str

    def as_row(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": self.amount_safe_to_pay,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


@dataclass
class Forecast:
    start_date: date
    end_date: date
    opening_balance: Decimal
    minimum_balance: Decimal
    flows: list[CashFlow] = field(default_factory=list)
    variable_uncertainty: Decimal = Decimal("0")
    safe_adjustment: Decimal = Decimal("0")


def format_decimal(value: Decimal, *, two_places: bool = False) -> str:
    if two_places:
        return f"{value.quantize(Decimal('0.01')):.2f}"
    normalized = value.quantize(Decimal("0.01"))
    text = format(normalized, "f").rstrip("0").rstrip(".")
    return text or "0"
