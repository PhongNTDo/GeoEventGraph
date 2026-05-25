"""Post-processing helpers for extracted entities, relations, and events."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geokg.ontology import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_EVENT_DATE_PRECISIONS,
    ALLOWED_EVENT_PARTICIPANT_ROLES,
    ALLOWED_EVENT_TYPES,
    ALLOWED_RELATION_TYPES,
)


BUILTIN_ALIASES: dict[str, tuple[str, str | None]] = {
    "us": ("United States", "NationState"),
    "u.s.": ("United States", "NationState"),
    "u.s": ("United States", "NationState"),
    "usa": ("United States", "NationState"),
    "uk": ("United Kingdom", "NationState"),
    "u.k.": ("United Kingdom", "NationState"),
}


@dataclass(slots=True)
class AliasEntry:
    canonical_name: str
    canonical_type: str | None = None


@dataclass(slots=True)
class ReviewFlag:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def load_aliases(path: Path) -> dict[str, AliasEntry]:
    aliases: dict[str, AliasEntry] = {
        _alias_key(alias): AliasEntry(canonical_name=name, canonical_type=entity_type)
        for alias, (name, entity_type) in BUILTIN_ALIASES.items()
    }
    if not path.exists():
        return aliases

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            alias = _alias_key(row.get("alias", ""))
            canonical_name = _normalize_name(row.get("canonical_name", ""))
            canonical_type = _normalize_name(row.get("canonical_type", "")) or None
            if not alias or not canonical_name:
                continue
            aliases[alias] = AliasEntry(
                canonical_name=canonical_name,
                canonical_type=canonical_type,
            )
    return aliases


def clean_extraction_record(
    record: dict[str, Any],
    aliases: dict[str, AliasEntry],
) -> dict[str, Any]:
    original_entities = record.get("entities", [])
    original_relations = record.get("relations", [])
    original_events = record.get("events", [])

    cleaned_entities: list[dict[str, Any]] = []
    canonical_lookup: dict[tuple[str, str], str] = {}
    name_index: dict[str, dict[str, Any]] = {}
    review_flags: list[ReviewFlag] = []

    for raw_entity in original_entities:
        if not isinstance(raw_entity, dict):
            continue
        entity_name = _normalize_name(raw_entity.get("name", ""))
        entity_type = raw_entity.get("type")
        if not entity_name or entity_type not in ALLOWED_ENTITY_TYPES:
            continue

        canonical_name, canonical_type = canonicalize_entity(entity_name, entity_type, aliases)
        canonical_lookup[(entity_name.casefold(), entity_type)] = canonical_name

        existing = name_index.get(canonical_name.casefold())
        if existing is None:
            entity = {"name": canonical_name, "type": canonical_type}
            if canonical_name != entity_name:
                entity["aliases"] = [entity_name]
            cleaned_entities.append(entity)
            name_index[canonical_name.casefold()] = entity
        else:
            if existing["type"] != canonical_type:
                review_flags.append(
                    ReviewFlag(
                        code="entity_type_conflict",
                        message=(
                            f"Entity '{canonical_name}' appeared with multiple types: "
                            f"{existing['type']} and {canonical_type}."
                        ),
                    )
                )
            _append_alias(existing, entity_name)

    cleaned_relations, relation_flags = _clean_relation_records(
        original_relations,
        name_index,
        aliases,
    )
    review_flags.extend(relation_flags)

    cleaned_events, event_flags = _clean_event_records(
        original_events,
        record,
        name_index,
        aliases,
    )
    review_flags.extend(event_flags)
    cleaned_relations = _merge_relation_records(
        cleaned_relations,
        [
            relation
            for event in cleaned_events
            for relation in event.get("relations", [])
            if isinstance(relation, dict)
        ],
    )

    for entity in cleaned_entities:
        if entity["type"] == "StrategicLocation":
            entity_flags = review_location_name(entity["name"])
            if entity_flags:
                entity["review_flags"] = [flag.to_dict() for flag in entity_flags]
                review_flags.extend(entity_flags)

    cleaned_record = dict(record)
    cleaned_record["entities"] = cleaned_entities
    cleaned_record["relations"] = cleaned_relations
    cleaned_record["events"] = cleaned_events
    cleaned_record["postprocess_review_flags"] = [flag.to_dict() for flag in _dedupe_flags(review_flags)]
    return cleaned_record


def _clean_relation_records(
    relations: Any,
    name_index: dict[str, dict[str, Any]],
    aliases: dict[str, AliasEntry],
) -> tuple[list[dict[str, Any]], list[ReviewFlag]]:
    if not isinstance(relations, list):
        return [], []

    cleaned_relations: list[dict[str, Any]] = []
    review_flags: list[ReviewFlag] = []
    seen_relations: set[tuple[str, str, str, str]] = set()
    for raw_relation in relations:
        if not isinstance(raw_relation, dict):
            continue
        source = _normalize_name(raw_relation.get("source", ""))
        target = _normalize_name(raw_relation.get("target", ""))
        relation_type = raw_relation.get("type")
        evidence = _normalize_name(raw_relation.get("evidence", ""))
        if not source or not target or not evidence:
            continue
        if relation_type not in ALLOWED_RELATION_TYPES:
            continue

        source_name = _resolve_relation_endpoint(source, name_index, aliases)
        target_name = _resolve_relation_endpoint(target, name_index, aliases)
        if source_name is None or target_name is None:
            review_flags.append(
                ReviewFlag(
                    code="relation_missing_entity",
                    message=(
                        f"Relation '{relation_type}' dropped because source '{source}' "
                        f"or target '{target}' was missing after canonicalization."
                    ),
                )
            )
            continue
        if source_name == target_name:
            review_flags.append(
                ReviewFlag(
                    code="self_loop_relation",
                    message=(
                        f"Relation '{relation_type}' dropped because source and target "
                        f"both resolve to '{source_name}'."
                    ),
                )
            )
            continue

        relation_key = (source_name.casefold(), target_name.casefold(), relation_type, evidence)
        if relation_key in seen_relations:
            continue
        seen_relations.add(relation_key)
        cleaned_relations.append(
            {
                "source": source_name,
                "target": target_name,
                "type": relation_type,
                "evidence": evidence,
            }
        )
    return cleaned_relations, review_flags


def _clean_event_records(
    events: Any,
    record: dict[str, Any],
    name_index: dict[str, dict[str, Any]],
    aliases: dict[str, AliasEntry],
) -> tuple[list[dict[str, Any]], list[ReviewFlag]]:
    if not isinstance(events, list):
        return [], []

    cleaned_events: list[dict[str, Any]] = []
    review_flags: list[ReviewFlag] = []
    seen_events: set[tuple[Any, ...]] = set()

    for index, raw_event in enumerate(events):
        if not isinstance(raw_event, dict):
            continue
        event_type = raw_event.get("event_type")
        if event_type not in ALLOWED_EVENT_TYPES:
            continue

        date_precision = raw_event.get("date_precision")
        if date_precision not in ALLOWED_EVENT_DATE_PRECISIONS:
            review_flags.append(
                ReviewFlag(
                    code="event_date_precision_invalid",
                    message=(
                        f"Event '{event_type}' used invalid date precision "
                        f"'{date_precision}'."
                    ),
                )
            )
            date_precision = "unknown"

        location = _normalize_name(raw_event.get("location", ""))
        if location:
            resolved_location = _resolve_relation_endpoint(location, name_index, aliases)
            if resolved_location is None:
                review_flags.append(
                    ReviewFlag(
                        code="event_location_missing_entity",
                        message=(
                            f"Event '{event_type}' location '{location}' was not found "
                            "after canonicalization."
                        ),
                    )
                )
            else:
                location = resolved_location

        participants, participant_flags = _clean_event_participants(
            raw_event.get("participants", []),
            name_index,
            aliases,
            event_type,
        )
        review_flags.extend(participant_flags)

        relations, relation_flags = _clean_relation_records(
            raw_event.get("relations", []),
            name_index,
            aliases,
        )
        review_flags.extend(relation_flags)
        if not participants or not relations:
            review_flags.append(
                ReviewFlag(
                    code="event_incomplete",
                    message=(
                        f"Event '{event_type}' dropped because participants or relations "
                        "were missing after canonicalization."
                    ),
                )
            )
            continue

        event_id = _normalize_name(raw_event.get("event_id", ""))
        if not event_id:
            event_id = _build_event_id(record, index, event_type)

        cleaned_event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_date": _normalize_name(raw_event.get("event_date", "")),
            "date_precision": date_precision,
            "location": location,
            "participants": participants,
            "relations": relations,
            "summary": _normalize_name(raw_event.get("summary", "")),
            "evidence": _normalize_name(raw_event.get("evidence", "")),
            "confidence": _coerce_confidence(raw_event.get("confidence")),
            "review_status": _normalize_name(raw_event.get("review_status", "")) or "unreviewed",
        }

        existing_flags = raw_event.get("review_flags", [])
        if isinstance(existing_flags, list):
            event_review_flags = [
                flag
                for flag in existing_flags
                if isinstance(flag, dict)
                and isinstance(flag.get("code"), str)
                and isinstance(flag.get("message"), str)
            ]
            if event_review_flags:
                cleaned_event["review_flags"] = event_review_flags

        event_key = _event_key(cleaned_event)
        if event_key in seen_events:
            continue
        seen_events.add(event_key)
        cleaned_events.append(cleaned_event)

    return cleaned_events, review_flags


def _clean_event_participants(
    participants: Any,
    name_index: dict[str, dict[str, Any]],
    aliases: dict[str, AliasEntry],
    event_type: str,
) -> tuple[list[dict[str, str]], list[ReviewFlag]]:
    if not isinstance(participants, list):
        return [], []

    cleaned: list[dict[str, str]] = []
    review_flags: list[ReviewFlag] = []
    seen: set[tuple[str, str]] = set()
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        name = _normalize_name(participant.get("name", ""))
        role = participant.get("role")
        if not name or role not in ALLOWED_EVENT_PARTICIPANT_ROLES:
            continue

        canonical_name = _resolve_relation_endpoint(name, name_index, aliases)
        if canonical_name is None:
            review_flags.append(
                ReviewFlag(
                    code="event_participant_missing_entity",
                    message=(
                        f"Event '{event_type}' participant '{name}' was not found "
                        "after canonicalization."
                    ),
                )
            )
            continue

        entity = name_index.get(canonical_name.casefold())
        if entity is None:
            continue
        key = (canonical_name.casefold(), role)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"name": canonical_name, "type": entity["type"], "role": role})

    return cleaned, review_flags


def _merge_relation_records(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for relation in [*left, *right]:
        source = relation.get("source")
        target = relation.get("target")
        relation_type = relation.get("type")
        evidence = relation.get("evidence")
        if not all(isinstance(value, str) and value for value in (source, target, relation_type, evidence)):
            continue
        key = (source.casefold(), target.casefold(), relation_type, evidence)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "evidence": evidence,
            }
        )
    return merged


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(float(value), 0.0), 1.0)


def _build_event_id(record: dict[str, Any], index: int, event_type: str) -> str:
    article_id = _slugify(_normalize_name(record.get("article_id", "")) or "article")
    return f"event:{article_id}:{index + 1:03d}:{_slugify(event_type)}"


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    relation_keys = tuple(
        (
            relation.get("source", "").casefold(),
            relation.get("target", "").casefold(),
            relation.get("type", ""),
            relation.get("evidence", ""),
        )
        for relation in event.get("relations", [])
        if isinstance(relation, dict)
    )
    return (
        event.get("event_type"),
        event.get("event_date"),
        event.get("location", "").casefold(),
        event.get("evidence", ""),
        relation_keys,
    )


def canonicalize_entity(
    name: str,
    entity_type: str,
    aliases: dict[str, AliasEntry],
) -> tuple[str, str]:
    normalized_name = _normalize_name(name)
    if entity_type == "NationState" and normalized_name.lower().startswith("the "):
        normalized_name = normalized_name[4:]

    alias = aliases.get(_alias_key(normalized_name))
    if alias is None:
        return normalized_name, entity_type

    canonical_type = alias.canonical_type or entity_type
    if canonical_type not in ALLOWED_ENTITY_TYPES:
        canonical_type = entity_type
    return alias.canonical_name, canonical_type


def review_location_name(name: str) -> list[ReviewFlag]:
    lowered = name.casefold()
    flags: list[ReviewFlag] = []
    generic_terms = ("port", "ports", "base", "bases", "airspace", "waters")
    if any(term in lowered.split() for term in generic_terms) or lowered.endswith(generic_terms):
        flags.append(
            ReviewFlag(
                code="generic_location_name",
                message=f"Location '{name}' looks generic and should be manually reviewed.",
            )
        )
    demonyms = ("iranian ", "israeli ", "american ", "british ", "pakistani ", "chinese ")
    if lowered.startswith(demonyms):
        flags.append(
            ReviewFlag(
                code="adjectival_location_name",
                message=(
                    f"Location '{name}' starts with a demonym and may need a manual "
                    "canonical form or override."
                ),
            )
        )
    return flags


def _resolve_relation_endpoint(
    name: str,
    name_index: dict[str, dict[str, Any]],
    aliases: dict[str, AliasEntry],
) -> str | None:
    normalized_name = _normalize_name(name)
    direct = name_index.get(normalized_name.casefold())
    if direct is not None:
        return direct["name"]

    alias = aliases.get(_alias_key(normalized_name))
    if alias is None:
        return None
    resolved = name_index.get(alias.canonical_name.casefold())
    return resolved["name"] if resolved is not None else None


def _append_alias(entity: dict[str, Any], alias_value: str) -> None:
    alias_value = _normalize_name(alias_value)
    if not alias_value or alias_value == entity["name"]:
        return
    aliases = entity.setdefault("aliases", [])
    if alias_value not in aliases:
        aliases.append(alias_value)


def _dedupe_flags(flags: list[ReviewFlag]) -> list[ReviewFlag]:
    seen: set[tuple[str, str]] = set()
    output: list[ReviewFlag] = []
    for flag in flags:
        key = (flag.code, flag.message)
        if key in seen:
            continue
        seen.add(key)
        output.append(flag)
    return output


def _alias_key(value: str) -> str:
    return _normalize_name(value).casefold().replace(".", "")


def _normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().strip("\"'").split())


def _slugify(value: str) -> str:
    slug = _normalize_name(value).casefold()
    output = []
    previous_dash = False
    for character in slug:
        if character.isalnum():
            output.append(character)
            previous_dash = False
        elif not previous_dash:
            output.append("-")
            previous_dash = True
    return "".join(output).strip("-")
