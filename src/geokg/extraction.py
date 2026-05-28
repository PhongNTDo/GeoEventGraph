"""Prompting and validation for event-centric extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from geokg.ontology import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_EVENT_DATE_PRECISIONS,
    ALLOWED_EVENT_PARTICIPANT_ROLES,
    ALLOWED_EVENT_TYPES,
    ALLOWED_RELATION_TYPES,
    EVENT_TYPE_TO_RELATION_TYPE,
)


PROMPT_VERSION = "event-v1"


SYSTEM_PROMPT = """You extract geopolitical entities, events, and compatibility relations from news articles.

Return JSON only. Do not return Markdown. Do not add commentary.

You must obey this ontology exactly.
- Allowed entity types: NationState, NonStateActor, PoliticalLeader, StrategicLocation, MilitaryAsset
- Allowed event types: AttackEvent, ThreatEvent, NegotiationEvent, SupportEvent, SanctionEvent, BlockadeEvent
- Allowed relation types: ATTACKED, THREATENED, NEGOTIATED_WITH, SUPPORTED, SANCTIONED, BLOCKADED
- Allowed participant roles: initiator, target, mediator, supporter, sanctioning_actor, affected_location, military_asset, participant

Rules:
- Extract only facts explicitly supported by the article text.
- Do not infer hidden actors, motives, or missing links.
- Do not invent entities, event types, relation types, or participant roles outside the ontology.
- Extract events directly. Use relations only as compatibility edges inside each event and in the top-level relations list.
- Each event must describe one concrete geopolitical happening or claim in the article.
- If an event is implied but not explicit enough for a short supporting quote, omit it.
- Use canonical English names where obvious, for example United States instead of US.
- Include every entity referenced by an event participant, event location, or relation in the entities list.
- Event location must be an extracted entity name or an empty string if no concrete location is stated.
- Use the article published date with date_precision=article_date when the article does not state a more specific event date.
- The top-level relations array must contain the union of the relation edges found inside events.
- Evidence must be an exact short quote copied from the article text.
- If no valid entities, relations, or events exist, return empty arrays.
"""


def extraction_json_schema() -> dict[str, Any]:
    relation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string"},
            "target": {"type": "string"},
            "type": {"type": "string", "enum": list(ALLOWED_RELATION_TYPES)},
            "evidence": {"type": "string"},
        },
        "required": ["source", "target", "type", "evidence"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": list(ALLOWED_ENTITY_TYPES)},
                    },
                    "required": ["name", "type"],
                },
            },
            "relations": {
                "type": "array",
                "items": relation_schema,
            },
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "event_type": {"type": "string", "enum": list(ALLOWED_EVENT_TYPES)},
                        "event_date": {"type": "string"},
                        "date_precision": {
                            "type": "string",
                            "enum": list(ALLOWED_EVENT_DATE_PRECISIONS),
                        },
                        "location": {"type": "string"},
                        "participants": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string", "enum": list(ALLOWED_ENTITY_TYPES)},
                                    "role": {
                                        "type": "string",
                                        "enum": list(ALLOWED_EVENT_PARTICIPANT_ROLES),
                                    },
                                },
                                "required": ["name", "type", "role"],
                            },
                        },
                        "relations": {
                            "type": "array",
                            "items": relation_schema,
                        },
                        "summary": {"type": "string"},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": [
                        "event_type",
                        "event_date",
                        "date_precision",
                        "location",
                        "participants",
                        "relations",
                        "summary",
                        "evidence",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["entities", "relations", "events"],
    }


def build_extraction_prompt(article: dict[str, Any]) -> str:
    schema = {
        "entities": [{"name": "string", "type": "AllowedEntityType"}],
        "events": [
            {
                "event_type": "AllowedEventType",
                "event_date": "YYYY-MM-DD, YYYY-MM, YYYY, or article published date",
                "date_precision": "day | month | year | article_date | unknown",
                "location": "StrategicLocation entity name or empty string",
                "participants": [
                    {
                        "name": "entity name",
                        "type": "AllowedEntityType",
                        "role": "AllowedParticipantRole",
                    }
                ],
                "relations": [
                    {
                        "source": "entity name",
                        "target": "entity name",
                        "type": "AllowedRelationType",
                        "evidence": "exact supporting quote from the article",
                    }
                ],
                "summary": "one sentence event summary grounded in the article",
                "evidence": "exact supporting quote from the article",
                "confidence": 0.0,
            }
        ],
        "relations": [
            {
                "source": "entity name",
                "target": "entity name",
                "type": "AllowedRelationType",
                "evidence": "exact supporting quote from the article",
            }
        ],
    }
    return (
        "Extract entities, direct event records, and compatibility relations from this article.\n\n"
        "Output schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        f"Allowed entity types: {', '.join(ALLOWED_ENTITY_TYPES)}\n"
        f"Allowed event types: {', '.join(ALLOWED_EVENT_TYPES)}\n"
        f"Allowed relation types: {', '.join(ALLOWED_RELATION_TYPES)}\n\n"
        f"Allowed participant roles: {', '.join(ALLOWED_EVENT_PARTICIPANT_ROLES)}\n\n"
        "Event-to-relation compatibility mapping:\n"
        f"{json.dumps(EVENT_TYPE_TO_RELATION_TYPE, indent=2)}\n\n"
        "Important output rules:\n"
        "- Extract events directly. Do not only extract flat relations.\n"
        "- Keep relations inside each event, and repeat those relation edges in the top-level relations array.\n"
        "- Every participant, location, relation source, and relation target must appear in entities.\n"
        "- Every evidence field must be an exact quote from the article text.\n"
        "- Use an empty string for event location only when no concrete location is stated.\n"
        "- Use date_precision=article_date and the article published date when no event date is stated.\n\n"
        "Article metadata:\n"
        f"- article_id: {article['article_id']}\n"
        f"- source: {article.get('source', '')}\n"
        f"- title: {article.get('title', '')}\n"
        f"- published_at: {article.get('published_at', '')}\n"
        f"- url: {article.get('url', '')}\n\n"
        "Article text:\n"
        f"{article.get('text', '')}\n"
    )


def normalize_model_json(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = _strip_code_fences(stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        candidate = _extract_json_object(stripped)
        return json.loads(candidate)


def build_repair_prompt(validation_errors: list[str]) -> str:
    bullet_errors = "\n".join(f"- {item}" for item in validation_errors)
    return (
        "Your previous JSON response was invalid. Return corrected JSON only.\n"
        "Fix these issues exactly:\n"
        f"{bullet_errors}\n"
    )


@dataclass(slots=True)
class ValidationResult:
    normalized: dict[str, Any] | None
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors and self.normalized is not None


def validate_extraction_payload(
    payload: dict[str, Any],
    article: dict[str, Any],
) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(None, ["Top-level response must be a JSON object."])

    entities = payload.get("entities")
    relations = payload.get("relations")
    events = payload.get("events", [])
    if not isinstance(entities, list):
        errors.append("'entities' must be an array.")
    if not isinstance(relations, list):
        errors.append("'relations' must be an array.")
    if not isinstance(events, list):
        errors.append("'events' must be an array.")
    if errors:
        return ValidationResult(None, errors)

    normalized_entities: list[dict[str, str]] = []
    entity_index: dict[str, str] = {}

    for idx, entity in enumerate(entities):
        path = f"entities[{idx}]"
        if not isinstance(entity, dict):
            errors.append(f"{path} must be an object.")
            continue

        extra_keys = sorted(set(entity.keys()) - {"name", "type"})
        if extra_keys:
            errors.append(f"{path} has unsupported keys: {', '.join(extra_keys)}.")

        name = _normalize_space(entity.get("name"))
        entity_type = entity.get("type")
        if not name:
            errors.append(f"{path}.name must be a non-empty string.")
            continue
        if entity_type not in ALLOWED_ENTITY_TYPES:
            errors.append(
                f"{path}.type must be one of {', '.join(ALLOWED_ENTITY_TYPES)}."
            )
            continue

        dedupe_key = name.casefold()
        if dedupe_key not in entity_index:
            entity_index[dedupe_key] = entity_type
            normalized_entities.append({"name": name, "type": entity_type})

    article_text = article.get("text", "")
    normalized_article_text = _normalize_space(article_text)
    normalized_relations: list[dict[str, str]] = []
    seen_relations: set[tuple[str, str, str, str]] = set()

    for idx, relation in enumerate(relations):
        normalized = _validate_relation(
            relation,
            path=f"relations[{idx}]",
            entity_index=entity_index,
            normalized_article_text=normalized_article_text,
            errors=errors,
        )
        if normalized is None:
            continue
        _append_unique_relation(normalized_relations, seen_relations, normalized)

    normalized_events: list[dict[str, Any]] = []
    seen_events: set[tuple[Any, ...]] = set()
    for idx, event in enumerate(events):
        normalized = _validate_event(
            event,
            event_index=idx,
            article=article,
            entity_index=entity_index,
            normalized_article_text=normalized_article_text,
            errors=errors,
        )
        if normalized is None:
            continue
        for relation in normalized["relations"]:
            _append_unique_relation(normalized_relations, seen_relations, relation)

        event_key = _event_key(normalized)
        if event_key in seen_events:
            continue
        seen_events.add(event_key)
        normalized_events.append(normalized)

    if errors:
        return ValidationResult(None, errors)

    normalized = {
        "entities": normalized_entities,
        "relations": normalized_relations,
        "events": normalized_events,
    }
    return ValidationResult(normalized, [])


def attach_extraction_metadata(
    article: dict[str, Any],
    extraction: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "article_id": article["article_id"],
        "title": article.get("title"),
        "source": article.get("source"),
        "published_at": article.get("published_at"),
        "url": article.get("url"),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "extracted_at": datetime.now(tz=UTC).isoformat(),
        "entities": extraction["entities"],
        "relations": extraction["relations"],
        "events": extraction.get("events", []),
    }


def _validate_relation(
    relation: Any,
    *,
    path: str,
    entity_index: dict[str, str],
    normalized_article_text: str,
    errors: list[str],
) -> dict[str, str] | None:
    if not isinstance(relation, dict):
        errors.append(f"{path} must be an object.")
        return None

    extra_keys = sorted(set(relation.keys()) - {"source", "target", "type", "evidence"})
    if extra_keys:
        errors.append(f"{path} has unsupported keys: {', '.join(extra_keys)}.")

    source = _normalize_space(relation.get("source"))
    target = _normalize_space(relation.get("target"))
    relation_type = relation.get("type")
    evidence = _normalize_space(relation.get("evidence"))

    if not source:
        errors.append(f"{path}.source must be a non-empty string.")
    if not target:
        errors.append(f"{path}.target must be a non-empty string.")
    if relation_type not in ALLOWED_RELATION_TYPES:
        errors.append(f"{path}.type must be one of {', '.join(ALLOWED_RELATION_TYPES)}.")
    if not evidence:
        errors.append(f"{path}.evidence must be a non-empty string.")

    if not source or not target or not evidence or relation_type not in ALLOWED_RELATION_TYPES:
        return None
    if source.casefold() not in entity_index:
        errors.append(f"{path}.source references missing entity '{source}'.")
        return None
    if target.casefold() not in entity_index:
        errors.append(f"{path}.target references missing entity '{target}'.")
        return None
    if not _evidence_exists(evidence, normalized_article_text):
        errors.append(f"{path}.evidence must be an exact quote from the article text.")
        return None

    return {
        "source": source,
        "target": target,
        "type": relation_type,
        "evidence": evidence,
    }


def _validate_event(
    event: Any,
    *,
    event_index: int,
    article: dict[str, Any],
    entity_index: dict[str, str],
    normalized_article_text: str,
    errors: list[str],
) -> dict[str, Any] | None:
    path = f"events[{event_index}]"
    if not isinstance(event, dict):
        errors.append(f"{path} must be an object.")
        return None

    allowed_keys = {
        "event_type",
        "event_date",
        "date_precision",
        "location",
        "participants",
        "relations",
        "summary",
        "evidence",
        "confidence",
    }
    extra_keys = sorted(set(event.keys()) - allowed_keys)
    if extra_keys:
        errors.append(f"{path} has unsupported keys: {', '.join(extra_keys)}.")

    event_type = event.get("event_type")
    if event_type not in ALLOWED_EVENT_TYPES:
        errors.append(f"{path}.event_type must be one of {', '.join(ALLOWED_EVENT_TYPES)}.")

    date_precision = event.get("date_precision")
    if date_precision not in ALLOWED_EVENT_DATE_PRECISIONS:
        errors.append(
            f"{path}.date_precision must be one of {', '.join(ALLOWED_EVENT_DATE_PRECISIONS)}."
        )

    event_date = _normalize_event_date(event.get("event_date"), article, date_precision)
    if event_date is None:
        errors.append(
            f"{path}.event_date must be a date-like string, or use date_precision=unknown."
        )

    location = _normalize_space(event.get("location"))
    if location and location.casefold() not in entity_index:
        errors.append(f"{path}.location references missing entity '{location}'.")

    summary = _normalize_space(event.get("summary"))
    if not summary:
        errors.append(f"{path}.summary must be a non-empty string.")

    evidence = _normalize_space(event.get("evidence"))
    if not evidence:
        errors.append(f"{path}.evidence must be a non-empty string.")
    elif not _evidence_exists(evidence, normalized_article_text):
        errors.append(f"{path}.evidence must be an exact quote from the article text.")

    confidence = event.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        errors.append(f"{path}.confidence must be a number between 0 and 1.")
        normalized_confidence = None
    else:
        normalized_confidence = float(confidence)
        if not 0 <= normalized_confidence <= 1:
            errors.append(f"{path}.confidence must be a number between 0 and 1.")

    participants = event.get("participants")
    normalized_participants = _validate_event_participants(
        participants,
        path=f"{path}.participants",
        entity_index=entity_index,
        errors=errors,
    )

    event_relations = event.get("relations")
    if not isinstance(event_relations, list):
        errors.append(f"{path}.relations must be an array.")
        normalized_relations = []
    else:
        normalized_relations = []
        seen_relations: set[tuple[str, str, str, str]] = set()
        for relation_index, relation in enumerate(event_relations):
            normalized_relation = _validate_relation(
                relation,
                path=f"{path}.relations[{relation_index}]",
                entity_index=entity_index,
                normalized_article_text=normalized_article_text,
                errors=errors,
            )
            if normalized_relation is not None:
                _append_unique_relation(
                    normalized_relations,
                    seen_relations,
                    normalized_relation,
                )
    if not normalized_relations:
        errors.append(f"{path}.relations must contain at least one valid relation.")

    if errors:
        return None
    assert isinstance(event_type, str)
    assert isinstance(date_precision, str)
    assert event_date is not None
    assert normalized_confidence is not None
    return {
        "event_id": _build_event_id(article, event_index, event_type, evidence),
        "event_type": event_type,
        "event_date": event_date,
        "date_precision": date_precision,
        "location": location,
        "participants": normalized_participants,
        "relations": normalized_relations,
        "summary": summary,
        "evidence": evidence,
        "confidence": normalized_confidence,
    }


def _validate_event_participants(
    participants: Any,
    *,
    path: str,
    entity_index: dict[str, str],
    errors: list[str],
) -> list[dict[str, str]]:
    if not isinstance(participants, list):
        errors.append(f"{path} must be an array.")
        return []

    normalized_participants: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for idx, participant in enumerate(participants):
        item_path = f"{path}[{idx}]"
        if not isinstance(participant, dict):
            errors.append(f"{item_path} must be an object.")
            continue
        extra_keys = sorted(set(participant.keys()) - {"name", "type", "role"})
        if extra_keys:
            errors.append(f"{item_path} has unsupported keys: {', '.join(extra_keys)}.")

        name = _normalize_space(participant.get("name"))
        participant_type = participant.get("type")
        role = participant.get("role")
        if not name:
            errors.append(f"{item_path}.name must be a non-empty string.")
            continue
        if participant_type not in ALLOWED_ENTITY_TYPES:
            errors.append(f"{item_path}.type must be one of {', '.join(ALLOWED_ENTITY_TYPES)}.")
            continue
        indexed_type = entity_index.get(name.casefold())
        if indexed_type is None:
            errors.append(f"{item_path}.name references missing entity '{name}'.")
            continue
        if indexed_type != participant_type:
            errors.append(
                f"{item_path}.type for '{name}' must match entity type '{indexed_type}'."
            )
            continue
        if role not in ALLOWED_EVENT_PARTICIPANT_ROLES:
            errors.append(
                f"{item_path}.role must be one of {', '.join(ALLOWED_EVENT_PARTICIPANT_ROLES)}."
            )
            continue

        key = (name.casefold(), role)
        if key in seen:
            continue
        seen.add(key)
        normalized_participants.append({"name": name, "type": participant_type, "role": role})

    if not normalized_participants:
        errors.append(f"{path} must contain at least one valid participant.")
    return normalized_participants


def _append_unique_relation(
    relations: list[dict[str, str]],
    seen_relations: set[tuple[str, str, str, str]],
    relation: dict[str, str],
) -> None:
    key = (
        relation["source"].casefold(),
        relation["target"].casefold(),
        relation["type"],
        relation["evidence"],
    )
    if key in seen_relations:
        return
    seen_relations.add(key)
    relations.append(relation)


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    relation_keys = tuple(
        (
            relation["source"].casefold(),
            relation["target"].casefold(),
            relation["type"],
            relation["evidence"],
        )
        for relation in event.get("relations", [])
    )
    return (
        event.get("event_type"),
        event.get("event_date"),
        event.get("location", "").casefold(),
        event.get("evidence", ""),
        relation_keys,
    )


def _normalize_event_date(
    value: Any,
    article: dict[str, Any],
    date_precision: Any,
) -> str | None:
    normalized = _normalize_space(value)
    if normalized:
        if date_precision == "unknown" and normalized.casefold() in {"unknown", "n/a", "none"}:
            return ""
        if _event_date_matches_precision(normalized, date_precision):
            return normalized
        return None
    if date_precision == "unknown":
        return ""
    article_date = _normalize_article_date(article.get("published_at"))
    if date_precision == "article_date" and article_date is not None:
        return article_date
    return article_date


def _normalize_article_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", value) else None


def _event_date_matches_precision(value: str, date_precision: Any) -> bool:
    if date_precision in {"day", "article_date"}:
        return re.match(r"^\d{4}-\d{2}-\d{2}$", value) is not None
    if date_precision == "month":
        return re.match(r"^\d{4}-\d{2}$", value) is not None
    if date_precision == "year":
        return re.match(r"^\d{4}$", value) is not None
    if date_precision == "unknown":
        return value == ""
    return False


def _build_event_id(
    article: dict[str, Any],
    event_index: int,
    event_type: str,
    evidence: str,
) -> str:
    article_id = _slugify(_normalize_space(article.get("article_id")) or "article")
    evidence_seed = _slugify(evidence[:48]) or "event"
    return f"event:{article_id}:{event_index + 1:03d}:{_slugify(event_type)}:{evidence_seed}"


def _slugify(value: str) -> str:
    lowered = value.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered)
    return normalized.strip("-")


def _strip_code_fences(value: str) -> str:
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(value: str) -> str:
    match = re.search(r"\{.*\}", value, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found", value, 0)
    return match.group(0)


def _normalize_space(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _evidence_exists(evidence: str, normalized_article_text: str) -> bool:
    return _normalize_space(evidence) in normalized_article_text
