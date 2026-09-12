from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parents[1]
ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from buy_or_wait.engine import DecisionEngine, OUTPUT_COLUMNS  # noqa: E402
from buy_or_wait.evidence import IMAGE_AMOUNTS  # noqa: E402


class DecisionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = ROOT / "dataset"
        cls.engine = DecisionEngine.from_directory(cls.dataset)

    def test_all_image_backed_amounts_are_available(self) -> None:
        with (self.dataset / "images.csv").open(encoding="utf-8-sig", newline="") as fh:
            image_ids = {row["image_id"] for row in csv.DictReader(fh)}
        self.assertEqual(image_ids, set(IMAGE_AMOUNTS))

    def test_public_sample_method_accuracy_is_high(self) -> None:
        sample_path = self.dataset / "sample_requests.csv"
        decisions = {item.request_id: item for item in self.engine.run(sample_path)}
        with sample_path.open(encoding="utf-8-sig", newline="") as fh:
            truth = list(csv.DictReader(fh))
        method_matches = sum(
            decisions[row["request_id"]].recommended_payment_method
            == row["recommended_payment_method"]
            for row in truth
        )
        status_matches = sum(
            decisions[row["request_id"]].affordability_status
            == row["affordability_status"]
            for row in truth
        )
        self.assertGreaterEqual(method_matches, 24)
        self.assertGreaterEqual(status_matches, 24)

    def test_full_output_has_exact_contract(self) -> None:
        decisions = self.engine.run(self.dataset / "requests.csv")
        self.assertEqual(250, len(decisions))
        target = Path(__file__).resolve().parent / "_test_output.csv"
        try:
            self.engine.write_output(decisions, target)
            with target.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
            self.assertEqual(OUTPUT_COLUMNS, reader.fieldnames)
            self.assertEqual(250, len(rows))
            self.assertEqual(250, len({row["request_id"] for row in rows}))
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
