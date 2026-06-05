import unittest

from geokg.extraction import (
    EVENT_ROLE_GUIDANCE,
    PROMPT_VERSION,
    attach_extraction_metadata,
    build_extraction_prompt,
    normalize_model_json,
    validate_extraction_payload,
)


ARTICLE = {
    "article_id": "test-1",
    "published_at": "2026-04-10T10:00:00+00:00",
    "url": "https://example.invalid/test-1",
    "text": (
        'The US military said it would stop all maritime traffic entering and exiting '
        'Iranian ports from Monday morning.'
    ),
}


class ExtractionValidationTest(unittest.TestCase):
    def test_prompt_version_is_event_v1_2(self) -> None:
        self.assertEqual(PROMPT_VERSION, "event-v1.2")

    def test_prompt_includes_role_templates_and_core_participant_guidance(self) -> None:
        prompt = build_extraction_prompt(ARTICLE)

        self.assertIn("Event role templates:", prompt)
        self.assertIn('"BlockadeEvent"', prompt)
        self.assertIn('"relation_type": "BLOCKADED"', prompt)
        self.assertIn(
            "Include every explicitly stated core participant needed to score the event",
            prompt,
        )
        self.assertIn("keep the attribution in the summary", prompt)
        self.assertEqual(
            EVENT_ROLE_GUIDANCE["AttackEvent"]["include_when_stated"][:2],
            ["initiator", "target"],
        )

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

    def test_partial_validation_drops_invalid_evidence_fragments(self) -> None:
        evidence = (
            "The US military said it would stop all maritime traffic entering and "
            "exiting Iranian ports from Monday morning."
        )
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
                        },
                        {
                            "source": "United States",
                            "target": "Iranian ports",
                            "type": "BLOCKADED",
                            "evidence": "The United States blockaded Iranian ports.",
                        },
                    ],
                    "summary": "United States military said it would stop traffic at Iranian ports.",
                    "evidence": evidence,
                    "confidence": 0.82,
                }
            ],
        }

        strict_result = validate_extraction_payload(payload, ARTICLE)
        partial_result = validate_extraction_payload(payload, ARTICLE, allow_partial=True)

        self.assertFalse(strict_result.ok)
        self.assertTrue(partial_result.ok)
        self.assertGreaterEqual(len(partial_result.dropped_errors), 1)
        self.assertEqual(len(partial_result.normalized["events"]), 1)
        self.assertEqual(len(partial_result.normalized["relations"]), 1)
        self.assertEqual(partial_result.normalized["relations"][0]["evidence"], evidence)

    def test_extracts_json_from_code_fence(self) -> None:
        raw = """```json
{"entities":[],"relations":[]}
```"""

        parsed = normalize_model_json(raw)

        self.assertEqual(parsed, {"entities": [], "relations": []})

    def test_attach_metadata_preserves_article_url(self) -> None:
        extraction = {"entities": [], "relations": [], "events": []}

        record = attach_extraction_metadata(ARTICLE, extraction, "test-model")

        self.assertEqual(record["url"], "https://example.invalid/test-1")


if __name__ == "__main__":
    unittest.main()
