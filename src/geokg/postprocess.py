"""Post-processing helpers for extracted entities and relations."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geokg.ontology import ALLOWED_ENTITY_TYPES, ALLOWED_RELATION_TYPES


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

    cleaned_relations: list[dict[str, Any]] = []
    seen_relations: set[tuple[str, str, str, str]] = set()
    for raw_relation in original_relations:
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

    for entity in cleaned_entities:
        if entity["type"] == "StrategicLocation":
            entity_flags = review_location_name(entity["name"])
            if entity_flags:
                entity["review_flags"] = [flag.to_dict() for flag in entity_flags]
                review_flags.extend(entity_flags)

    cleaned_record = dict(record)
    cleaned_record["entities"] = cleaned_entities
    cleaned_record["relations"] = cleaned_relations
    cleaned_record["postprocess_review_flags"] = [flag.to_dict() for flag in _dedupe_flags(review_flags)]
    return cleaned_record


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
