"""Financial-state reconstruction, forecasting, and plan selection."""

from __future__ import annotations

import csv
import itertools
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Protocol

from .evidence import (
    failed_debit_remains_due,
    parse_confirmed_incomes,
    parse_rent_increase,
    parse_salary_evidence,
    relevant_messages,
)
from .models import (
    CandidatePlan,
    CashFlow,
    Decision,
    Event,
    Forecast,
    Message,
    PaymentOption,
    Profile,
    Request,
    SpendingChange,
    format_decimal,
)


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]
ZERO = Decimal("0")
CENT = Decimal("0.01")


class EvidenceResolver(Protocol):
    def extract_image_amount(self, image_path: Path, event: dict[str, str]) -> Decimal: ...

    def normalize_messages(self, messages: list[Message]) -> list[Message]: ...


def dec(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value.strip().replace(",", ""))


def split_set(value: str) -> frozenset[str]:
    return frozenset(part for part in value.split("|") if part)


def add_months(value: date, count: int = 1) -> date:
    month_index = value.month - 1 + count
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(value.day, month_lengths[month - 1]))


def human_date(value: date) -> str:
    """Portable day-month-year formatting without a leading zero."""
    return f"{value.day} {value.strftime('%B %Y')}"


class DecisionEngine:
    def __init__(
        self,
        profiles: dict[str, Profile],
        events: list[Event],
        options: list[PaymentOption],
        messages: list[Message],
        image_links: dict[str, str],
        exchange_rates: dict[tuple[date, str, str], Decimal],
    ) -> None:
        self.profiles = profiles
        self.events_by_user: dict[str, list[Event]] = defaultdict(list)
        for event in events:
            self.events_by_user[event.user_id].append(event)
        self.options_by_request: dict[str, list[PaymentOption]] = defaultdict(list)
        for option in options:
            self.options_by_request[option.request_id].append(option)
        self.messages = messages
        self.image_links = image_links
        self.exchange_rates = exchange_rates

    @classmethod
    def from_directory(
        cls, dataset: Path, evidence_resolver: EvidenceResolver
    ) -> "DecisionEngine":
        dataset = dataset.resolve()
        with (dataset / "financial_profiles.csv").open(encoding="utf-8-sig", newline="") as fh:
            profiles = {
                row["user_id"]: Profile(
                    user_id=row["user_id"],
                    currency=row["home_currency"],
                    balance=dec(row["current_available_balance"]) or ZERO,
                    minimum_balance=dec(row["minimum_balance_to_keep"]) or ZERO,
                    priorities=split_set(row["financial_priorities"]),
                    protected_categories=split_set(row["expense_categories_to_protect"]),
                    reducible_categories=split_set(row["expense_categories_user_is_willing_to_reduce"]),
                    stoppable_categories=split_set(row["expense_categories_user_is_willing_to_stop"]),
                    payment_methods=split_set(row["payment_methods_user_will_consider"]),
                    max_installment_months=int(row["max_installment_months"]) if row["max_installment_months"] else None,
                )
                for row in csv.DictReader(fh)
            }

        with (dataset / "images.csv").open(encoding="utf-8-sig", newline="") as fh:
            image_links = {row["related_event_id"]: row["image_id"] for row in csv.DictReader(fh)}

        events: list[Event] = []
        with (dataset / "financial_events.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                amount = dec(row["amount"])
                if amount is None and row["event_id"] in image_links:
                    image_id = image_links[row["event_id"]]
                    amount = evidence_resolver.extract_image_amount(
                        dataset / "media" / "images" / f"{image_id}.png", row
                    )
                if amount is None:
                    raise ValueError(
                        f"Event {row['event_id']} has no amount and no resolvable image evidence"
                    )
                events.append(
                    Event(
                        event_id=row["event_id"], user_id=row["user_id"],
                        event_type=row["event_type"], description=row["description"],
                        category=row["category"], direction=row["direction"], amount=amount,
                        currency=row["currency"], event_date=date.fromisoformat(row["event_date"]),
                        settlement_date=date.fromisoformat(row["settlement_date"] or row["event_date"]),
                        status=row["status"], linked_event_id=row["linked_event_id"] or None,
                        flexibility=row["flexibility"],
                        minimum_allowed_amount=dec(row["minimum_allowed_amount"]),
                    )
                )

        options: list[PaymentOption] = []
        with (dataset / "request_payment_options.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                options.append(
                    PaymentOption(
                        option_id=row["payment_option_id"], request_id=row["request_id"],
                        method=row["payment_method"], payment_amount=dec(row["payment_amount"]) or ZERO,
                        number_of_payments=int(row["number_of_payments"]),
                        first_payment_date=date.fromisoformat(row["first_payment_date"]),
                        frequency_days=int(row["payment_frequency_days"]) if row["payment_frequency_days"] else None,
                        financing_fee=dec(row["financing_fee"]) or ZERO,
                        total_payable=dec(row["total_payable_amount"]) or ZERO,
                    )
                )

        messages: list[Message] = []
        with (dataset / "messages.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                messages.append(
                    Message(
                        message_id=row["message_id"], user_id=row["user_id"],
                        request_id=row["request_id"] or None,
                        related_event_id=row["related_event_id"] or None,
                        sent_at=row["sent_at"], source_type=row["source_type"],
                        text=row["message_text"],
                    )
                )
        messages = evidence_resolver.normalize_messages(messages)

        rates: dict[tuple[date, str, str], Decimal] = {}
        with (dataset / "exchange_rates.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rates[(date.fromisoformat(row["rate_date"]), row["from_currency"], row["to_currency"])] = Decimal(row["rate"])
        return cls(profiles, events, options, messages, image_links, rates)

    def load_requests(self, path: Path) -> list[Request]:
        result: list[Request] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                result.append(
                    Request(
                        request_id=row["request_id"], user_id=row["user_id"],
                        request_date=date.fromisoformat(row["request_date"]),
                        request_type=row["request_type"], amount=dec(row["requested_amount"]) or ZERO,
                        desired_completion_date=date.fromisoformat(row["desired_completion_date"]),
                        allows_partial=row["allows_partial_payment"].lower() == "true",
                        text=row["request_text"],
                    )
                )
        return result

    def run(self, request_path: Path) -> list[Decision]:
        return [self.decide(request) for request in self.load_requests(request_path)]

    def write_output(self, decisions: list[Decision], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(decision.as_row() for decision in decisions)

    def _home_amount(self, event: Event, profile: Profile) -> Decimal:
        assert event.amount is not None
        return self._convert_amount(event.amount, event.currency, profile, event.settlement_date)

    def _convert_amount(
        self, amount: Decimal, currency: str, profile: Profile, settlement_date: date
    ) -> Decimal:
        if currency == profile.currency:
            return amount
        key = (settlement_date, currency, profile.currency)
        if key not in self.exchange_rates:
            raise ValueError(f"Missing exchange rate for {key}")
        return (amount * self.exchange_rates[key]).quantize(CENT)

    @staticmethod
    def _is_monthly(events: list[Event], request_date: date, *, max_staleness: int = 40) -> bool:
        if len(events) < 4:
            return False
        recent = events[-5:]
        if (request_date - recent[-1].settlement_date).days > max_staleness:
            return False
        intervals = [
            (right.settlement_date - left.settlement_date).days
            for left, right in zip(recent, recent[1:])
        ]
        return len(intervals) >= 3 and all(26 <= gap <= 35 for gap in intervals[-3:])

    def _build_forecast(self, request: Request) -> tuple[Forecast, list[SpendingChange]]:
        profile = self.profiles[request.user_id]
        end = request.request_date + timedelta(days=90)
        user_events = sorted(self.events_by_user[request.user_id], key=lambda item: item.settlement_date)
        neutralized_debits = {
            event.linked_event_id
            for event in user_events
            if (
                event.status == "settled"
                and event.direction == "credit"
                and event.event_type == "refund"
                and event.linked_event_id
            )
        }
        scheduled_retry_of = {
            event.linked_event_id
            for event in user_events
            if (
                event.status == "scheduled"
                and event.direction == "debit"
                and event.linked_event_id
            )
        }
        messages = relevant_messages(self.messages, request.user_id, request.request_id, request.request_date)
        linked_messages = {message.related_event_id: message for message in messages if message.related_event_id}
        flows: list[CashFlow] = []

        # Explicit future records and reserved debits take precedence over inferred recurrence.
        known_keys: set[tuple[str, str, date]] = set()
        known_category_dates: set[tuple[str, str, date]] = set()
        scheduled_salary_events: list[Event] = []
        for event in user_events:
            if event.amount is None or event.status in {"cancelled", "unrealized"}:
                continue
            flow_date = event.settlement_date
            include = False
            if event.status == "scheduled" and flow_date >= request.request_date:
                include = True
            elif event.status == "pending" and event.direction == "debit":
                include = True
                flow_date = max(flow_date, request.request_date)
            elif event.status == "failed" and event.direction == "debit":
                message = linked_messages.get(event.event_id)
                if (
                    event.event_id not in scheduled_retry_of
                    and message
                    and failed_debit_remains_due(message)
                ):
                    include = True
                    flow_date = request.request_date
            if not include or flow_date > end:
                continue
            amount = self._home_amount(event, profile)
            signed = amount if event.direction == "credit" else -amount
            # Pending credits are intentionally excluded above.
            flows.append(CashFlow(flow_date, signed, event.event_id, event.category, event.description))
            known_keys.add((event.direction, event.description, flow_date))
            known_category_dates.add((event.direction, event.category, flow_date))
            if event.status == "scheduled" and event.direction == "credit" and event.category == "salary":
                scheduled_salary_events.append(event)

        # Some approved contract/invoice income exists only in provider
        # messages. It is usable only when both the amount and settlement date
        # are explicit; pending or undated app earnings remain excluded.
        for income in parse_confirmed_incomes(messages):
            if not (request.request_date <= income.settlement_date <= end):
                continue
            amount = self._convert_amount(
                income.amount, income.currency, profile, income.settlement_date
            )
            duplicate = any(
                flow.flow_date == income.settlement_date
                and flow.amount == amount
                and flow.amount > ZERO
                for flow in flows
            )
            if not duplicate:
                flows.append(
                    CashFlow(
                        income.settlement_date,
                        amount,
                        income.message_id,
                        "contract_income",
                        "Confirmed invoice payment",
                    )
                )

        history_groups: dict[tuple[str, str, str], list[Event]] = defaultdict(list)
        for event in user_events:
            if (
                event.status == "settled" and event.amount is not None
                and event.settlement_date <= request.request_date
                and event.event_type not in {"refund", "investment_purchase", "investment_sale", "investment_valuation"}
            ):
                history_groups[(event.direction, event.category, event.description)].append(event)

        # Freelance/contract income often changes description every payment but
        # still follows stable monthly day slots. Add those slot series only when
        # no description-level salary series already establishes recurrence.
        salary_description_recurs = any(
            direction == "credit" and category == "salary"
            and self._is_monthly(group, request.request_date, max_staleness=70)
            for (direction, category, _), group in history_groups.items()
        )
        if not salary_description_recurs:
            salary_events = [
                event for event in user_events
                if event.status == "settled" and event.direction == "credit"
                and event.category == "salary" and event.amount is not None
                and event.settlement_date <= request.request_date
            ]
            slots: dict[int, list[Event]] = defaultdict(list)
            for event in salary_events:
                slot = 0 if event.settlement_date.day <= 13 else 1
                slots[slot].append(event)
            for slot, group in slots.items():
                if self._is_monthly(group, request.request_date, max_staleness=70):
                    history_groups[("credit", "salary", f"__salary_slot_{slot}")] = group

        recurring_ids: set[str] = set()
        changes: list[SpendingChange] = []
        salary_evidence = parse_salary_evidence(messages)
        rent_increase = parse_rent_increase(messages)
        salary_group_seen = False
        salary_arrears_added = False
        settled_salary_events = [
            event for event in user_events
            if event.status == "settled" and event.direction == "credit"
            and event.category == "salary" and event.amount is not None
            and event.settlement_date <= request.request_date
        ]
        latest_salary_is_final = bool(
            settled_salary_events
            and "final" in settled_salary_events[-1].description.lower()
        )

        for (direction, category, description), group in history_groups.items():
            group.sort(key=lambda item: item.settlement_date)
            if not self._is_monthly(
                group, request.request_date,
                max_staleness=70 if category == "salary" else 40,
            ):
                continue
            recurring_ids.update(item.event_id for item in group)
            representative = group[-1]
            amounts = [self._home_amount(item, profile) for item in group[-3:]]
            stable = max(amounts) - min(amounts) <= max(Decimal("0.01"), statistics.median(amounts) * Decimal("0.02"))
            amount = amounts[-1] if stable or direction == "credit" else max(amounts)
            next_date = add_months(representative.settlement_date)

            if category == "salary":
                # Multiple independently recurring salary slots are valid (for
                # example twice-monthly freelance payments).
                if latest_salary_is_final and salary_evidence is None:
                    continue
                if salary_evidence and salary_group_seen:
                    continue
                if scheduled_salary_events and not salary_evidence:
                    scheduled_amounts = [self._home_amount(item, profile) for item in scheduled_salary_events]
                    if min(abs(amount - item_amount) for item_amount in scheduled_amounts) > max(Decimal("1"), amount * Decimal("0.05")):
                        continue
                salary_group_seen = True
                if salary_evidence:
                    if salary_evidence.stopped:
                        continue
                    if salary_evidence.amount is not None:
                        amount = self._convert_amount(
                            salary_evidence.amount,
                            salary_evidence.currency or profile.currency,
                            profile,
                            salary_evidence.effective_date or next_date,
                        )
                    if salary_evidence.effective_date is not None:
                        next_date = salary_evidence.effective_date
                elif scheduled_salary_events:
                    matching = min(
                        scheduled_salary_events,
                        key=lambda item: abs((item.settlement_date - next_date).days),
                    )
                    if abs((matching.settlement_date - next_date).days) <= 20:
                        next_date = matching.settlement_date
                        amount = self._home_amount(matching, profile)
            if category == "rent" and rent_increase is not None:
                amount = (amount * (Decimal("1") + rent_increase)).quantize(CENT)

            current_date = next_date
            occurrence = 0
            while current_date <= end:
                occurrence += 1
                if (
                    (direction, description, current_date) not in known_keys
                    and (direction, category, current_date) not in known_category_dates
                ):
                    signed = amount if direction == "credit" else -amount
                    if category == "salary" and salary_evidence and salary_evidence.next_only and occurrence > 1:
                        # A one-cycle reduction changes only the first inferred payroll.
                        amount = statistics.median(amounts)
                        signed = amount
                    flows.append(
                        CashFlow(current_date, signed, representative.event_id, category, description, True)
                    )
                current_date = add_months(current_date)

            if (
                category == "salary"
                and salary_evidence
                and salary_evidence.one_time_amount is not None
                and not salary_arrears_added
            ):
                arrears_date = salary_evidence.effective_date or next_date
                if request.request_date <= arrears_date <= end:
                    arrears = self._convert_amount(
                        salary_evidence.one_time_amount,
                        salary_evidence.one_time_currency or profile.currency,
                        profile,
                        arrears_date,
                    )
                    flows.append(
                        CashFlow(
                            arrears_date,
                            arrears,
                            "message_salary_arrears",
                            "salary",
                            "Confirmed one-time payroll adjustment",
                        )
                    )
                    salary_arrears_added = True

            if direction == "debit" and representative.flexibility != "fixed" and category not in profile.protected_categories:
                if category in profile.stoppable_categories and representative.flexibility in {"stoppable", "reducible_or_stoppable"}:
                    changes.append(SpendingChange("stop", representative.event_id, amount, ZERO, category))
                if category in profile.reducible_categories and representative.flexibility in {"reducible", "reducible_or_stoppable"}:
                    new_amount = representative.minimum_allowed_amount or ZERO
                    if new_amount < amount:
                        changes.append(SpendingChange("reduce_to", representative.event_id, amount, new_amount, category))

        # A scheduled salary is itself strong evidence of the next monthly
        # cycle, even when employment has only just started.
        if not salary_group_seen and scheduled_salary_events:
            scheduled = min(scheduled_salary_events, key=lambda item: item.settlement_date)
            amount = self._home_amount(scheduled, profile)
            flow_date = add_months(scheduled.settlement_date)
            while flow_date <= end:
                flows.append(CashFlow(flow_date, amount, scheduled.event_id, "salary", scheduled.description, True))
                flow_date = add_months(flow_date)
            salary_group_seen = True

        # Confirmed first salary can create a series even when no recurring salary history exists.
        if (
            not salary_group_seen and salary_evidence and not salary_evidence.stopped
            and salary_evidence.effective_date
        ):
            evidence_amount = salary_evidence.amount
            if evidence_amount is None and settled_salary_events:
                evidence_amount = self._home_amount(settled_salary_events[-1], profile)
            elif evidence_amount is not None:
                evidence_amount = self._convert_amount(
                    evidence_amount,
                    salary_evidence.currency or profile.currency,
                    profile,
                    salary_evidence.effective_date,
                )
            if evidence_amount is None:
                evidence_amount = ZERO
            flow_date = salary_evidence.effective_date
            occurrence = 0
            while flow_date <= end and evidence_amount > ZERO:
                occurrence += 1
                amount = evidence_amount
                flows.append(CashFlow(flow_date, amount, "message_salary", "salary", "Confirmed salary", True))
                if salary_evidence.next_only:
                    break
                flow_date = add_months(flow_date)
            if salary_evidence.one_time_amount is not None and salary_evidence.effective_date:
                arrears = self._convert_amount(
                    salary_evidence.one_time_amount,
                    salary_evidence.one_time_currency or profile.currency,
                    profile,
                    salary_evidence.effective_date,
                )
                flows.append(
                    CashFlow(
                        salary_evidence.effective_date,
                        arrears,
                        "message_salary_arrears",
                        "salary",
                        "Confirmed one-time payroll adjustment",
                    )
                )

        # Preserve the observed intra-month shape of variable spending.  Using
        # the average for each calendar day over the last three complete months
        # reserves realistically for pre-payday spending without pretending an
        # individual supermarket or taxi transaction is a recurring contract.
        current_month = request.request_date.replace(day=1)
        lookback_start = add_months(current_month, -3)
        by_month_day: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for event in user_events:
            if event.event_id in recurring_ids or event.amount is None:
                continue
            if event.status != "settled" or event.direction != "debit":
                continue
            if not (lookback_start <= event.settlement_date < current_month):
                continue
            if event.event_type in {"investment_purchase", "investment_sale", "investment_valuation", "refund"}:
                continue
            if event.event_id in neutralized_debits or any(
                word in event.description.lower() for word in ("reversal", "authorization")
            ):
                continue
            by_month_day[event.settlement_date.day] += self._home_amount(event, profile)
        for day_of_month in list(by_month_day):
            by_month_day[day_of_month] = (by_month_day[day_of_month] / Decimal("3")).quantize(CENT)
        for offset in range(1, 91):
            flow_date = request.request_date + timedelta(days=offset)
            amount = by_month_day[flow_date.day]
            if amount:
                flows.append(CashFlow(flow_date, -amount, "variable_spending", "variable_spending", "Normal variable spending"))

        # A repeated flexible category can represent an adjustable budget even
        # when individual merchant descriptions vary. Expose one action for
        # the latest evidence row in that category; older transactions are not
        # separate future budgets that can each be changed.
        existing_change_keys = {(change.action, change.event_id) for change in changes}
        flexible_groups: dict[str, list[Event]] = defaultdict(list)
        for (direction, category, _), group in history_groups.items():
            if direction == "debit":
                flexible_groups[category].extend(group)
        for category, group in flexible_groups.items():
            if len(group) < 2 or category in profile.protected_categories:
                continue
            group.sort(key=lambda item: item.settlement_date)
            representative = group[-1]
            if (request.request_date - representative.settlement_date).days > 180:
                continue
            amount = self._home_amount(representative, profile)
            if (
                category in profile.stoppable_categories
                and representative.flexibility in {"stoppable", "reducible_or_stoppable"}
                and ("stop", representative.event_id) not in existing_change_keys
            ):
                changes.append(SpendingChange("stop", representative.event_id, amount, ZERO, category))
            if (
                category in profile.reducible_categories
                and representative.flexibility in {"reducible", "reducible_or_stoppable"}
                and ("reduce_to", representative.event_id) not in existing_change_keys
            ):
                new_amount = representative.minimum_allowed_amount or ZERO
                if new_amount < amount:
                    changes.append(SpendingChange("reduce_to", representative.event_id, amount, new_amount, category))

        flows.sort(key=lambda item: (item.flow_date, item.event_id))
        variable_total = sum(
            (-flow.amount for flow in flows if flow.event_id == "variable_spending"),
            ZERO,
        )
        variable_uncertainty = (variable_total / Decimal("3")).quantize(CENT)
        trailing_start = request.request_date - timedelta(days=90)
        trailing_variable_total = ZERO
        for event in user_events:
            if event.event_id in recurring_ids or event.amount is None:
                continue
            if event.status != "settled" or event.direction != "debit":
                continue
            if not (trailing_start <= event.settlement_date < request.request_date):
                continue
            if event.event_type in {"investment_purchase", "investment_sale", "investment_valuation", "refund"}:
                continue
            if event.event_id in neutralized_debits or any(
                word in event.description.lower() for word in ("reversal", "authorization")
            ):
                continue
            trailing_variable_total += self._home_amount(event, profile)
        safe_adjustment = max(ZERO, trailing_variable_total - variable_total).quantize(CENT)
        return Forecast(
            request.request_date, end, profile.balance, profile.minimum_balance,
            flows, variable_uncertainty, safe_adjustment,
        ), changes

    @staticmethod
    def _minimum_balance(
        forecast: Forecast,
        payments: list[tuple[date, Decimal]] | None = None,
        changes: tuple[SpendingChange, ...] = (),
    ) -> Decimal:
        payment_map: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for payment_date, amount in payments or []:
            payment_map[payment_date] += amount
        change_map = {change.event_id: change for change in changes}
        matched_changes: set[str] = set()
        flow_map: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for flow in forecast.flows:
            amount = flow.amount
            change = change_map.get(flow.event_id)
            if change and flow.is_recurring and amount < ZERO:
                amount = -change.new_amount
                matched_changes.add(change.event_id)
            flow_map[flow.flow_date] += amount
        # For an adjustable but irregular budget, reserve the 90-day saving at
        # the start. It is a commitment to reduce that repeated category, not a
        # claim that a past transaction can be reversed.
        for change in changes:
            if change.event_id not in matched_changes:
                flow_map[forecast.start_date] += (change.old_amount - change.new_amount) * Decimal("3")
        balance = forecast.opening_balance
        minimum = balance
        current = forecast.start_date
        while current <= forecast.end_date:
            balance += flow_map[current]
            balance -= payment_map[current]
            minimum = min(minimum, balance)
            current += timedelta(days=1)
        return minimum.quantize(CENT)

    @staticmethod
    def _is_safe(forecast: Forecast, plan: CandidatePlan) -> bool:
        minimum = DecisionEngine._minimum_balance(forecast, plan.payments, plan.changes)
        plan.minimum_projected_balance = minimum
        # The calendar-day variable-spend envelope intentionally overstates
        # some timing risk. Its measured uncertainty is therefore allowed back
        # when evaluating a complete plan, while amount_safe_to_pay remains the
        # stricter pre-adjustment amount required by the output contract.
        return (
            minimum + forecast.variable_uncertainty
            >= forecast.minimum_balance + forecast.safe_adjustment
        )

    def _earliest_full_date(
        self, forecast: Forecast, amount: Decimal, desired_completion_date: date
    ) -> date | None:
        current = forecast.start_date
        strict_date: date | None = None
        while current <= forecast.end_date:
            if (
                self._minimum_balance(forecast, [(current, amount)])
                >= forecast.minimum_balance + forecast.safe_adjustment
            ):
                strict_date = current
                break
            current += timedelta(days=1)
        if strict_date is not None and strict_date <= desired_completion_date:
            return strict_date
        # When the conservative variable-spend envelope prevents a strict date,
        # only reconsider confirmed income dates, never an arbitrary earlier day.
        income_dates = sorted({
            flow.flow_date for flow in forecast.flows
            if flow.amount > ZERO and flow.category == "salary"
        })
        if not income_dates and (
            self._minimum_balance(forecast, [(forecast.start_date, amount)])
            + forecast.variable_uncertainty >= forecast.minimum_balance + forecast.safe_adjustment
        ):
            return forecast.start_date
        fallback_uncertainty = forecast.variable_uncertainty * Decimal("0.40")
        for candidate_date in income_dates:
            if (
                self._minimum_balance(forecast, [(candidate_date, amount)])
                + fallback_uncertainty
                >= forecast.minimum_balance
            ):
                return candidate_date
        return strict_date

    @staticmethod
    def _change_sets(changes: list[SpendingChange]) -> list[tuple[SpendingChange, ...]]:
        result: list[tuple[SpendingChange, ...]] = [()]
        by_event: dict[str, list[SpendingChange]] = defaultdict(list)
        for change in changes:
            by_event[change.event_id].append(change)
        event_ids = sorted(by_event)
        for size in range(1, min(3, len(event_ids)) + 1):
            for selected_ids in itertools.combinations(event_ids, size):
                for actions in itertools.product(*(by_event[event_id] for event_id in selected_ids)):
                    result.append(tuple(actions))
        return result

    def _candidate_plans(
        self,
        request: Request,
        forecast: Forecast,
        safe_today: Decimal,
        earliest_full: date | None,
        changes: list[SpendingChange],
    ) -> list[CandidatePlan]:
        profile = self.profiles[request.user_id]
        plans: list[CandidatePlan] = []
        for change_set in self._change_sets(changes):
            if "full_payment" in profile.payment_methods:
                plan = CandidatePlan("full_payment", [(request.request_date, request.amount)], request.amount, changes=change_set)
                if (change_set or safe_today >= request.amount) and self._is_safe(forecast, plan):
                    plans.append(plan)
                if not change_set and earliest_full and earliest_full <= request.desired_completion_date and earliest_full > request.request_date:
                    wait = CandidatePlan("wait", [(earliest_full, request.amount)], request.amount)
                    if self._is_safe(forecast, wait):
                        plans.append(wait)

            if (
                not change_set and request.allows_partial and "partial_payment" in profile.payment_methods
                and ZERO < safe_today < request.amount and earliest_full
                and earliest_full <= request.desired_completion_date
            ):
                partial = CandidatePlan(
                    "partial_payment",
                    [(request.request_date, safe_today), (earliest_full, request.amount - safe_today)],
                    request.amount,
                )
                if self._is_safe(forecast, partial):
                    plans.append(partial)

            if "installments" in profile.payment_methods:
                for option in self.options_by_request[request.request_id]:
                    if option.method != "installments":
                        continue
                    if profile.max_installment_months is None or option.number_of_payments > profile.max_installment_months:
                        continue
                    if option.first_payment_date < request.request_date:
                        continue
                    if option.number_of_payments > 1 and not option.frequency_days:
                        continue
                    frequency = option.frequency_days or 0
                    payments = [
                        (option.first_payment_date + timedelta(days=frequency * index), option.payment_amount)
                        for index in range(option.number_of_payments)
                    ]
                    if payments[-1][0] > request.desired_completion_date:
                        continue
                    plan = CandidatePlan(
                        "installments", payments, option.total_payable,
                        option_id=option.option_id, changes=change_set,
                    )
                    if self._is_safe(forecast, plan):
                        plans.append(plan)
        return plans

    @staticmethod
    def _rank(plan: CandidatePlan) -> tuple[object, ...]:
        return (
            bool(plan.changes),
            plan.total_payable,
            plan.starts_on,
            len(plan.payments),
            len(plan.changes),
            plan.option_id,
            tuple(change.text for change in plan.changes),
        )

    @staticmethod
    def _commitment_summary(forecast: Forecast, profile: Profile) -> str:
        """Describe the essential obligations reserved before a purchase."""
        labels = {
            "education": "education fees",
            "family_support": "childcare and family support",
            "housing": "housing costs",
            "rent": "rent",
            "debt_repayment": "loan repayments",
            "utilities": "utilities",
            "groceries": "groceries",
            "insurance": "insurance",
            "transport": "transport",
        }
        relevant = profile.protected_categories | profile.priorities
        present = {
            flow.category
            for flow in forecast.flows
            if flow.amount < ZERO and flow.category in relevant
        }
        ordered = [
            labels[category]
            for category in labels
            if category in present
        ]
        if any(flow.category == "variable_spending" for flow in forecast.flows):
            ordered.append("normal monthly spending")
        if not ordered:
            return "scheduled and recurring commitments"
        if len(ordered) == 1:
            return ordered[0]
        return ", ".join(ordered[:-1]) + f", and {ordered[-1]}"

    def decide(self, request: Request) -> Decision:
        profile = self.profiles[request.user_id]
        forecast, possible_changes = self._build_forecast(request)
        commitments = self._commitment_summary(forecast, profile)
        baseline_minimum = self._minimum_balance(forecast)
        safe_today = max(
            ZERO,
            baseline_minimum - profile.minimum_balance - forecast.safe_adjustment,
        )
        safe_today = min(request.amount, safe_today).quantize(CENT, rounding=ROUND_DOWN)
        earliest_full = self._earliest_full_date(
            forecast, request.amount, request.desired_completion_date
        )
        candidates = self._candidate_plans(request, forecast, safe_today, earliest_full, possible_changes)

        if not candidates:
            return Decision(
                request_id=request.request_id,
                amount_safe_to_pay=format_decimal(safe_today),
                affordability_status="not_affordable",
                recommended_payment_method="not_recommended",
                payment_plan="none",
                earliest_date_for_full_payment=earliest_full.isoformat() if earliest_full else "",
                spending_changes_needed="none",
                decision_explanation=(
                    f"After reserving {commitments}, do not make this payment by "
                    f"{human_date(request.desired_completion_date)}. None of the eligible options keeps the {profile.currency} "
                    f"{format_decimal(profile.minimum_balance)} minimum protected."
                ),
            )

        chosen = min(candidates, key=self._rank)
        if chosen.method == "wait":
            status = "affordable_later"
        elif chosen.method == "full_payment" and not chosen.changes and safe_today >= request.amount:
            status = "affordable_now"
        else:
            status = "affordable_with_plan"

        payment_plan = "|".join(
            f"{payment_date.isoformat()}:{format_decimal(amount)}"
            for payment_date, amount in chosen.payments
        )
        changes_text = "|".join(change.text for change in chosen.changes) or "none"
        if chosen.method == "wait":
            explanation = (
                f"Wait until {human_date(chosen.payments[0][0])}, then pay "
                f"{profile.currency} {format_decimal(request.amount)} in full. Paying sooner would "
                f"put the {profile.currency} {format_decimal(profile.minimum_balance)} minimum at risk after "
                f"reserving {commitments}."
            )
        elif chosen.method == "installments":
            explanation = (
                f"Use {len(chosen.payments)} installments of {profile.currency} "
                f"{format_decimal(chosen.payments[0][1])}, starting "
                f"{human_date(chosen.starts_on)}; total payable is {profile.currency} "
                f"{format_decimal(chosen.total_payable)}. After reserving {commitments}, the forecast protects the "
                f"{profile.currency} {format_decimal(profile.minimum_balance)} minimum."
            )
        elif chosen.method == "partial_payment":
            explanation = (
                f"Pay {profile.currency} {format_decimal(chosen.payments[0][1])} now and "
                f"{profile.currency} {format_decimal(chosen.payments[1][1])} on "
                f"{human_date(chosen.payments[1][0])}. After reserving {commitments}, this keeps the "
                f"{profile.currency} {format_decimal(profile.minimum_balance)} minimum protected."
            )
        else:
            prefix = "Adjust the selected flexible spending, then " if chosen.changes else ""
            explanation = (
                f"{prefix}pay {profile.currency} {format_decimal(request.amount)} today. "
                f"After reserving {commitments}, the forecast protects the {profile.currency} "
                f"{format_decimal(profile.minimum_balance)} minimum."
            )

        return Decision(
            request_id=request.request_id,
            amount_safe_to_pay=format_decimal(safe_today),
            affordability_status=status,
            recommended_payment_method=chosen.method,
            payment_plan=payment_plan,
            earliest_date_for_full_payment=earliest_full.isoformat() if earliest_full else "",
            spending_changes_needed=changes_text,
            decision_explanation=explanation,
        )
