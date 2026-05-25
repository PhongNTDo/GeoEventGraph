import unittest

from geokg.extraction import normalize_model_json, validate_extraction_payload


ARTICLE = {
    "article_id": "test-1",
    "published_at": "2026-04-10T10:00:00+00:00",
    "text": (
        'The US military said it would stop all maritime traffic entering and exiting '
        'Iranian ports from Monday morning.'
    ),
}


class ExtractionValidationTest(unittest.TestCase):
    def test_accepts_valid_payload(self) -> None:
        payload = {
            "entities": [
                {"name": "United States", "type": "NationState"},
                {"name": "Iran", "type": "NationState"},
            ],
            "relations": [
                {
                    "source": "United States",
                    "target": "Iran",
                    "type": "BLOCKADED",
                    "evidence": "The US military said it would stop all maritime traffic entering and exiting Iranian ports from Monday morning.",
                }
            ],
        }

        result = validate_extraction_payload(payload, ARTICLE)

        self.assertTrue(result.ok)
        self.assertEqual(result.normalized["relations"][0]["type"], "BLOCKADED")

    def test_accepts_direct_event_and_merges_inner_relation(self) -> None:
        evidence = (
            "The US military said it would stop all maritime traffic entering and "
            "exiting Iranian ports from Monday morning."
        )
        payload = {
            "entities": [
                {"name": "United States", "type": "NationState"},
                {"name": "Iranian ports", "type": "StrategicLocation"},
            ],
            "relations": [],
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

        result = validate_extraction_payload(payload, ARTICLE)

        self.assertTrue(result.ok)
        self.assertEqual(result.normalized["events"][0]["event_type"], "BlockadeEvent")
        self.assertEqual(result.normalized["events"][0]["event_date"], "2026-04-10")
        self.assertEqual(result.normalized["relations"][0]["type"], "BLOCKADED")

    def test_rejects_invalid_relation_type(self) -> None:
        payload = {
            "entities": [
                {"name": "United States", "type": "NationState"},
                {"name": "Iran", "type": "NationState"},
            ],
            "relations": [
                {
                    "source": "United States",
                    "target": "Iran",
                    "type": "PRESSURED",
                    "evidence": "The US military said it would stop all maritime traffic entering and exiting Iranian ports from Monday morning.",
                }
            ],
        }

        result = validate_extraction_payload(payload, ARTICLE)

        self.assertFalse(result.ok)
        self.assertIn("must be one of", result.errors[0])

    def test_extracts_json_from_code_fence(self) -> None:
        raw = """```json
{"entities":[],"relations":[]}
```"""

        parsed = normalize_model_json(raw)

        self.assertEqual(parsed, {"entities": [], "relations": []})


if __name__ == "__main__":
    unittest.main()
