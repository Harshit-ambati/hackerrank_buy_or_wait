# HackerRank Orchestrate

## Implemented solution

This repository contains an online AI evidence agent with a deterministic Python
financial planner for **Buy or Wait?**. It reads a supplied dataset folder,
extracts image and message evidence through Gemini, forecasts cash flow,
tests seller payment options, and writes a contract-valid `output.csv`.

### Run

Python 3.11 or newer is recommended. No third-party package is required, but a
Gemini API key is mandatory. Production has no offline OCR or
hardcoded-evidence fallback.

PowerShell setup:

```powershell
$env:GEMINI_API_KEY="your-key"
python code/main.py --dataset dataset --output output.csv
```

Alternatively, copy `.env.example` to `.env` and set `GEMINI_API_KEY` there.
The project loads this ignored file automatically and never overrides variables
already exported by the shell.

Every evidence request uses Gemini and fails closed if the key, network, image,
or structured response is unavailable. Never commit keys or place real keys in
`.env.example`.

Browser interface:

```powershell
python code/web.py
```

Then open `http://127.0.0.1:8765`. The Gemini key stays in the server process and
is never sent to or displayed in the browser page.

```bash
python code/main.py
```

Useful alternatives:

```bash
# Generate decisions for the solved public examples
python code/main.py --requests sample_requests.csv --output sample_predictions.csv

# Score those decisions against the public examples
python code/evaluation/main.py sample_predictions.csv \
  --requests dataset/sample_requests.csv \
  --truth dataset/sample_requests.csv

# Validate the final submission file
python code/evaluation/main.py output.csv --requests dataset/requests.csv

# Run the automated tests
python -m unittest discover -s code/tests -v
```

On Windows PowerShell, the same commands work with `python` and backslashes.

### Decision pipeline

1. Validate schemas, identifiers, and cross-file relationships before any API call.
2. Load and type-check profiles, requests, financial events, payment options,
   dated exchange rates, messages, and image links.
3. Extract image-backed blank amounts online with a vision-capable provider and
   normalize message evidence into a strict JSON schema.
4. Resolve cash state and linked lifecycles: reserve pending debits once, ignore
   pending credits, cancelled authorizations, refunded charges, and unrealized
   investments, and avoid double-counting a failed debit with its scheduled retry.
5. Infer supported monthly commitments and salary cycles. Message evidence can
   move or replace payroll, stop ended income, add one-time arrears or approved
   invoice income, convert dated foreign salary, or adjust recurring rent.
6. Forecast fixed commitments and calendar-shaped variable spending for 90 days.
7. Compute safe capacity and evaluate full, partial, installment, wait, and
   permitted spending-change candidates.
8. Rank safe plans by the challenge rules and validate the emitted schema,
   schedules, user preferences, and change targets.
9. Validate one decision per request, write the submission, and record model usage.

Runtime logs are intentionally concise. They report input dimensions, the selected
Gemini model and deterministic policy, inference start/completion, and submission
validation. There are no training or cross-validation logs because the submitted
system is an inference-only financial rules engine; the solved sample labels are
used only by evaluation tests.

### Code organization

```text
code/buy_or_wait/
├── config.py            # Project-local environment loading
├── data_loading.py      # Typed CSV loading and evidence attachment
├── validation.py        # Input and prediction-contract validation
├── ai_evidence.py       # Gemini preprocessing for messages and images
├── evidence.py          # Canonical evidence parsing
├── engine.py            # Forecast features and deterministic inference
├── pipeline.py          # Shared CLI/browser orchestration
├── submission.py        # output.csv generation
├── runtime_logging.py   # Concise stage logging
└── models.py            # Typed domain objects
```

### Essential obligations and taxes

Before recommending any purchase or service, the forecast reserves confirmed
and recurring education fees, childcare or family support, housing or rent,
loan repayments, utilities, groceries, insurance, transport, and ordinary
monthly spending. Categories marked as protected or as a financial priority
are never offered as spending cuts.

Tax-labelled receipt and invoice rows use the document's final tax-inclusive
total. They are not charged a second time. A separate tax liability would be
reserved only when the supplied events or messages contain a confirmed amount
and settlement date; the engine does not invent an unsupported future tax.

Financial arithmetic, plan feasibility, and ranking remain deterministic. The
evidence stage is online and model-backed; structured schemas and semantic
validation prevent malformed evidence from reaching the planner.

Starter repository for the **HackerRank Orchestrate** 24-hour hackathon (September 2026).

## Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **"Can I afford this laptop?"**

Answering well takes more than the current balance. The agent must account for recurring expenses, pending payments, essential spending, confirmed income, available payment options, and relevant details buried in messages and images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation must be personalized: two users with the same balance can deserve different answers based on their commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

A recommendation is safe only if the user can complete the full payment plan, cover essential expenses, and stay above their preferred minimum balance throughout the forecast period.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, allowed values, conflict-resolution rules, and submission format.

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26
```

Build your solution in `code/main.py`, or use another language and document its entry point clearly.

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction for every request
- Write the final predictions to `output.csv` in the repository root

Run the starter Python entry point with:

```bash
python3 code/main.py
```

After running your solution, confirm that `output.csv` exists in the repository root and contains the required columns and one row for every request.

## Important File Locations

```text
dataset/        Input data and the blank output template. Do not modify the input data.
code/           Your solution code.
output.csv      Final generated predictions in the repository root.
code.zip        ZIP file containing your complete solution for submission.
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file must be the root-level `output.csv`.

---

## Repository Layout

```text
.
├── AGENTS.md                         # Rules for AI coding tools + transcript logging
├── problem_statement.md              # Full challenge statement
├── README.md                         # You are here
├── code/                             # Your solution code
├── output.csv                        # Final generated predictions
└── dataset/
    ├── requests.csv                  # 250 requests to evaluate — predict these
    ├── output.csv                    # Blank submission template
    ├── sample_requests.csv           # 25 solved examples
    ├── financial_profiles.csv        # Balances, minimum balance, priorities, preferences
    ├── financial_events.csv          # Historical, pending, and confirmed transactions
    ├── request_payment_options.csv   # Payment options available per request
    ├── exchange_rates.csv            # Fixed, dated conversion rates
    ├── messages.csv                  # Messages tied to users, requests, or events
    ├── images.csv                    # Payroll letters, statements, bills, receipts
    └── media/
        └── images/
```

Only `dataset/requests.csv` requires predictions. Everything else is context. Join user records with `user_id`, request records with `request_id`, supporting evidence with `related_event_id`, and exchange rates with the rate date and currency pair.

Amounts are in the user's `home_currency` — the dataset uses INR, ZAR, IDR, USD, and EUR, and every conversion rate you need is in `exchange_rates.csv`. All dates are `YYYY-MM-DD`. Live exchange rates, market data, and banking access are not required.

---

## What You Need to Build

For every row in `dataset/requests.csv`, produce one row in `output.csv` with:

| Column | Meaning |
|---|---|
| `request_id` | The request being answered |
| `amount_safe_to_pay` | Largest amount safe to pay on `request_date` before optional spending changes, after protecting essentials and the minimum balance |
| `affordability_status` | `affordable_now`, `affordable_with_plan`, `affordable_later`, or `not_affordable` |
| `recommended_payment_method` | `full_payment`, `partial_payment`, `installments`, `wait`, or `not_recommended` |
| `payment_plan` | Chronological `<YYYY-MM-DD>:<amount>` entries joined by `\|`, or `none` |
| `earliest_date_for_full_payment` | Earliest date the full amount is forecast safe as one payment; empty if never within the forecast |
| `spending_changes_needed` | Up to three `stop:<event_id>` / `reduce_to:<event_id>:<amount>` changes joined by `\|`, or `none` |
| `decision_explanation` | Short explanation and the financial facts behind it |

`0 <= amount_safe_to_pay <= requested_amount` must always hold. Installment plans must exactly match a supplied payment option, and only recurring expenses marked flexible may be changed.

`affordable_with_plan` means the full request is completed through a partial-payment schedule, installments, or permitted spending changes. Recommend `partial_payment` only when the request allows it, the user accepts it, `0 < amount_safe_to_pay < requested_amount`, and `earliest_date_for_full_payment` is on or before `desired_completion_date`. Use exactly two payments: pay `amount_safe_to_pay` on `request_date`, then pay the remaining amount on `earliest_date_for_full_payment`. The two payments must add up to `requested_amount`. Unlike installments, partial payment does not need to match a supplied payment option.

---

## Suggested Workflow

1. Inspect `dataset/sample_requests.csv` — 25 requests with completed output columns — to understand the expected format and decision style.
2. Reconstruct each user's financial state from `financial_profiles.csv` and `financial_events.csv`: separate recurring expenses from one-time events, reserve pending transactions, count confirmed salary only on its settlement date, and de-duplicate repeated representations of the same event.
3. When an event has a blank `amount`, find its `event_id` as `related_event_id` in `images.csv` and extract the amount from the linked image. Never treat a blank amount as zero. Pull in any other relevant messages, images, and payment options for the request.
4. Forecast forward and generate a plan that keeps the balance above the minimum at every step.
5. Verify deterministically — bounds, plan feasibility, schedule match, flexible-only spending changes — before writing `output.csv`.
6. Score yourself on the solved samples, then run the full dataset.

You may use any language or runtime. Python, JavaScript, and TypeScript are all reasonable choices.

---

## Requirements

Your solution must:

- be runnable from the terminal
- read the provided files from `dataset/`
- produce a valid `output.csv` with the exact required columns in the exact required order
- include one prediction for every `request_id` in `dataset/requests.csv`
- not use organizer-only files or hardcoded labels
- keep behavior deterministic where possible

Gemini credentials are required in production and must be read from an
environment variable. Never hardcode secrets in the repository.

---

## Evaluation

Your `output.csv` will be compared against hidden ground-truth values.

The scoring will consider:

- accuracy of `amount_safe_to_pay`
- correctness of `affordability_status`
- correctness of `recommended_payment_method` and `payment_plan`
- accuracy of `earliest_date_for_full_payment`
- validity of `spending_changes_needed`
- usefulness and consistency of `decision_explanation`

### Token Usage And Cost Analysis

Your `code.zip` must include one token-usage file:

```text
evaluation/usage_report.md
```

The report must cover model providers and names, model calls, input and output tokens, total and average tokens per request, estimated total and per-request cost. The reported values must correspond to the final full-dataset run that produced your `output.csv`.

---

## Chat Transcript Logging

This repo includes an [`AGENTS.md`](./AGENTS.md) file for AI coding tools. It asks compatible tools to append conversation summaries to a `log.txt` in the repository root — the same directory as `AGENTS.md`:

| Platform | Path |
|---|---|
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

The path resolves relative to `AGENTS.md`, so it stays correct across clones, renames, and checkouts. `log.txt` is gitignored — upload it as your chat transcript at submission time. Do not paste secrets into the chat.

In case, the harness you are using is not in the repo root, you can explicitly ask the agent to look for the AGENTS.md in this folder & then continue.

---

## Submission

Submit the following files as instructed by HackerRank:

| File | Description |
|---|---|
| `code.zip` | Full runnable solution, prompts/configuration, README, and the required `evaluation/` folder |
| `output.csv` | Predictions for every row in `dataset/requests.csv` |
| `chat_transcript` | The `log.txt` described above, showing how you developed or used the system |

Before submitting, confirm:

- `output.csv` has one row per row in `dataset/requests.csv` (250 rows plus the header).
- `output.csv` has the exact required columns in the exact required order.
- Every `amount_safe_to_pay` satisfies `0 <= amount_safe_to_pay <= requested_amount`.
- Every installment plan matches a supplied payment option, and every spending change targets a flexible recurring expense.
- Your runnable code, setup instructions, and `evaluation/` folder are included in `code.zip`.
