"""Print forecast components for one request during model calibration."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.engine import DecisionEngine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_id")
    parser.add_argument("--samples", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    engine = DecisionEngine.from_directory(root / "dataset")
    filename = "sample_requests.csv" if args.samples else "requests.csv"
    request = next(
        row for row in engine.load_requests(root / "dataset" / filename)
        if row.request_id == args.request_id
    )
    forecast, changes = engine._build_forecast(request)
    totals: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    balance = forecast.opening_balance
    low = balance
    low_date = forecast.start_date
    for flow in forecast.flows:
        key = (flow.event_id, flow.category, flow.description)
        totals[key] += flow.amount
        counts[key] += 1
    daily: dict[object, Decimal] = defaultdict(lambda: Decimal("0"))
    for flow in forecast.flows:
        daily[flow.flow_date] += flow.amount
    current = forecast.start_date
    while current <= forecast.end_date:
        balance += daily[current]
        if balance < low:
            low = balance
            low_date = current
        current = current.fromordinal(current.toordinal() + 1)
    profile = engine.profiles[request.user_id]
    print(f"request={request.request_id} user={request.user_id} amount={request.amount}")
    print(f"opening={forecast.opening_balance} floor={forecast.minimum_balance}")
    print(f"low={low} on {low_date}; safe={max(Decimal('0'), low-profile.minimum_balance)}")
    print("flows:")
    for key, total in sorted(totals.items(), key=lambda item: item[0]):
        print(f"  {key[0]:>18}  {key[1]:<22} {counts[key]:>3} {total:>15}  {key[2]}")
    print("changes:", ", ".join(change.text for change in changes) or "none")
    recurring_ids: set[str] = set()
    grouped: dict[tuple[str, str, str], list[object]] = defaultdict(list)
    for event in engine.events_by_user[request.user_id]:
        if event.status == "settled" and event.amount is not None and event.settlement_date <= request.request_date:
            grouped[(event.direction, event.category, event.description)].append(event)
    for (_, category, _), group in grouped.items():
        group.sort(key=lambda item: item.settlement_date)
        if engine._is_monthly(group, request.request_date, max_staleness=70 if category == "salary" else 40):
            recurring_ids.update(item.event_id for item in group)
    history: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    halves: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for event in engine.events_by_user[request.user_id]:
        if (
            event.status == "settled" and event.direction == "debit"
            and event.amount is not None and event.event_id not in recurring_ids
            and request.request_date.fromordinal(request.request_date.toordinal() - 120)
            <= event.settlement_date < request.request_date
            and not event.linked_event_id
        ):
            history[event.settlement_date.strftime("%Y-%m")] += engine._home_amount(event, profile)
            half = "01-14" if event.settlement_date.day <= 14 else "15-31"
            halves[(event.settlement_date.strftime("%Y-%m"), half)] += engine._home_amount(event, profile)
    print("non-recurring monthly history:", dict(sorted(history.items())))
    print("non-recurring half-month history:", dict(sorted(halves.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
