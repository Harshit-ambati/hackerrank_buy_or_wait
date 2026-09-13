from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


CODE_DIR = Path(__file__).resolve().parents[1]
ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from buy_or_wait.ai_evidence import (  # noqa: E402
    EvidenceAPIError,
    OnlineEvidenceResolver,
    UsageEntry,
)


class FailingBackend:
    provider = "openai"
    model = "test-openai"

    def generate(self, prompt, schema_name, schema, image_path=None):
        del prompt, schema_name, schema, image_path
        raise EvidenceAPIError("temporary failure")


class SuccessfulBackend:
    provider = "gemini"
    model = "test-gemini"

    def generate(self, prompt, schema_name, schema, image_path=None):
        del prompt, schema_name, schema, image_path
        return (
            {"amount": "704.05", "currency": "INR", "basis": "total"},
            UsageEntry("gemini", self.model, 100, 12),
        )


class OnlineEvidenceTests(unittest.TestCase):
    def test_online_only_mode_rejects_missing_keys(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EvidenceAPIError):
                OnlineEvidenceResolver.from_environment("auto")

    def test_auto_mode_fails_over_between_providers(self) -> None:
        resolver = OnlineEvidenceResolver([FailingBackend(), SuccessfulBackend()])
        amount = resolver.extract_image_amount(
            ROOT / "dataset" / "media" / "images" / "image_05.png",
            {
                "event_type": "expense", "category": "utilities",
                "description": "Monthly bill", "direction": "debit", "currency": "INR",
            },
        )
        self.assertEqual(Decimal("704.05"), amount)
        self.assertEqual("gemini", resolver.usage[0].provider)

    def test_usage_report_contains_tokens_and_cost(self) -> None:
        resolver = OnlineEvidenceResolver([SuccessfulBackend()])
        resolver.usage.append(UsageEntry("gemini", "gemini-2.5-flash", 1000, 100))
        target = Path(__file__).resolve().parent / "_usage_report.md"
        try:
            resolver.write_usage_report(target, 10)
            report = target.read_text(encoding="utf-8")
            self.assertIn("Input tokens: 1000", report)
            self.assertIn("Estimated total model cost: USD", report)
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
