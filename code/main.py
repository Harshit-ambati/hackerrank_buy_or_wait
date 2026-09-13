"""Command-line entry point for the Buy or Wait decision engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from buy_or_wait.ai_evidence import EvidenceAPIError, OnlineEvidenceResolver  # noqa: E402
from buy_or_wait.config import load_environment  # noqa: E402
from buy_or_wait.pipeline import run_pipeline  # noqa: E402
from buy_or_wait.runtime_logging import configure_logging  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate safe payment recommendations for Buy or Wait requests."
    )
    repo_root = CODE_DIR.parent
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repo_root / "dataset",
        help="Directory containing the challenge CSV files.",
    )
    parser.add_argument(
        "--requests",
        default="requests.csv",
        help="Request CSV inside --dataset (use sample_requests.csv to evaluate samples).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "output.csv",
        help="Destination CSV path.",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print a compact summary for every generated decision.",
    )
    parser.add_argument(
        "--usage-report",
        type=Path,
        default=repo_root / "code" / "evaluation" / "usage_report.md",
        help="Destination for token-usage reporting from this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment(CODE_DIR.parent / ".env")
    logger = configure_logging()
    try:
        resolver = OnlineEvidenceResolver.from_environment()
        decisions = run_pipeline(
            args.dataset, args.requests, args.output, args.usage_report, resolver, logger
        )
    except (EvidenceAPIError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.explain:
        for decision in decisions:
            print(
                f"{decision.request_id}: {decision.affordability_status} / "
                f"{decision.recommended_payment_method} / safe today "
                f"{decision.amount_safe_to_pay}"
            )
    print(f"Wrote {len(decisions)} decisions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
