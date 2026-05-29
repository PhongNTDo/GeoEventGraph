import unittest

from geokg.evaluate import generate_annotation_candidates, score_predictions


def build_record(article_id: str = "a1") -> dict:
    return {
        "article_id": article_id,
        "title": "Article One",
        "source": "BBC News",
        "url": "https://example.invalid/a1",
        "published_at": "2026-04-10",
        "entities": [
            {"name": "Iran", "type": "NationState"},
            {"name": "Strait of Hormuz", "type": "StrategicLocation"},
        ],
        "relations": [
            {
                "source": "Iran",
                "target": "Strait of Hormuz",
                "type": "BLOCKADED",
                "evidence": "Iran blocked the strait.",
            }
        ],
        "events": [
            {
                "event_type": "BlockadeEvent",
                "event_date": "2026-04-10",
                "date_precision": "day",
                "location": "Strait of Hormuz",
                "participants": [
                    {"name": "Iran", "type": "NationState", "role": "initiator"},
                    {
                        "name": "Strait of Hormuz",
                        "type": "StrategicLocation",
                        "role": "affected_location",
                    },
                ],
                "relations": [
                    {
                        "source": "Iran",
                        "target": "Strait of Hormuz",
                        "type": "BLOCKADED",
                        "evidence": "Iran blocked the strait.",
                    }
                ],
                "summary": "Iran blocked the Strait of Hormuz.",
                "evidence": "Iran blocked the strait.",
                "confidence": 0.9,
                "location_geocode": {
                    "latitude": 26.5667,
                    "longitude": 56.25,
                    "geocode_source": "override",
                },
            }
        ],
    }


class EvaluationTest(unittest.TestCase):
    def test_generate_candidates_marks_rows_for_human_review(self) -> None:
        rows = generate_annotation_candidates([build_record()], limit=1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["annotation_status"], "needs_human_review")
        self.assertEqual(rows[0]["events"][0]["event_type"], "BlockadeEvent")
        self.assertIn("location_geocode", rows[0]["events"][0])

    def test_score_predictions_reports_perfect_match(self) -> None:
        gold = build_record()
        gold["annotation_status"] = "gold"

        report = score_predictions(
            gold_records=[gold],
            prediction_records=[build_record()],
        )

        self.assertEqual(report["metrics"]["entities"]["micro"]["f1"], 1.0)
        self.assertEqual(report["metrics"]["relations"]["micro"]["f1"], 1.0)
        self.assertEqual(report["metrics"]["events_exact"]["micro"]["f1"], 1.0)
        self.assertEqual(report["metrics"]["events_soft"]["f1"], 1.0)
        self.assertEqual(
            report["metrics"]["participants"]["by_label"]["initiator"]["f1"],
            1.0,
        )
        self.assertEqual(
            report["metrics"]["event_relations"]["by_label"]["BLOCKADED"]["f1"],
            1.0,
        )
        self.assertEqual(
            report["metrics"]["matched_event_fields"]["evidence_exact_match_rate"],
            1.0,
        )

    def test_score_predictions_rejects_draft_gold_by_default(self) -> None:
        draft = build_record()
        draft["annotation_status"] = "needs_human_review"

        with self.assertRaises(SystemExit):
            score_predictions(gold_records=[draft], prediction_records=[build_record()])

    def test_score_predictions_tracks_missing_prediction_article(self) -> None:
        gold = build_record("missing")
        gold["annotation_status"] = "gold"

        report = score_predictions(gold_records=[gold], prediction_records=[])

        self.assertEqual(report["missing_prediction_article_ids"], ["missing"])
        self.assertEqual(report["metrics"]["events_soft"]["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
