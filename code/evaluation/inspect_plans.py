"""Show safety margins for all eligible raw payment plans."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.engine import DecisionEngine  # noqa: E402
from buy_or_wait.models import CandidatePlan  # noqa: E402


root = Path(__file__).resolve().parents[2]
engine = DecisionEngine.from_directory(root / "dataset")
requests = {row.request_id: row for row in engine.load_requests(root / "dataset" / "sample_requests.csv")}
for request_id in sys.argv[1:]:
    request = requests[request_id]
    forecast, changes = engine._build_forecast(request)
    profile = engine.profiles[request.user_id]
    print(f"--- {request_id} floor={forecast.minimum_balance}")
    raw = [CandidatePlan("full_payment", [(request.request_date, request.amount)], request.amount)]
    for option in engine.options_by_request[request_id]:
        if option.method == "installments":
            raw.append(CandidatePlan(
                "installments",
                [(option.first_payment_date + timedelta(days=(option.frequency_days or 0) * index), option.payment_amount)
                 for index in range(option.number_of_payments)],
                option.total_payable,
                option.option_id,
            ))
    for plan in raw:
        margin = engine._minimum_balance(forecast, plan.payments) - forecast.minimum_balance
        print(plan.method, plan.option_id, "payments", len(plan.payments), "margin", margin)
        for change in changes:
            changed_margin = engine._minimum_balance(forecast, plan.payments, (change,)) - forecast.minimum_balance
            print("  ", change.text, "margin", changed_margin)
