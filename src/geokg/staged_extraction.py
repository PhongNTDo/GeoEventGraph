"""Multi-stage event extraction using smaller LLM tasks."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geokg.extract_relations import (
    _existing_ids,
    _filter_articles_by_ids,
    _load_article_ids,
    _load_jsonl,
)
from geokg.extraction import normalize_model_json, validate_extraction_payload
from geokg.ollama_client import OllamaClient, OllamaError
from geokg.ontology import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_EVENT_DATE_PRECISIONS,
    ALLOWED_EVENT_PARTICIPANT_ROLES,
    ALLOWED_EVENT_TYPES,
    EVENT_TYPE_TO_RELATION_TYPE,
)


DEFAULT_BASE_URL = os.environ.get("GEOKG_OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("GEOKG_OLLAMA_MODEL", "gpt-oss:120b")
PROMPT_VERSION = "event-v2-staged"
UNKNOWN_EVENT_TYPE = "Unknown"


SYSTEM_PROMPT = """You extract geopolitical event information from news articles.

Return JSON only. Do not return Markdown. Do not add commentary.
All extracted evidence must be an exact contiguous quote from the article.
Do not infer hidden actors, motives, or missing links.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/normalized/articles.jsonl"),
        help="Normalized article JSONL input.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/extractions_staged"),
        help="Output directory for staged extraction artifacts.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Ollama base URL, for example http://127.0.0.1:11434",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--article-id", action="append", default=[])
    parser.add_argument(
        "--article-ids-file",
        type=Path,
        default=None,
        help="File containing article IDs. Supports plain text, JSON arrays, or JSONL.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Accepted for wrapper compatibility; staged extraction does not retry stages yet.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument(
        "--max-candidates-per-article",
        type=int,
        default=24,
        help="Limit evidence candidates before per-event stages.",
    )
    parser.add_argument(
        "--skip-verifier",
        action="store_true",
        help="Skip the final per-event verifier stage.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    articles = list(_load_jsonl(args.input))
    selected_article_ids = set(args.article_id)
    if args.article_ids_file is not None:
        selected_article_ids.update(_load_article_ids(args.article_ids_file))
    if selected_article_ids:
        articles = _filter_articles_by_ids(articles, selected_article_ids)
    if args.limit is not None:
        articles = articles[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "article_extractions.jsonl"
    failures_path = args.output_dir / "failures.jsonl"
    diagnostics_path = args.output_dir / "stage_diagnostics.jsonl"

    seen_article_ids = _existing_ids(output_path) if args.resume else set()
    client = OllamaClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds)

    processed = 0
    succeeded = 0
    failed = 0
    with output_path.open("a", encoding="utf-8") as output_handle, failures_path.open(
        "a", encoding="utf-8"
    ) as failure_handle, diagnostics_path.open("a", encoding="utf-8") as diagnostics_handle:
        for article in articles:
            article_id = article["article_id"]
            if article_id in seen_article_ids:
                continue

            processed += 1
            try:
                extraction, diagnostics = extract_article_staged(
                    client=client,
                    article=article,
                    model=args.model,
                    temperature=args.temperature,
                    num_ctx=args.num_ctx,
                    max_candidates=args.max_candidates_per_article,
                    verify=not args.skip_verifier,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failure_handle.write(
                    json.dumps(
                        {
                            "article_id": article_id,
                            "title": article.get("title"),
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                continue

            output_handle.write(json.dumps(extraction, ensure_ascii=False) + "\n")
            diagnostics_handle.write(json.dumps(diagnostics, ensure_ascii=False) + "\n")
            succeeded += 1

    print(
        json.dumps(
            {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "selected_article_count": len(articles),
                "output": str(output_path),
                "failures": str(failures_path),
                "diagnostics": str(diagnostics_path),
            }
        )
    )
    return 0


def extract_article_staged(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    model: str,
    temperature: float,
    num_ctx: int,
    max_candidates: int = 24,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    options = {"temperature": temperature, "num_ctx": num_ctx}
    candidates = detect_event_candidates(
        client=client,
        article=article,
        model=model,
        options=options,
    )[:max_candidates]

    staged_events: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(candidates):
        classification = classify_event_candidate(
            client=client,
            article=article,
            candidate=candidate,
            model=model,
            options=options,
        )
        if not classification.get("keep", True):
            dropped.append(
                {
                    "stage": "classification",
                    "candidate_index": candidate_index,
                    "reason": classification.get("drop_reason", ""),
                }
            )
            continue

        participants = extract_event_participants(
            client=client,
            article=article,
            candidate=candidate,
            classification=classification,
            model=model,
            options=options,
        )
        draft = build_event_from_stages(candidate, classification, participants)
        event = finalize_staged_event(draft)
        if event is None:
            dropped.append(
                {
                    "stage": "deterministic_relations",
                    "candidate_index": candidate_index,
                    "reason": "No deterministic relation could be built.",
                }
            )
            continue

        if verify:
            verified = verify_event_candidate(
                client=client,
                article=article,
                candidate=candidate,
                event=event,
                model=model,
                options=options,
            )
            if not verified.get("keep", True):
                dropped.append(
                    {
                        "stage": "verification",
                        "candidate_index": candidate_index,
                        "reason": verified.get("rejection_reason", ""),
                    }
                )
                continue
            draft = build_event_from_stages(candidate, verified, verified)
            event = finalize_staged_event(draft)
            if event is None:
                dropped.append(
                    {
                        "stage": "verification",
                        "candidate_index": candidate_index,
                        "reason": "Verifier correction left no valid relation.",
                    }
                )
                continue
        staged_events.append(event)

    payload = build_payload(staged_events)
    validation = validate_extraction_payload(payload, article, allow_partial=True)
    if validation.errors:
        raise OllamaError("; ".join(validation.errors))
    normalized = validation.normalized or {"entities": [], "relations": [], "events": []}

    extraction = attach_staged_metadata(
        article=article,
        extraction=normalized,
        model=model,
        validation_warnings=validation.dropped_errors,
        verified=verify,
    )
    diagnostics = {
        "article_id": article["article_id"],
        "title": article.get("title"),
        "prompt_version": PROMPT_VERSION,
        "candidate_count": len(candidates),
        "event_count": len(normalized.get("events", [])),
        "dropped_count": len(dropped),
        "dropped": dropped,
        "validation_warning_count": len(validation.dropped_errors),
        "verified": verify,
    }
    return extraction, diagnostics


def detect_event_candidates(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    model: str,
    options: dict[str, Any],
) -> list[dict[str, str]]:
    payload = _chat_json(
        client=client,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_candidate_prompt(article)},
        ],
        schema=candidate_schema(),
        options=options,
    )
    rows = payload.get("event_candidates", [])
    if not isinstance(rows, list):
        return []

    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, str]] = []
    article_text = article.get("text", "")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        evidence = _normalize_space(row.get("evidence"))
        event_type_hint = row.get("event_type_hint")
        if event_type_hint not in (*ALLOWED_EVENT_TYPES, UNKNOWN_EVENT_TYPE):
            event_type_hint = UNKNOWN_EVENT_TYPE
        if not evidence or not _quote_exists(evidence, article_text):
            continue
        key = (evidence.casefold(), str(event_type_hint))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "candidate_id": _normalize_space(row.get("candidate_id")) or f"c{index + 1}",
                "event_type_hint": str(event_type_hint),
                "evidence": evidence,
                "context": _normalize_space(row.get("context"))
                or nearby_context(article_text, evidence),
                "rationale": _normalize_space(row.get("rationale")),
            }
        )
    return candidates


def classify_event_candidate(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    candidate: dict[str, str],
    model: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    return _chat_json(
        client=client,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_classification_prompt(article, candidate)},
        ],
        schema=classification_schema(),
        options=options,
    )


def extract_event_participants(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    candidate: dict[str, str],
    classification: dict[str, Any],
    model: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    return _chat_json(
        client=client,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_participant_prompt(article, candidate, classification),
            },
        ],
        schema=participants_schema(),
        options=options,
    )


def verify_event_candidate(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    candidate: dict[str, str],
    event: dict[str, Any],
    model: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    return _chat_json(
        client=client,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_verifier_prompt(article, candidate, event)},
        ],
        schema=verifier_schema(),
        options=options,
    )


def build_event_from_stages(
    candidate: dict[str, str],
    classification: dict[str, Any],
    participants_payload: dict[str, Any],
) -> dict[str, Any]:
    participants = participants_payload.get("participants", [])
    if not isinstance(participants, list):
        participants = []
    return {
        "event_type": classification.get("event_type"),
        "event_date": _normalize_space(classification.get("event_date")),
        "date_precision": classification.get("date_precision"),
        "location": _normalize_space(classification.get("location")),
        "participants": participants,
        "summary": _normalize_space(classification.get("summary")),
        "evidence": candidate["evidence"],
        "confidence": classification.get("confidence", 0.0),
    }


def finalize_staged_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("event_type")
    evidence = _normalize_space(event.get("evidence"))
    participants = normalize_participants(event.get("participants"))
    if event_type not in ALLOWED_EVENT_TYPES or not evidence or not participants:
        return None

    location = _normalize_space(event.get("location"))
    if location:
        participants = ensure_location_participant(participants, location)

    relations = build_deterministic_relations(event_type, participants, evidence)
    if not relations:
        return None

    return {
        "event_type": event_type,
        "event_date": _normalize_space(event.get("event_date")),
        "date_precision": event.get("date_precision"),
        "location": location,
        "participants": participants,
        "relations": relations,
        "summary": _normalize_space(event.get("summary")),
        "evidence": evidence,
        "confidence": event.get("confidence", 0.0),
    }


def build_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    entities: list[dict[str, str]] = []
    seen_entities: set[str] = set()
    relations: list[dict[str, str]] = []
    seen_relations: set[tuple[str, str, str, str]] = set()
    for event in events:
        for participant in event.get("participants", []):
            key = participant["name"].casefold()
            if key not in seen_entities:
                seen_entities.add(key)
                entities.append({"name": participant["name"], "type": participant["type"]})
        location = _normalize_space(event.get("location"))
        if location and location.casefold() not in seen_entities:
            seen_entities.add(location.casefold())
            entities.append({"name": location, "type": "StrategicLocation"})
        for relation in event.get("relations", []):
            key = (
                relation["source"].casefold(),
                relation["target"].casefold(),
                relation["type"],
                relation["evidence"],
            )
            if key not in seen_relations:
                seen_relations.add(key)
                relations.append(relation)
    return {"entities": entities, "relations": relations, "events": events}


def build_deterministic_relations(
    event_type: str,
    participants: list[dict[str, str]],
    evidence: str,
) -> list[dict[str, str]]:
    relation_type = EVENT_TYPE_TO_RELATION_TYPE.get(event_type)
    if relation_type is None:
        return []

    by_role: dict[str, list[dict[str, str]]] = {}
    for participant in participants:
        by_role.setdefault(participant["role"], []).append(participant)

    pairs: list[tuple[dict[str, str], dict[str, str]]] = []
    if event_type == "AttackEvent":
        pairs = _role_pairs(by_role, ["initiator"], ["target", "affected_location"])
    elif event_type == "ThreatEvent":
        pairs = _role_pairs(by_role, ["initiator"], ["target", "affected_location"])
    elif event_type == "BlockadeEvent":
        pairs = _role_pairs(by_role, ["initiator"], ["affected_location", "target"])
    elif event_type == "SupportEvent":
        pairs = _role_pairs(by_role, ["supporter"], ["target", "participant"])
    elif event_type == "SanctionEvent":
        pairs = _role_pairs(by_role, ["sanctioning_actor"], ["target", "participant"])
    elif event_type == "NegotiationEvent":
        direct = by_role.get("participant", [])
        for index, source in enumerate(direct):
            for target in direct[index + 1 :]:
                pairs.append((source, target))
        if not pairs:
            pairs = _role_pairs(by_role, ["initiator"], ["target", "participant"])

    seen: set[tuple[str, str, str]] = set()
    relations: list[dict[str, str]] = []
    for source, target in pairs:
        if source["name"].casefold() == target["name"].casefold():
            continue
        key = (source["name"].casefold(), target["name"].casefold(), relation_type)
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            {
                "source": source["name"],
                "target": target["name"],
                "type": relation_type,
                "evidence": evidence,
            }
        )
    return relations


def _role_pairs(
    by_role: dict[str, list[dict[str, str]]],
    source_roles: list[str],
    target_roles: list[str],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    sources = [item for role in source_roles for item in by_role.get(role, [])]
    targets = [item for role in target_roles for item in by_role.get(role, [])]
    return [(source, target) for source in sources for target in targets]


def normalize_participants(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    seen: set[tuple[str, str]] = set()
    participants: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _normalize_space(item.get("name"))
        entity_type = item.get("type")
        role = item.get("role")
        if (
            not name
            or entity_type not in ALLOWED_ENTITY_TYPES
            or role not in ALLOWED_EVENT_PARTICIPANT_ROLES
        ):
            continue
        key = (name.casefold(), role)
        if key in seen:
            continue
        seen.add(key)
        participants.append({"name": name, "type": entity_type, "role": role})
    return participants


def ensure_location_participant(
    participants: list[dict[str, str]],
    location: str,
) -> list[dict[str, str]]:
    for participant in participants:
        if participant["name"].casefold() == location.casefold():
            return participants
    return [
        *participants,
        {"name": location, "type": "StrategicLocation", "role": "affected_location"},
    ]


def attach_staged_metadata(
    *,
    article: dict[str, Any],
    extraction: dict[str, Any],
    model: str,
    validation_warnings: list[str],
    verified: bool,
) -> dict[str, Any]:
    record = {
        "article_id": article["article_id"],
        "title": article.get("title"),
        "source": article.get("source"),
        "published_at": article.get("published_at"),
        "url": article.get("url"),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "extraction_method": "multi_stage",
        "stages": [
            "evidence_detection",
            "event_classification",
            "participant_extraction",
            "deterministic_relation_building",
        ]
        + (["verification"] if verified else []),
        "extracted_at": datetime.now(tz=UTC).isoformat(),
        "entities": extraction["entities"],
        "relations": extraction["relations"],
        "events": extraction.get("events", []),
    }
    if validation_warnings:
        record["validation_status"] = "partial"
        record["validation_warnings"] = validation_warnings[:50]
    return record


def _chat_json(
    *,
    client: OllamaClient,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    response = client.chat(
        model=model,
        messages=messages,
        response_format=schema,
        options=options,
    )
    try:
        payload = normalize_model_json(response["message"]["content"])
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OllamaError("Model response must be a JSON object.")
    return payload


def build_candidate_prompt(article: dict[str, Any]) -> str:
    return (
        "Stage 1: evidence-first event detection.\n"
        "Find candidate geopolitical event mentions in the article.\n"
        "Return only candidates whose evidence is an exact contiguous quote from the article.\n"
        "Prefer the smallest quote that identifies the action or claim.\n"
        "Do not classify participants or relations in this stage.\n\n"
        f"Allowed event type hints: {', '.join(ALLOWED_EVENT_TYPES)}, {UNKNOWN_EVENT_TYPE}\n\n"
        f"Article metadata:\n"
        f"- article_id: {article['article_id']}\n"
        f"- title: {article.get('title', '')}\n"
        f"- published_at: {article.get('published_at', '')}\n"
        f"- url: {article.get('url', '')}\n\n"
        f"Article text:\n{article.get('text', '')}\n"
    )


def build_classification_prompt(article: dict[str, Any], candidate: dict[str, str]) -> str:
    return (
        "Stage 2: classify one evidence-backed event candidate.\n"
        "Use only the evidence quote, nearby context, and article metadata.\n"
        "Set keep=false if this is not one allowed geopolitical event.\n"
        "Keep attribution in the summary when the article reports a claim, warning, or allegation.\n"
        "Use article_date only when no event date is stated and the event is current/recent.\n\n"
        f"Allowed event types: {', '.join(ALLOWED_EVENT_TYPES)}\n"
        f"Allowed date precisions: {', '.join(ALLOWED_EVENT_DATE_PRECISIONS)}\n\n"
        f"Article published_at: {article.get('published_at', '')}\n"
        f"Candidate evidence: {candidate['evidence']}\n"
        f"Nearby context: {candidate.get('context', '')}\n"
        f"Event type hint: {candidate.get('event_type_hint', UNKNOWN_EVENT_TYPE)}\n"
    )


def build_participant_prompt(
    article: dict[str, Any],
    candidate: dict[str, str],
    classification: dict[str, Any],
) -> str:
    return (
        "Stage 3: extract participants for one classified event.\n"
        "Extract only entities directly needed for this event: initiator, target, "
        "affected_location, military_asset, mediator, supporter, sanctioning_actor, "
        "or participant.\n"
        "Use canonical English names where obvious.\n"
        "Do not add unrelated context entities.\n\n"
        f"Allowed entity types: {', '.join(ALLOWED_ENTITY_TYPES)}\n"
        f"Allowed participant roles: {', '.join(ALLOWED_EVENT_PARTICIPANT_ROLES)}\n\n"
        f"Article title: {article.get('title', '')}\n"
        f"Event type: {classification.get('event_type')}\n"
        f"Event summary: {classification.get('summary')}\n"
        f"Event location: {classification.get('location')}\n"
        f"Candidate evidence: {candidate['evidence']}\n"
        f"Nearby context: {candidate.get('context', '')}\n"
    )


def build_verifier_prompt(
    article: dict[str, Any],
    candidate: dict[str, str],
    event: dict[str, Any],
) -> str:
    return (
        "Stage 5: verify one drafted event.\n"
        "Decide whether the event is explicitly supported by the exact evidence quote "
        "and nearby context. Drop domestic-only, rescue-logistics, market-reaction, "
        "or lifestyle events that are not allowed geopolitical events.\n"
        "If kept, correct event type, date, location, summary, confidence, and participants.\n"
        "Do not change the evidence quote.\n\n"
        f"Allowed event types: {', '.join(ALLOWED_EVENT_TYPES)}\n"
        f"Allowed entity types: {', '.join(ALLOWED_ENTITY_TYPES)}\n"
        f"Allowed participant roles: {', '.join(ALLOWED_EVENT_PARTICIPANT_ROLES)}\n\n"
        f"Article title: {article.get('title', '')}\n"
        f"Candidate evidence: {candidate['evidence']}\n"
        f"Nearby context: {candidate.get('context', '')}\n"
        f"Draft event:\n{json.dumps(event, indent=2)}\n"
    )


def candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "event_type_hint": {
                            "type": "string",
                            "enum": [*ALLOWED_EVENT_TYPES, UNKNOWN_EVENT_TYPE],
                        },
                        "evidence": {"type": "string"},
                        "context": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "candidate_id",
                        "event_type_hint",
                        "evidence",
                        "context",
                        "rationale",
                    ],
                },
            }
        },
        "required": ["event_candidates"],
    }


def classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keep": {"type": "boolean"},
            "event_type": {"type": "string", "enum": list(ALLOWED_EVENT_TYPES)},
            "event_date": {"type": "string"},
            "date_precision": {
                "type": "string",
                "enum": list(ALLOWED_EVENT_DATE_PRECISIONS),
            },
            "location": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "drop_reason": {"type": "string"},
        },
        "required": [
            "keep",
            "event_type",
            "event_date",
            "date_precision",
            "location",
            "summary",
            "confidence",
            "drop_reason",
        ],
    }


def participants_schema() -> dict[str, Any]:
    participant_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": list(ALLOWED_ENTITY_TYPES)},
            "role": {"type": "string", "enum": list(ALLOWED_EVENT_PARTICIPANT_ROLES)},
        },
        "required": ["name", "type", "role"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "participants": {"type": "array", "items": participant_item},
        },
        "required": ["participants"],
    }


def verifier_schema() -> dict[str, Any]:
    participant_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": list(ALLOWED_ENTITY_TYPES)},
            "role": {"type": "string", "enum": list(ALLOWED_EVENT_PARTICIPANT_ROLES)},
        },
        "required": ["name", "type", "role"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keep": {"type": "boolean"},
            "event_type": {"type": "string", "enum": list(ALLOWED_EVENT_TYPES)},
            "event_date": {"type": "string"},
            "date_precision": {
                "type": "string",
                "enum": list(ALLOWED_EVENT_DATE_PRECISIONS),
            },
            "location": {"type": "string"},
            "summary": {"type": "string"},
            "participants": {"type": "array", "items": participant_item},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rejection_reason": {"type": "string"},
        },
        "required": [
            "keep",
            "event_type",
            "event_date",
            "date_precision",
            "location",
            "summary",
            "participants",
            "confidence",
            "rejection_reason",
        ],
    }


def nearby_context(article_text: str, evidence: str, window: int = 260) -> str:
    index = _normalize_space(article_text).casefold().find(_normalize_space(evidence).casefold())
    if index < 0:
        return ""
    normalized_text = _normalize_space(article_text)
    start = max(0, index - window)
    end = min(len(normalized_text), index + len(evidence) + window)
    return normalized_text[start:end].strip()


def _quote_exists(quote: str, article_text: str) -> bool:
    if not quote:
        return False
    return _normalize_space(quote).casefold() in _normalize_space(article_text).casefold()


def _normalize_space(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


if __name__ == "__main__":
    raise SystemExit(main())
