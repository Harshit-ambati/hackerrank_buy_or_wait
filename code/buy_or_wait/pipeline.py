"""Reusable end-to-end inference pipeline for CLI and browser entry points."""

from __future__ import annotations

import logging
from pathlib import Path

from .ai_evidence import OnlineEvidenceResolver
from .engine import DecisionEngine
from .models import Decision
from .submission import write_submission
from .validation import validate_decisions, validate_input_dataset


def run_pipeline(
    dataset: Path,
    requests_name: str,
    output: Path,
    usage_report: Path,
    resolver: OnlineEvidenceResolver,
    logger: logging.Logger,
) -> list[Decision]:
    dimensions = validate_input_dataset(dataset, requests_name)
    summary = ", ".join(f"{name}={count}" for name, count in sorted(dimensions.rows.items()))
    logger.info("dataset validation: passed")
    logger.info("dataset dimensions: total_rows=%d; %s", dimensions.total_rows, summary)
    logger.info("selected model: %s", ", ".join(resolver.model_names))
    logger.info("selected policy: deterministic conservative cash-flow planner")

    engine = DecisionEngine.from_directory(dataset, resolver)
    requests = engine.load_requests(dataset / requests_name)
    logger.info("data loaded: profiles=%d requests=%d", len(engine.profiles), len(requests))
    logger.info("inference started: requests=%d", len(requests))
    decisions = [engine.decide(request) for request in requests]
    logger.info("prediction completed: rows=%d", len(decisions))

    validate_decisions(decisions, requests)
    logger.info("submission validation: passed rows=%d", len(decisions))
    write_submission(decisions, output)
    resolver.write_usage_report(usage_report, len(decisions))
    logger.info("submission written: %s", output)
    return decisions
