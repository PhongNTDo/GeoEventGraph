import unittest

from geokg.extraction import normalize_model_json, validate_extraction_payload


ARTICLE = {
    "article_id": "test-1",
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
