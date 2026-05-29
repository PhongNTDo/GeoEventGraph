import tempfile
import unittest
from pathlib import Path

from geokg.eval_log import append_log_row, build_log_row


REPORT = {
    "gold": {"article_count": 10, "event_count": 74},
    "predictions": {"event_count_in_scope": 65},
    "metrics": {
        "entities": {"micro": {"f1": 0.8991596638655462}},
        "relations": {"micro": {"f1": 0.8280254777070064}},
        "events_exact": {"micro": {"f1": 0.21582733812949642}},
        "events_soft": {"precision": 0.9, "recall": 0.8, "f1": 0.8489208633093526},
        "participants": {"micro": {"f1": 0.47647058823529415}},
        "event_relations": {"micro": {"f1": 0.5853658536585366}},
        "matched_event_fields": {
            "event_type_accuracy": 0.9830508474576272,
            "event_date_accuracy": 0.864406779661017,
            "evidence_exact_match_rate": 0.4067796610169492,
            "evidence_fuzzy_match_rate": 0.8305084745762712,
        },
        "geocoding": {"located_event_coordinate_rate": 0.3235294117647059},
    },
}


class EvaluationLogTest(unittest.TestCase):
    def test_build_log_row_formats_key_metrics(self) -> None:
        row = build_log_row(
            report=REPORT,
            timestamp="2026-05-30T12:00:00+00:00",
            label="baseline",
            notes="first run",
        )

        self.assertIn("| baseline |", row)
        self.assertIn("| 0.899 |", row)
        self.assertIn("| 0.216 |", row)
        self.assertIn("| first run |", row)

    def test_append_log_row_creates_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "EVALUATION_LOG.md"

            append_log_row(path, "| row |\n")

            content = path.read_text(encoding="utf-8")
            self.assertIn("# GeoKG Evaluation Log", content)
            self.assertTrue(content.endswith("| row |\n"))


if __name__ == "__main__":
    unittest.main()
