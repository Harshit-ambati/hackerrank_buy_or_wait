"""Local structural validator and public-sample scorer."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
]
ENUMS = {
    "affordability_status": {
        "affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"
    },
    "recommended_payment_method": {
        "full_payment", "partial_payment", "installments", "wait", "not_recommended"
    },
}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_plan(value: str) -> list[tuple[date, Decimal]]:
    if value == "none":
        return []
    result = []
    for item in value.split("|"):
        day, amount = item.split(":", 1)
        result.append((date.fromisoformat(day), Decimal(amount)))
    return result


def validate(
    predictions: list[dict[str, str]], requests: list[dict[str, str]], dataset: Path
) -> list[str]:
    errors: list[str] = []
    if predictions and list(predictions[0]) != OUTPUT_COLUMNS:
        errors.append("Output columns are missing, reordered, or unexpected")
    request_map = {row["request_id"]: row for row in requests}
    profiles = {row["user_id"]: row for row in read(dataset / "financial_profiles.csv")}
    events = {row["event_id"]: row for row in read(dataset / "financial_events.csv")}
    options: dict[str, list[dict[str, str]]] = {}
    for option in read(dataset / "request_payment_options.csv"):
        options.setdefault(option["request_id"], []).append(option)
    if len(predictions) != len(requests):
        errors.append(f"Expected {len(requests)} rows, found {len(predictions)}")
    if len({row["request_id"] for row in predictions}) != len(predictions):
        errors.append("Duplicate request_id values")
    for row in predictions:
        request = request_map.get(row["request_id"])
        if request is None:
            errors.append(f"Unknown request_id {row['request_id']}")
            continue
        try:
            safe = Decimal(row["amount_safe_to_pay"])
            requested = Decimal(request["requested_amount"])
            if not (Decimal("0") <= safe <= requested):
                errors.append(f"{row['request_id']}: amount_safe_to_pay is out of range")
        except Exception:
            errors.append(f"{row['request_id']}: invalid amount_safe_to_pay")
        for field, values in ENUMS.items():
            if row[field] not in values:
                errors.append(f"{row['request_id']}: invalid {field}")
        if row["recommended_payment_method"] == "not_recommended" and row["payment_plan"] != "none":
            errors.append(f"{row['request_id']}: not_recommended must have payment_plan=none")
        try:
            plan = parse_plan(row["payment_plan"])
        except Exception:
            errors.append(f"{row['request_id']}: malformed payment_plan")
            plan = []
        if plan != sorted(plan, key=lambda item: item[0]):
            errors.append(f"{row['request_id']}: payment_plan is not chronological")
        method = row["recommended_payment_method"]
        profile = profiles[request["user_id"]]
        accepted = set(profile["payment_methods_user_will_consider"].split("|"))
        required_preference = "full_payment" if method == "wait" else method
        if method not in {"not_recommended"} and required_preference not in accepted:
            errors.append(f"{row['request_id']}: method conflicts with user preferences")
        requested_amount = Decimal(request["requested_amount"])
        request_date = date.fromisoformat(request["request_date"])
        desired_date = date.fromisoformat(request["desired_completion_date"])
        earliest_text = row["earliest_date_for_full_payment"]
        earliest = date.fromisoformat(earliest_text) if earliest_text else None
        status = row["affordability_status"]
        if status == "affordable_now" and (method != "full_payment" or earliest != request_date):
            errors.append(f"{row['request_id']}: affordable_now relationship is invalid")
        if status == "affordable_later" and (
            method != "wait" or earliest is None or earliest > desired_date
        ):
            errors.append(f"{row['request_id']}: affordable_later relationship is invalid")
        if status == "not_affordable" and method != "not_recommended":
            errors.append(f"{row['request_id']}: not_affordable must be not_recommended")
        if earliest and not (request_date <= earliest <= request_date + timedelta(days=90)):
            errors.append(f"{row['request_id']}: earliest full-payment date is outside forecast")
        if plan and plan[-1][0] > desired_date and method != "not_recommended":
            errors.append(f"{row['request_id']}: recommended plan misses desired completion date")
        if method in {"full_payment", "wait"}:
            if len(plan) != 1 or abs(plan[0][1] - requested_amount) > Decimal("0.01"):
                errors.append(f"{row['request_id']}: full/wait plan must contain one full payment")
        if method == "partial_payment":
            if request["allows_partial_payment"].lower() != "true" or len(plan) != 2:
                errors.append(f"{row['request_id']}: invalid partial-payment eligibility or length")
            elif (
                plan[0][0] != request_date
                or abs(plan[0][1] - Decimal(row["amount_safe_to_pay"])) > Decimal("0.01")
                or abs(sum((amount for _, amount in plan), Decimal("0")) - requested_amount) > Decimal("0.01")
            ):
                errors.append(f"{row['request_id']}: partial-payment schedule is inconsistent")
        if method == "installments":
            matched = False
            for option in options.get(row["request_id"], []):
                if option["payment_method"] != "installments":
                    continue
                count = int(option["number_of_payments"])
                first = date.fromisoformat(option["first_payment_date"])
                frequency = int(option["payment_frequency_days"])
                amount = Decimal(option["payment_amount"])
                expected = [(first + timedelta(days=frequency * index), amount) for index in range(count)]
                if len(plan) == len(expected) and all(
                    actual_date == expected_date and abs(actual_amount - expected_amount) <= Decimal("0.01")
                    for (actual_date, actual_amount), (expected_date, expected_amount) in zip(plan, expected)
                ):
                    matched = True
                    break
            if not matched:
                errors.append(f"{row['request_id']}: installment schedule matches no supplied option")
        changes = [] if row["spending_changes_needed"] == "none" else row["spending_changes_needed"].split("|")
        if len(changes) > 3:
            errors.append(f"{row['request_id']}: more than three spending changes")
        seen_events: set[str] = set()
        for change in changes:
            parts = change.split(":")
            if len(parts) not in {2, 3} or parts[0] not in {"stop", "reduce_to"}:
                errors.append(f"{row['request_id']}: malformed spending change {change}")
                continue
            event = events.get(parts[1])
            if not event or event["user_id"] != request["user_id"]:
                errors.append(f"{row['request_id']}: spending change targets an invalid event")
                continue
            if parts[1] in seen_events:
                errors.append(f"{row['request_id']}: multiple changes target the same event")
            seen_events.add(parts[1])
            allowed_field = (
                "expense_categories_user_is_willing_to_stop"
                if parts[0] == "stop" else "expense_categories_user_is_willing_to_reduce"
            )
            if event["category"] not in set(profile[allowed_field].split("|")):
                errors.append(f"{row['request_id']}: spending change category is not permitted")
            compatible = (
                event["flexibility"] in {"stoppable", "reducible_or_stoppable"}
                if parts[0] == "stop"
                else event["flexibility"] in {"reducible", "reducible_or_stoppable"}
            )
            if not compatible:
                errors.append(f"{row['request_id']}: spending change conflicts with event flexibility")
        if not row["decision_explanation"].strip():
            errors.append(f"{row['request_id']}: missing decision_explanation")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--requests", type=Path, default=Path("dataset/requests.csv"))
    parser.add_argument("--truth", type=Path)
    args = parser.parse_args()
    predictions = read(args.predictions)
    requests = read(args.requests)
    errors = validate(predictions, requests, args.requests.resolve().parent)
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Valid output: {len(predictions)} rows")
    if args.truth:
        truth = {row["request_id"]: row for row in read(args.truth)}
        fields = [
            "affordability_status", "recommended_payment_method",
            "earliest_date_for_full_payment", "spending_changes_needed",
        ]
        for field in fields:
            matches = sum(row[field] == truth[row["request_id"]][field] for row in predictions)
            print(f"{field}: {matches}/{len(predictions)}")
        absolute_errors = [
            abs(Decimal(row["amount_safe_to_pay"]) - Decimal(truth[row["request_id"]]["amount_safe_to_pay"]))
            for row in predictions
        ]
        print(f"amount_safe_to_pay exact: {sum(error == 0 for error in absolute_errors)}/{len(predictions)}")
        print(f"amount_safe_to_pay mean absolute error: {sum(absolute_errors) / len(absolute_errors):.2f}")
        print("\nPer-request differences:")
        for row, error in zip(predictions, absolute_errors):
            expected = truth[row["request_id"]]
            mismatches = [field for field in fields if row[field] != expected[field]]
            if error or mismatches:
                print(
                    f"{row['request_id']}: safe error={error}; "
                    f"mismatch={','.join(mismatches) or 'none'}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
