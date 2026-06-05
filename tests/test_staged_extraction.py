import json
import unittest

from geokg.staged_extraction import (
    PROMPT_VERSION,
    build_parser,
    build_deterministic_relations,
    detect_event_candidates,
    extract_article_staged,
)


ARTICLE = {
    "article_id": "test-1",
    "title": "Test article",
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


class StagedExtractionTest(unittest.TestCase):
    def test_parser_accepts_wrapper_retry_argument(self) -> None:
        args = build_parser().parse_args(["--max-retries", "2"])

        self.assertEqual(args.max_retries, 2)

    def test_detect_candidates_keeps_only_exact_quotes(self) -> None:
        client = FakeOllamaClient(
            [
                {
                    "event_candidates": [
                        {
                            "candidate_id": "c1",
                            "event_type_hint": "BlockadeEvent",
                            "evidence": (
                                "The US military said it would stop all maritime traffic "
                                "entering and exiting Iranian ports from Monday morning."
                            ),
                            "context": "",
                            "rationale": "blockade",
                        },
                        {
                            "candidate_id": "c2",
                            "event_type_hint": "BlockadeEvent",
                            "evidence": "The United States blockaded Iranian ports.",
                            "context": "",
                            "rationale": "paraphrase",
                        },
                    ]
                }
            ]
        )

        candidates = detect_event_candidates(
            client=client,
            article=ARTICLE,
            model="test-model",
            options={"temperature": 0, "num_ctx": 1024},
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_id"], "c1")

    def test_build_deterministic_attack_relations(self) -> None:
        evidence = "Israel hit Iran's South Pars"
        participants = [
            {"name": "Israel", "type": "NationState", "role": "initiator"},
            {"name": "South Pars", "type": "StrategicLocation", "role": "target"},
            {"name": "Iran", "type": "NationState", "role": "participant"},
        ]

        relations = build_deterministic_relations("AttackEvent", participants, evidence)

        self.assertEqual(
            relations,
            [
                {
                    "source": "Israel",
                    "target": "South Pars",
                    "type": "ATTACKED",
                    "evidence": evidence,
                }
            ],
        )

    def test_full_staged_extraction_builds_compatible_record(self) -> None:
        evidence = ARTICLE["text"]
        client = FakeOllamaClient(
            [
                {
                    "event_candidates": [
                        {
                            "candidate_id": "c1",
                            "event_type_hint": "BlockadeEvent",
                            "evidence": evidence,
                            "context": evidence,
                            "rationale": "blockade statement",
                        }
                    ]
                },
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
                    "confidence": 0.82,
                    "drop_reason": "",
                },
                {
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
                    ]
                },
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
                    "confidence": 0.85,
                    "rejection_reason": "",
                },
            ]
        )

        record, diagnostics = extract_article_staged(
            client=client,
            article=ARTICLE,
            model="test-model",
            temperature=0,
            num_ctx=1024,
        )

        self.assertEqual(record["prompt_version"], PROMPT_VERSION)
        self.assertEqual(record["extraction_method"], "multi_stage")
        self.assertEqual(len(record["events"]), 1)
        self.assertEqual(record["events"][0]["event_date"], "2026-04-10")
        self.assertEqual(record["relations"][0]["type"], "BLOCKADED")
        self.assertEqual(diagnostics["candidate_count"], 1)
        self.assertEqual(diagnostics["event_count"], 1)

    def test_verifier_can_drop_candidate(self) -> None:
        evidence = ARTICLE["text"]
        client = FakeOllamaClient(
            [
                {
                    "event_candidates": [
                        {
                            "candidate_id": "c1",
                            "event_type_hint": "BlockadeEvent",
                            "evidence": evidence,
                            "context": evidence,
                            "rationale": "candidate",
                        }
                    ]
                },
                {
                    "keep": True,
                    "event_type": "BlockadeEvent",
                    "event_date": "",
                    "date_precision": "article_date",
                    "location": "Iranian ports",
                    "summary": "Draft event.",
                    "confidence": 0.5,
                    "drop_reason": "",
                },
                {
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
                    ]
                },
                {
                    "keep": False,
                    "event_type": "BlockadeEvent",
                    "event_date": "",
                    "date_precision": "article_date",
                    "location": "",
                    "summary": "",
                    "participants": [],
                    "confidence": 0,
                    "rejection_reason": "not supported",
                },
            ]
        )

        record, diagnostics = extract_article_staged(
            client=client,
            article=ARTICLE,
            model="test-model",
            temperature=0,
            num_ctx=1024,
        )

        self.assertEqual(record["events"], [])
        self.assertEqual(diagnostics["dropped_count"], 1)
        self.assertEqual(diagnostics["dropped"][0]["stage"], "verification")


if __name__ == "__main__":
    unittest.main()
