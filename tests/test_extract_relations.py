import json
import tempfile
import unittest
from pathlib import Path

from geokg.extract_relations import (
    _extract_single_article,
    _filter_articles_by_ids,
    _load_article_ids,
)


class FakeOllamaClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat(self, **_kwargs: object) -> dict:
        return {"message": {"content": json.dumps(self.payload)}}


class ExtractRelationsArticleSelectionTest(unittest.TestCase):
    def test_load_article_ids_from_gold_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "gold.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"article_id": "a-1", "events": []}),
                        json.dumps({"article_id": "a-2", "events": []}),
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(_load_article_ids(path), {"a-1", "a-2"})

    def test_load_article_ids_from_json_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ids.json"
            path.write_text(
                json.dumps(["a-1", {"article_id": "a-2"}, {"missing": "ignored"}]),
                encoding="utf-8",
            )

            self.assertEqual(_load_article_ids(path), {"a-1", "a-2"})

    def test_load_article_ids_from_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ids.txt"
            path.write_text("a-1\n\n a-2 \n", encoding="utf-8")

            self.assertEqual(_load_article_ids(path), {"a-1", "a-2"})

    def test_filter_articles_by_ids_preserves_input_order(self) -> None:
        articles = [
            {"article_id": "a-1", "title": "One"},
            {"article_id": "a-2", "title": "Two"},
            {"article_id": "a-3", "title": "Three"},
        ]

        selected = _filter_articles_by_ids(articles, {"a-3", "a-1"})

        self.assertEqual([row["article_id"] for row in selected], ["a-1", "a-3"])

    def test_extract_single_article_salvages_partial_payload_after_retries(self) -> None:
        evidence = (
            "The US military said it would stop all maritime traffic entering and "
            "exiting Iranian ports from Monday morning."
        )
        article = {
            "article_id": "test-1",
            "published_at": "2026-04-10T10:00:00+00:00",
            "url": "https://example.invalid/test-1",
            "text": evidence,
        }
        payload = {
            "entities": [
                {"name": "United States", "type": "NationState"},
                {"name": "Iranian ports", "type": "StrategicLocation"},
            ],
            "relations": [
                {
                    "source": "United States",
                    "target": "Iranian ports",
                    "type": "BLOCKADED",
                    "evidence": "The United States blockaded Iranian ports.",
                }
            ],
            "events": [
                {
                    "event_type": "BlockadeEvent",
                    "event_date": "",
                    "date_precision": "article_date",
                    "location": "Iranian ports",
                    "participants": [
                        {
                            "name": "United States",
                            "type": "NationState",
                            "role": "initiator",
                        },
                        {
                            "name": "Iranian ports",
                            "type": "StrategicLocation",
                            "role": "affected_location",
                        },
                    ],
                    "relations": [
                        {
                            "source": "United States",
                            "target": "Iranian ports",
                            "type": "BLOCKADED",
                            "evidence": evidence,
                        }
                    ],
                    "summary": "United States military said it would stop traffic at Iranian ports.",
                    "evidence": evidence,
                    "confidence": 0.82,
                }
            ],
        }

        record = _extract_single_article(
            client=FakeOllamaClient(payload),
            article=article,
            model="test-model",
            max_retries=0,
            temperature=0.0,
            num_ctx=1024,
        )

        self.assertEqual(record["validation_status"], "partial")
        self.assertGreaterEqual(len(record["validation_warnings"]), 1)
        self.assertEqual(len(record["events"]), 1)
        self.assertEqual(len(record["relations"]), 1)


if __name__ == "__main__":
    unittest.main()
