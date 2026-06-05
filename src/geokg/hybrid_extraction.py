"""Hybrid event extraction using event-v1 candidates plus event-level repair."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geokg.extract_relations import _existing_ids, _load_article_ids, _load_jsonl
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
PROMPT_VERSION = "event-v2-hybrid"


SYSTEM_PROMPT = """You verify and repair one geopolitical event candidate.

Return JSON only. Do not return Markdown. Do not add commentary.
Use the candidate as the starting point; do not rediscover all events in the article.
Keep the candidate evidence unchanged.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/extractions_event_v1/article_extractions.jsonl"),
        help="One-shot extraction JSONL used as event candidates.",
    )
    parser.add_argument(
        "--articles",
        type=Path,
        default=Path("data/normalized/articles.jsonl"),
        help="Normalized article JSONL used for verifier context and validation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/extractions_hybrid"),
        help="Output directory for hybrid extraction artifacts.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Ollama base URL, for example http://127.0.0.1:11434.",
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
        default=2,
        help="Retries after invalid verifier JSON.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument(
        "--skip-verifier",
        action="store_true",
        help="Skip LLM verification and only rebuild deterministic relations.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    candidate_records = list(_load_jsonl(args.input))
    articles_by_id = {row["article_id"]: row for row in _load_jsonl(args.articles)}

    selected_article_ids = set(args.article_id)
    if args.article_ids_file is not None:
        selected_article_ids.update(_load_article_ids(args.article_ids_file))
    if selected_article_ids:
        candidate_records = [
            row
            for row in candidate_records
            if isinstance(row.get("article_id"), str) and row["article_id"] in selected_article_ids
        ]
    if args.limit is not None:
        candidate_records = candidate_records[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "article_extractions.jsonl"
    failures_path = args.output_dir / "failures.jsonl"
    diagnostics_path = args.output_dir / "hybrid_diagnostics.jsonl"

    seen_article_ids = _existing_ids(output_path) if args.resume else set()
    client = OllamaClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds)

    processed = 0
    succeeded = 0
    failed = 0

    with output_path.open("a", encoding="utf-8") as output_handle, failures_path.open(
        "a", encoding="utf-8"
    ) as failure_handle, diagnostics_path.open("a", encoding="utf-8") as diagnostics_handle:
        for candidate_record in candidate_records:
            article_id = candidate_record["article_id"]
            if article_id in seen_article_ids:
                continue

            processed += 1
            article = articles_by_id.get(article_id)
            if article is None:
                failed += 1
                failure_handle.write(
                    json.dumps(
                        {
                            "article_id": article_id,
                            "title": candidate_record.get("title"),
                            "error": f"Article metadata not found in {args.articles}.",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                continue

            try:
                extraction, diagnostics = extract_article_hybrid(
                    client=client,
                    article=article,
                    candidate_record=candidate_record,
                    model=args.model,
                    temperature=args.temperature,
                    num_ctx=args.num_ctx,
                    max_retries=args.max_retries,
                    verify=not args.skip_verifier,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failure_handle.write(
                    json.dumps(
                        {
                            "article_id": article_id,
                            "title": candidate_record.get("title") or article.get("title"),
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
                "selected_article_count": len(candidate_records),
                "output": str(output_path),
                "failures": str(failures_path),
                "diagnostics": str(diagnostics_path),
            }
        )
    )
    return 0


def extract_article_hybrid(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    candidate_record: dict[str, Any],
    model: str,
    temperature: float,
    num_ctx: int,
    max_retries: int = 2,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    options = {"temperature": temperature, "num_ctx": num_ctx}
    candidate_events = [
        event for event in candidate_record.get("events", []) if isinstance(event, dict)
    ]

    repaired_events: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    repair_notes: list[dict[str, Any]] = []
    for event_index, candidate_event in enumerate(candidate_events):
        if verify:
            verifier_payload = verify_or_repair_event(
                client=client,
                article=article,
                candidate_event=candidate_event,
                model=model,
                options=options,
                max_retries=max_retries,
            )
        else:
            verifier_payload = candidate_event_to_verifier_payload(candidate_event)

        if not verifier_payload.get("keep", True):
            dropped.append(
                {
                    "stage": "event_verifier",
                    "candidate_event_index": event_index,
                    "candidate_event_id": candidate_event.get("event_id", ""),
                    "reason": _normalize_space(verifier_payload.get("drop_reason")),
                }
            )
            continue

        event = finalize_hybrid_event(
            candidate_event=candidate_event,
            verifier_payload=verifier_payload,
            candidate_entities=candidate_record.get("entities", []),
        )
        if event is None:
            dropped.append(
                {
                    "stage": "deterministic_relation_repair",
                    "candidate_event_index": event_index,
                    "candidate_event_id": candidate_event.get("event_id", ""),
                    "reason": "No compatible deterministic relation could be built.",
                }
            )
            continue

        if event_changed(candidate_event, event):
            repair_notes.append(
                {
                    "candidate_event_index": event_index,
                    "candidate_event_id": candidate_event.get("event_id", ""),
                    "repair_notes": _normalize_space(verifier_payload.get("repair_notes")),
                }
            )
        repaired_events.append(event)

    payload = build_payload(candidate_record.get("entities", []), repaired_events)
    validation = validate_extraction_payload(payload, article, allow_partial=True)
    if validation.errors:
        raise OllamaError("; ".join(validation.errors))
    normalized = validation.normalized or {"entities": [], "relations": [], "events": []}

    extraction = attach_hybrid_metadata(
        article=article,
        candidate_record=candidate_record,
        extraction=normalized,
        model=model,
        validation_warnings=validation.dropped_errors,
        verified=verify,
    )
    diagnostics = {
        "article_id": article["article_id"],
        "title": article.get("title"),
        "prompt_version": PROMPT_VERSION,
        "candidate_prompt_version": candidate_record.get("prompt_version", ""),
        "candidate_event_count": len(candidate_events),
        "event_count": len(normalized.get("events", [])),
        "dropped_count": len(dropped),
        "dropped": dropped,
        "repaired_count": len(repair_notes),
        "repairs": repair_notes,
        "validation_warning_count": len(validation.dropped_errors),
        "verified": verify,
    }
    return extraction, diagnostics


def verify_or_repair_event(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    candidate_event: dict[str, Any],
    model: str,
    options: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_event_verifier_prompt(article, candidate_event),
        },
    ]
    last_error = "Unknown verifier failure."
    for _attempt in range(max_retries + 1):
        response = client.chat(
            model=model,
            messages=messages,
            response_format=event_verifier_schema(),
            options=options,
        )
        raw_content = response["message"]["content"]
        try:
            payload = normalize_model_json(raw_content)
        except json.JSONDecodeError as exc:
            last_error = f"Model returned invalid JSON: {exc}"
            messages.extend(
                [
                    {"role": "assistant", "content": raw_content},
                    {"role": "user", "content": build_verifier_repair_prompt(last_error)},
                ]
            )
            continue
        if isinstance(payload, dict):
            return payload
        last_error = "Verifier response must be a JSON object."
        messages.extend(
            [
                {"role": "assistant", "content": raw_content},
                {"role": "user", "content": build_verifier_repair_prompt(last_error)},
            ]
        )
    raise OllamaError(last_error)


def candidate_event_to_verifier_payload(candidate_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "keep": True,
        "event_type": candidate_event.get("event_type"),
        "event_date": candidate_event.get("event_date", ""),
        "date_precision": candidate_event.get("date_precision", "unknown"),
        "location": candidate_event.get("location", ""),
        "summary": candidate_event.get("summary", ""),
        "participants": candidate_event.get("participants", []),
        "confidence": candidate_event.get("confidence", 0.0),
        "repair_notes": "Verifier skipped; reused event-v1 candidate.",
        "drop_reason": "",
    }


def finalize_hybrid_event(
    *,
    candidate_event: dict[str, Any],
    verifier_payload: dict[str, Any],
    candidate_entities: Any,
) -> dict[str, Any] | None:
    event_type = verifier_payload.get("event_type")
    evidence = _normalize_space(candidate_event.get("evidence"))
    if event_type not in ALLOWED_EVENT_TYPES or not evidence:
        return None

    known_entity_types = known_entity_type_index(candidate_entities)
    participants = normalize_participants(verifier_payload.get("participants"))
    participants = repair_roles_for_event(event_type, participants)

    location = _normalize_space(verifier_payload.get("location"))
    if location:
        participants = ensure_location_participant(participants, location, known_entity_types)
    if not participants:
        return None

    relations = build_repaired_relations(event_type, participants, evidence)
    if not relations:
        return None

    confidence = verifier_payload.get("confidence", candidate_event.get("confidence", 0.0))
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = 0.0

    return {
        "event_type": event_type,
        "event_date": _normalize_space(verifier_payload.get("event_date")),
        "date_precision": verifier_payload.get("date_precision"),
        "location": location,
        "participants": participants,
        "relations": relations,
        "summary": _normalize_space(verifier_payload.get("summary")),
        "evidence": evidence,
        "confidence": max(0.0, min(1.0, float(confidence))),
    }


def build_payload(candidate_entities: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    entities: list[dict[str, str]] = []
    seen_entities: set[str] = set()

    def add_entity(name: str, entity_type: str) -> None:
        if entity_type not in ALLOWED_ENTITY_TYPES:
            return
        normalized_name = _normalize_space(name)
        if not normalized_name:
            return
        key = normalized_name.casefold()
        if key in seen_entities:
            return
        seen_entities.add(key)
        entities.append({"name": normalized_name, "type": entity_type})

    for event in events:
        for participant in event.get("participants", []):
            add_entity(participant["name"], participant["type"])
        location = _normalize_space(event.get("location"))
        if location and location.casefold() not in seen_entities:
            add_entity(location, "StrategicLocation")

    if isinstance(candidate_entities, list):
        for entity in candidate_entities:
            if not isinstance(entity, dict):
                continue
            add_entity(str(entity.get("name", "")), str(entity.get("type", "")))

    relations: list[dict[str, str]] = []
    seen_relations: set[tuple[str, str, str, str]] = set()
    for event in events:
        for relation in event.get("relations", []):
            key = (
                relation["source"].casefold(),
                relation["target"].casefold(),
                relation["type"],
                relation["evidence"],
            )
            if key in seen_relations:
                continue
            seen_relations.add(key)
            relations.append(relation)

    return {"entities": entities, "relations": relations, "events": events}


def build_repaired_relations(
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
        pairs = _first_non_empty_role_pairs(
            by_role,
            ["initiator"],
            [["target"], ["affected_location"], ["military_asset"]],
        )
    elif event_type == "ThreatEvent":
        pairs = _first_non_empty_role_pairs(
            by_role,
            ["initiator"],
            [["target"], ["affected_location"]],
        )
    elif event_type == "BlockadeEvent":
        pairs = _first_non_empty_role_pairs(
            by_role,
            ["initiator"],
            [["affected_location"], ["target"]],
        )
    elif event_type == "SupportEvent":
        pairs = _first_non_empty_role_pairs(
            by_role,
            ["supporter"],
            [["target"], ["participant"]],
        )
    elif event_type == "SanctionEvent":
        pairs = _first_non_empty_role_pairs(
            by_role,
            ["sanctioning_actor"],
            [["target"], ["participant"]],
        )
    elif event_type == "NegotiationEvent":
        direct = by_role.get("participant", [])
        for index, source in enumerate(direct):
            for target in direct[index + 1 :]:
                pairs.append((source, target))
        if not pairs:
            pairs = _first_non_empty_role_pairs(
                by_role,
                ["initiator"],
                [["target"], ["participant"]],
            )

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


def _first_non_empty_role_pairs(
    by_role: dict[str, list[dict[str, str]]],
    source_roles: list[str],
    target_role_groups: list[list[str]],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    sources = [item for role in source_roles for item in by_role.get(role, [])]
    if not sources:
        return []
    for target_roles in target_role_groups:
        targets = [item for role in target_roles for item in by_role.get(role, [])]
        if targets:
            return [(source, target) for source in sources for target in targets]
    return []


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


def repair_roles_for_event(
    event_type: str,
    participants: list[dict[str, str]],
) -> list[dict[str, str]]:
    repaired: list[dict[str, str]] = []
    for participant in participants:
        item = dict(participant)
        if event_type == "SupportEvent" and item["role"] == "initiator":
            item["role"] = "supporter"
        elif event_type == "SanctionEvent" and item["role"] == "initiator":
            item["role"] = "sanctioning_actor"
        elif event_type == "NegotiationEvent" and item["role"] in {"initiator", "target"}:
            item["role"] = "participant"
        repaired.append(item)

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in repaired:
        key = (item["name"].casefold(), item["role"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def ensure_location_participant(
    participants: list[dict[str, str]],
    location: str,
    known_entity_types: dict[str, str],
) -> list[dict[str, str]]:
    if any(participant["name"].casefold() == location.casefold() for participant in participants):
        return participants
    entity_type = known_entity_types.get(location.casefold(), "StrategicLocation")
    if entity_type not in ALLOWED_ENTITY_TYPES:
        entity_type = "StrategicLocation"
    return [
        *participants,
        {"name": location, "type": entity_type, "role": "affected_location"},
    ]


def known_entity_type_index(candidate_entities: Any) -> dict[str, str]:
    known: dict[str, str] = {}
    if not isinstance(candidate_entities, list):
        return known
    for entity in candidate_entities:
        if not isinstance(entity, dict):
            continue
        name = _normalize_space(entity.get("name"))
        entity_type = entity.get("type")
        if name and entity_type in ALLOWED_ENTITY_TYPES:
            known.setdefault(name.casefold(), entity_type)
    return known


def attach_hybrid_metadata(
    *,
    article: dict[str, Any],
    candidate_record: dict[str, Any],
    extraction: dict[str, Any],
    model: str,
    validation_warnings: list[str],
    verified: bool,
) -> dict[str, Any]:
    record = {
        "article_id": article["article_id"],
        "title": article.get("title") or candidate_record.get("title"),
        "source": article.get("source") or candidate_record.get("source"),
        "published_at": article.get("published_at") or candidate_record.get("published_at"),
        "url": article.get("url") or candidate_record.get("url"),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "candidate_model": candidate_record.get("model", ""),
        "candidate_prompt_version": candidate_record.get("prompt_version", ""),
        "extraction_method": "hybrid_event_v1_verifier",
        "stages": [
            "event_v1_candidate_generation",
            *([] if not verified else ["per_event_verifier_repair"]),
            "deterministic_relation_repair",
            "final_schema_validation",
        ],
        "extracted_at": datetime.now(tz=UTC).isoformat(),
        "entities": extraction["entities"],
        "relations": extraction["relations"],
        "events": extraction.get("events", []),
    }
    if validation_warnings:
        record["validation_status"] = "partial"
        record["validation_warnings"] = validation_warnings[:50]
    return record


def event_changed(candidate_event: dict[str, Any], event: dict[str, Any]) -> bool:
    compared_keys = (
        "event_type",
        "event_date",
        "date_precision",
        "location",
        "participants",
        "summary",
        "confidence",
    )
    for key in compared_keys:
        if candidate_event.get(key) != event.get(key):
            return True
    return candidate_event.get("relations", []) != event.get("relations", [])


def build_event_verifier_prompt(article: dict[str, Any], candidate_event: dict[str, Any]) -> str:
    evidence = _normalize_space(candidate_event.get("evidence"))
    context = nearby_context(article.get("text", ""), evidence)
    candidate_for_prompt = {
        key: candidate_event.get(key)
        for key in (
            "event_type",
            "event_date",
            "date_precision",
            "location",
            "participants",
            "relations",
            "summary",
            "evidence",
            "confidence",
        )
    }
    return (
        "Verify and repair this one event-v1 candidate.\n\n"
        "Decision rules:\n"
        "- Use the candidate as the starting point. Do not search for new events.\n"
        "- Set keep=false if the evidence/context does not support one allowed geopolitical event.\n"
        "- Keep evidence unchanged. It must remain the exact candidate evidence string.\n"
        "- If kept, repair only event_type, event_date, date_precision, location, "
        "summary, participants, and confidence.\n"
        "- Do not return relation edges. GeoKG will rebuild relations deterministically "
        "after participants are stable.\n"
        "- Preserve attribution in the summary for claims, warnings, or allegations.\n"
        "- Do not add actors or targets that are not stated in the evidence or nearby context.\n"
        "- For SupportEvent use role=supporter for the supporting actor.\n"
        "- For SanctionEvent use role=sanctioning_actor for the actor imposing sanctions.\n"
        "- For NegotiationEvent use role=participant for negotiating sides and mediator "
        "only for a stated mediator or host.\n\n"
        f"Allowed event types: {', '.join(ALLOWED_EVENT_TYPES)}\n"
        f"Allowed entity types: {', '.join(ALLOWED_ENTITY_TYPES)}\n"
        f"Allowed date precisions: {', '.join(ALLOWED_EVENT_DATE_PRECISIONS)}\n"
        f"Allowed participant roles: {', '.join(ALLOWED_EVENT_PARTICIPANT_ROLES)}\n\n"
        f"Article metadata:\n"
        f"- article_id: {article['article_id']}\n"
        f"- title: {article.get('title', '')}\n"
        f"- published_at: {article.get('published_at', '')}\n"
        f"- url: {article.get('url', '')}\n\n"
        f"Candidate evidence:\n{evidence}\n\n"
        f"Nearby context:\n{context}\n\n"
        f"Candidate event JSON:\n{json.dumps(candidate_for_prompt, indent=2)}\n"
    )


def build_verifier_repair_prompt(error: str) -> str:
    return (
        "Your previous verifier response was invalid. Return corrected JSON only.\n"
        "Keep the candidate evidence unchanged. Do not include relation edges.\n"
        f"Problem: {error}\n"
    )


def event_verifier_schema() -> dict[str, Any]:
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
            "repair_notes": {"type": "string"},
            "drop_reason": {"type": "string"},
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
            "repair_notes",
            "drop_reason",
        ],
    }


def nearby_context(article_text: str, evidence: str, window: int = 360) -> str:
    normalized_text = _normalize_space(article_text)
    normalized_evidence = _normalize_space(evidence)
    if not normalized_text or not normalized_evidence:
        return ""
    index = normalized_text.casefold().find(normalized_evidence.casefold())
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(normalized_text), index + len(normalized_evidence) + window)
    return normalized_text[start:end].strip()


def _normalize_space(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


if __name__ == "__main__":
    raise SystemExit(main())
