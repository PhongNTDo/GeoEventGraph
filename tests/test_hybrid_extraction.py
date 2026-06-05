import json
import unittest

from geokg.hybrid_extraction import (
    PROMPT_VERSION,
    build_parser,
    build_repaired_relations,
    extract_article_hybrid,
)


ARTICLE = {
    "article_id": "test-1",
    "title": "Test article",
    "source": "BBC News",
    "published_at": "2026-04-10T10:00:00+00:00",
    "url": "https://example.invalid/test-1",
    "text": (
        "The US military said it would stop all maritime traffic entering and "
        "exiting Iranian ports from Monday morning."
    ),
}


class FakeOllamaClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def chat(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        if not self.payloads:
            raise AssertionError("No fake payloads left.")
        return {"message": {"content": json.dumps(self.payloads.pop(0))}}


def candidate_record(event: dict) -> dict:
    return {
        "article_id": ARTICLE["article_id"],
        "title": ARTICLE["title"],
        "source": ARTICLE["source"],
        "published_at": ARTICLE["published_at"],
        "url": ARTICLE["url"],
        "model": "gpt-oss:120b",
        "prompt_version": "event-v1",
        "entities": [
            {"name": "United States", "type": "NationState"},
            {"name": "Iranian ports", "type": "StrategicLocation"},
            {"name": "Extra baseline entity", "type": "StrategicLocation"},
        ],
        "relations": [],
        "events": [event],
    }


class HybridExtractionTest(unittest.TestCase):
    def test_parser_accepts_wrapper_retry_argument(self) -> None:
        args = build_parser().parse_args(["--max-retries", "2"])

        self.assertEqual(args.max_retries, 2)

    def test_repaired_relations_use_priority_target_roles(self) -> None:
        participants = [
            {"name": "Israel", "type": "NationState", "role": "initiator"},
            {"name": "Iran", "type": "NationState", "role": "target"},
            {"name": "Tehran", "type": "StrategicLocation", "role": "affected_location"},
        ]

        relations = build_repaired_relations("AttackEvent", participants, "Israel hit Iran.")

        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["target"], "Iran")

    def test_hybrid_verifier_repairs_event_and_rebuilds_relations(self) -> None:
        evidence = ARTICLE["text"]
        original_event = {
            "event_id": "event:test-1:001:blockadeevent",
            "event_type": "ThreatEvent",
            "event_date": "",
            "date_precision": "article_date",
            "location": "Iranian ports",
            "participants": [
                {"name": "United States", "type": "NationState", "role": "initiator"}
            ],
            "relations": [],
            "summary": "The US threatened maritime traffic.",
            "evidence": evidence,
            "confidence": 0.5,
        }
        client = FakeOllamaClient(
            [
                {
                    "keep": True,
                    "event_type": "BlockadeEvent",
                    "event_date": "",
                    "date_precision": "article_date",
                    "location": "Iranian ports",
                    "summary": (
                        "The US military said it would stop maritime traffic at "
                        "Iranian ports."
                    ),
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
                    "confidence": 0.86,
                    "repair_notes": "Changed threat to blockade.",
                    "drop_reason": "",
                }
            ]
        )

        record, diagnostics = extract_article_hybrid(
            client=client,
            article=ARTICLE,
            candidate_record=candidate_record(original_event),
            model="test-model",
            temperature=0,
            num_ctx=1024,
        )

        self.assertEqual(record["prompt_version"], PROMPT_VERSION)
        self.assertEqual(record["candidate_prompt_version"], "event-v1")
        self.assertEqual(record["extraction_method"], "hybrid_event_v1_verifier")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(record["events"]), 1)
        event = record["events"][0]
        self.assertEqual(event["event_type"], "BlockadeEvent")
        self.assertEqual(event["event_date"], "2026-04-10")
        self.assertEqual(event["evidence"], evidence)
        self.assertEqual(event["relations"][0]["type"], "BLOCKADED")
        self.assertEqual(event["relations"][0]["target"], "Iranian ports")
        self.assertIn(
            {"name": "Extra baseline entity", "type": "StrategicLocation"},
            record["entities"],
        )
        self.assertEqual(diagnostics["candidate_event_count"], 1)
        self.assertEqual(diagnostics["event_count"], 1)
        self.assertEqual(diagnostics["repaired_count"], 1)

    def test_hybrid_verifier_can_drop_candidate(self) -> None:
        evidence = ARTICLE["text"]
        original_event = {
            "event_type": "BlockadeEvent",
            "event_date": "",
            "date_precision": "article_date",
            "location": "Iranian ports",
            "participants": [
                {"name": "United States", "type": "NationState", "role": "initiator"}
            ],
            "relations": [],
            "summary": "Draft event.",
            "evidence": evidence,
            "confidence": 0.5,
        }
        client = FakeOllamaClient(
            [
                {
                    "keep": False,
                    "event_type": "BlockadeEvent",
                    "event_date": "",
                    "date_precision": "article_date",
                    "location": "",
                    "summary": "",
                    "participants": [],
                    "confidence": 0,
                    "repair_notes": "",
                    "drop_reason": "not a geopolitical event",
                }
            ]
        )

        record, diagnostics = extract_article_hybrid(
            client=client,
            article=ARTICLE,
            candidate_record=candidate_record(original_event),
            model="test-model",
            temperature=0,
            num_ctx=1024,
        )

        self.assertEqual(record["events"], [])
        self.assertEqual(diagnostics["dropped_count"], 1)
        self.assertEqual(diagnostics["dropped"][0]["stage"], "event_verifier")

    def test_skip_verifier_repairs_support_roles_before_relation_building(self) -> None:
        article = {
            **ARTICLE,
            "text": "Iran is Hamas's biggest backer in terms of funding and weapons.",
        }
        evidence = article["text"]
        original_event = {
            "event_type": "SupportEvent",
            "event_date": "",
            "date_precision": "article_date",
            "location": "",
            "participants": [
                {"name": "Iran", "type": "NationState", "role": "initiator"},
                {"name": "Hamas", "type": "NonStateActor", "role": "target"},
            ],
            "relations": [],
            "summary": "Iran supports Hamas.",
            "evidence": evidence,
            "confidence": 1.0,
        }
        record_in = {
            **candidate_record(original_event),
            "entities": [
                {"name": "Iran", "type": "NationState"},
                {"name": "Hamas", "type": "NonStateActor"},
            ],
        }
        client = FakeOllamaClient([])

        record, diagnostics = extract_article_hybrid(
            client=client,
            article=article,
            candidate_record=record_in,
            model="test-model",
            temperature=0,
            num_ctx=1024,
            verify=False,
        )

        self.assertEqual(client.calls, [])
        self.assertEqual(record["events"][0]["participants"][0]["role"], "supporter")
        self.assertEqual(record["events"][0]["relations"][0]["type"], "SUPPORTED")
        self.assertEqual(diagnostics["verified"], False)


if __name__ == "__main__":
    unittest.main()
