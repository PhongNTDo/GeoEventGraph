import csv
import tempfile
import unittest
from pathlib import Path

from geokg.case_review import build_case_review, write_case_review


GOLD_RECORD = {
    "article_id": "a1",
    "title": "Gold article",
    "annotation_status": "gold",
    "entities": [
        {"name": "Iran", "type": "NationState"},
        {"name": "Hamas", "type": "NonStateActor"},
    ],
    "relations": [
        {"source": "Iran", "target": "Hamas", "type": "SUPPORTED", "evidence": "Iran backs Hamas."}
    ],
    "events": [
        {
            "event_type": "SupportEvent",
            "event_date": "2026-04-10",
            "date_precision": "day",
            "location": "",
            "participants": [
                {"name": "Iran", "type": "NationState", "role": "supporter"},
                {"name": "Hamas", "type": "NonStateActor", "role": "target"},
            ],
            "relations": [
                {
                    "source": "Iran",
                    "target": "Hamas",
                    "type": "SUPPORTED",
                    "evidence": "Iran backs Hamas.",
                }
            ],
            "summary": "Iran backs Hamas.",
            "evidence": "Iran backs Hamas.",
        },
        {
            "event_type": "AttackEvent",
            "event_date": "2026-04-10",
            "date_precision": "day",
            "location": "Tehran",
            "participants": [
                {"name": "Israel", "type": "NationState", "role": "initiator"},
                {"name": "Tehran", "type": "StrategicLocation", "role": "target"},
            ],
            "relations": [
                {
                    "source": "Israel",
                    "target": "Tehran",
                    "type": "ATTACKED",
                    "evidence": "Israel hit Tehran.",
                }
            ],
            "summary": "Israel hit Tehran.",
            "evidence": "Israel hit Tehran.",
        },
    ],
}


PREDICTION_RECORD = {
    "article_id": "a1",
    "title": "Gold article",
    "entities": [
        {"name": "Iran", "type": "NationState"},
        {"name": "Hamas", "type": "NonStateActor"},
        {"name": "United States", "type": "NationState"},
    ],
    "relations": [
        {"source": "Iran", "target": "Hamas", "type": "SUPPORTED", "evidence": "Iran backs Hamas."}
    ],
    "events": [
        {
            "event_type": "SupportEvent",
            "event_date": "2026-04-10",
            "date_precision": "article_date",
            "location": "",
            "participants": [
                {"name": "Iran", "type": "NationState", "role": "supporter"},
                {"name": "Hamas", "type": "NonStateActor", "role": "target"},
            ],
            "relations": [
                {
                    "source": "Iran",
                    "target": "Hamas",
                    "type": "SUPPORTED",
                    "evidence": "Iran backs Hamas.",
                }
            ],
            "summary": "Iran backs Hamas.",
            "evidence": "Iran backs Hamas.",
        },
        {
            "event_type": "ThreatEvent",
            "event_date": "2026-04-10",
            "date_precision": "day",
            "location": "",
            "participants": [
                {"name": "United States", "type": "NationState", "role": "initiator"},
                {"name": "Iran", "type": "NationState", "role": "target"},
            ],
            "relations": [
                {
                    "source": "United States",
                    "target": "Iran",
                    "type": "THREATENED",
                    "evidence": "The US warned Iran.",
                }
            ],
            "summary": "The US warned Iran.",
            "evidence": "The US warned Iran.",
        },
    ],
}


class CaseReviewTest(unittest.TestCase):
    def test_builds_case_review_with_matched_missed_and_extra_events(self) -> None:
        review = build_case_review(
            gold_records=[GOLD_RECORD],
            prediction_records=[PREDICTION_RECORD],
            article_records=[
                {
                    "article_id": "a1",
                    "text": "Iran backs Hamas. Israel hit Tehran. The US warned Iran.",
                }
            ],
        )

        article = review["articles"][0]
        self.assertEqual(review["summary"]["matched_events"], 1)
        self.assertEqual(review["summary"]["missed_gold_events"], 1)
        self.assertEqual(review["summary"]["extra_prediction_events"], 1)
        self.assertEqual(article["matched_events"][0]["field_mismatches"], ["date_precision"])
        self.assertEqual(article["entity_diff"]["extra"][0]["name"], "United States")
        self.assertIn("Iran backs Hamas.", article["matched_events"][0]["gold_event"]["source_context"])

    def test_writes_index_csv_json_and_article_markdown(self) -> None:
        review = build_case_review(
            gold_records=[GOLD_RECORD],
            prediction_records=[PREDICTION_RECORD],
            article_records=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_case_review(review, output_dir)

            self.assertTrue((output_dir / "index.md").exists())
            self.assertTrue((output_dir / "case_review.json").exists())
            self.assertTrue((output_dir / "articles" / "a1.md").exists())
            with (output_dir / "case_review.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertIn("review_decision", rows[0])
            self.assertEqual(rows[0]["status"], "matched")
            self.assertEqual(rows[1]["status"], "missed_gold")
            self.assertEqual(rows[2]["status"], "extra_hybrid")


if __name__ == "__main__":
    unittest.main()
