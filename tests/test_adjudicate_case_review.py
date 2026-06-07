import unittest

from geokg.adjudicate_case_review import adjudicate_case_review


def event(summary: str, *, event_type: str = "ThreatEvent") -> dict:
    return {
        "event_type": event_type,
        "event_date": "2026-04-10",
        "date_precision": "day",
        "location": "Iran",
        "participants": [
            {"name": "United States", "type": "NationState", "role": "initiator"},
            {"name": "Iran", "type": "NationState", "role": "target"},
        ],
        "relations": [
            {
                "source": "United States",
                "target": "Iran",
                "type": "THREATENED",
                "evidence": summary,
            }
        ],
        "summary": summary,
        "evidence": summary,
        "confidence": 0.99,
    }


class AdjudicateCaseReviewTest(unittest.TestCase):
    def test_applies_review_decisions_to_events(self) -> None:
        gold_records = [
            {
                "article_id": "a1",
                "title": "Article",
                "source": "BBC News",
                "source_url": "https://example.invalid/a1",
                "published_at": "2026-04-10T00:00:00+00:00",
                "annotation_status": "gold",
                "entities": [
                    {"name": "United States", "type": "NationState", "aliases": ["US"]},
                    {"name": "Iran", "type": "NationState", "aliases": []},
                ],
                "relations": [],
                "events": [
                    event("gold matched"),
                    event("gold missed"),
                    event("gold dropped"),
                ],
            }
        ]
        prediction_records = [
            {
                "article_id": "a1",
                "title": "Article",
                "entities": [
                    {"name": "United States", "type": "NationState"},
                    {"name": "Iran", "type": "NationState"},
                ],
                "relations": [],
                "events": [
                    event("hybrid matched"),
                    event("hybrid extra"),
                ],
            }
        ]
        review_rows = [
            {
                "article_id": "a1",
                "status": "matched",
                "gold_index": 0,
                "hybrid_index": 0,
                "review_decision": "hybrid_better",
            },
            {
                "article_id": "a1",
                "status": "missed_gold",
                "gold_index": 1,
                "hybrid_index": None,
                "review_decision": "gold_correct",
            },
            {
                "article_id": "a1",
                "status": "extra_hybrid",
                "gold_index": None,
                "hybrid_index": 1,
                "review_decision": "hybrid_better",
            },
            {
                "article_id": "a1",
                "status": "missed_gold",
                "gold_index": 2,
                "hybrid_index": None,
                "review_decision": "both_wrong",
            },
        ]

        result = adjudicate_case_review(
            review_rows=review_rows,
            gold_records=gold_records,
            prediction_records=prediction_records,
        )

        output = result["records"][0]
        self.assertEqual(
            [item["summary"] for item in output["events"]],
            ["hybrid matched", "gold missed", "hybrid extra"],
        )
        self.assertEqual(output["annotation_status"], "gold")
        self.assertEqual(result["summary"]["source_counts"], {"dropped": 1, "gold": 1, "hybrid": 2})
        self.assertIn({"name": "United States", "type": "NationState", "aliases": ["US"]}, output["entities"])
        self.assertEqual(
            [item for item in output["entities"] if item["name"] == "Iran"],
            [{"name": "Iran", "type": "NationState", "aliases": []}],
        )
        self.assertEqual(len(output["relations"]), 3)

    def test_both_correct_matched_uses_hybrid_event(self) -> None:
        result = adjudicate_case_review(
            review_rows=[
                {
                    "article_id": "a1",
                    "status": "matched",
                    "gold_index": 0,
                    "hybrid_index": 0,
                    "review_decision": "both_correct",
                }
            ],
            gold_records=[{"article_id": "a1", "events": [event("gold")]}],
            prediction_records=[{"article_id": "a1", "events": [event("hybrid")]}],
        )

        self.assertEqual(result["records"][0]["events"][0]["summary"], "hybrid")


if __name__ == "__main__":
    unittest.main()
