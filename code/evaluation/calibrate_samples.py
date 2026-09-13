"""Compare public labels with forecast internals during local calibration."""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.engine import DecisionEngine  # noqa: E402
from buy_or_wait.models import CashFlow  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"


def main() -> int:
    engine = DecisionEngine.from_directory(DATASET)
    truth = {
        row["request_id"]: row
        for row in csv.DictReader(
            (DATASET / "sample_requests.csv").open(encoding="utf-8-sig", newline="")
        )
    }
    variants = {name: [] for name in ("mean", "median", "max")}
    print("request expected current raw no_variable required_variable cadence_mean cadence_median cadence_max")
    for request in engine.load_requests(DATASET / "sample_requests.csv"):
        profile = engine.profiles[request.user_id]
        forecast, _ = engine._build_forecast(request)
        raw = engine._minimum_balance(forecast) - profile.minimum_balance
        no_variable = replace(
            forecast,
            flows=[flow for flow in forecast.flows if flow.event_id != "variable_spending"],
        )
        no_variable_raw = engine._minimum_balance(no_variable) - profile.minimum_balance
        expected = Decimal(truth[request.request_id]["amount_safe_to_pay"])

        # Experimental category-cadence forecast for non-monthly settled debits.
        groups: dict[str, list[object]] = defaultdict(list)
        for event in engine.events_by_user[request.user_id]:
            if (
                event.status == "settled"
                and event.direction == "debit"
                and event.amount is not None
                and event.category in {"groceries", "transport", "dining"}
                and event.settlement_date < request.request_date
            ):
                groups[event.category].append(event)
        cadence_flows = {name: [] for name in variants}
        for group in groups.values():
            group.sort(key=lambda item: item.settlement_date)
            recent = group[-6:]
            gaps = [
                (right.settlement_date - left.settlement_date).days
                for left, right in zip(recent, recent[1:])
            ]
            if not gaps:
                continue
            gap = max(1, round(statistics.median(gaps)))
            recent_amounts = [engine._home_amount(item, profile) for item in recent[-3:]]
            amounts = {
                "mean": sum(recent_amounts, Decimal("0")) / Decimal(len(recent_amounts)),
                "median": Decimal(str(statistics.median(recent_amounts))),
                "max": max(recent_amounts),
            }
            next_date = recent[-1].settlement_date + timedelta(days=gap)
            while next_date <= forecast.end_date:
                for name, amount in amounts.items():
                    cadence_flows[name].append(
                        CashFlow(next_date, -amount, "variable_spending", "variable_spending", "Cadence")
                    )
                next_date += timedelta(days=gap)

        cadence_safe = {}
        for name, extra_flows in cadence_flows.items():
            candidate = replace(no_variable, flows=no_variable.flows + extra_flows)
            value = engine._minimum_balance(candidate) - profile.minimum_balance
            value -= forecast.safe_adjustment
            value = min(request.amount, max(Decimal("0"), value))
            cadence_safe[name] = value.quantize(Decimal("0.01"))
            variants[name].append(abs(cadence_safe[name] - expected))

        current = Decimal(engine.decide(request).amount_safe_to_pay)
        print(
            request.request_id,
            expected,
            current,
            raw,
            no_variable_raw,
            (no_variable_raw - expected).quantize(Decimal("0.01")),
            cadence_safe["mean"],
            cadence_safe["median"],
            cadence_safe["max"],
        )
    print("MAE", *(f"{name}={sum(errors, Decimal('0')) / len(errors):.2f}" for name, errors in variants.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
