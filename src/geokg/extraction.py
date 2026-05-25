"""Prompting and validation for relation extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from geokg.ontology import ALLOWED_ENTITY_TYPES, ALLOWED_RELATION_TYPES


SYSTEM_PROMPT = """You extract geopolitical entities and relations from news articles.

Return JSON only. Do not return Markdown. Do not add commentary.

You must obey this ontology exactly.
- Allowed entity types: NationState, NonStateActor, PoliticalLeader, StrategicLocation, MilitaryAsset
- Allowed relation types: ATTACKED, THREATENED, NEGOTIATED_WITH, SUPPORTED, SANCTIONED, BLOCKADED

Rules:
- Extract only facts explicitly supported by the article text.
- Do not infer hidden actors, motives, or missing links.
- Do not invent entities or relation types outside the ontology.
- If a relation is implied but not explicit enough for a short supporting quote, omit it.
- Use canonical English names where obvious, for example United States instead of US.
- Include every entity referenced by a relation in the entities list.
- Evidence must be an exact short quote copied from the article text.
- If no valid entities or relations exist, return empty arrays.
"""


def extraction_json_schema() -> dict[str, Any]:
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
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "type": {"type": "string", "enum": list(ALLOWED_RELATION_TYPES)},
                        "evidence": {"type": "string"},
                    },
                    "required": ["source", "target", "type", "evidence"],
                },
            },
        },
        "required": ["entities", "relations"],
    }


def build_extraction_prompt(article: dict[str, Any]) -> str:
    schema = {
        "entities": [{"name": "string", "type": "AllowedEntityType"}],
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
        "Extract entities and relations from this article.\n\n"
        "Output schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        f"Allowed entity types: {', '.join(ALLOWED_ENTITY_TYPES)}\n"
        f"Allowed relation types: {', '.join(ALLOWED_RELATION_TYPES)}\n\n"
        "Article metadata:\n"
        f"- article_id: {article['article_id']}\n"
        f"- source: {article.get('source', '')}\n"
        f"- title: {article.get('title', '')}\n"
        f"- published_at: {article.get('published_at', '')}\n\n"
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
    if not isinstance(entities, list):
        errors.append("'entities' must be an array.")
    if not isinstance(relations, list):
        errors.append("'relations' must be an array.")
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
        path = f"relations[{idx}]"
        if not isinstance(relation, dict):
            errors.append(f"{path} must be an object.")
            continue

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
            errors.append(
                f"{path}.type must be one of {', '.join(ALLOWED_RELATION_TYPES)}."
            )
        if not evidence:
            errors.append(f"{path}.evidence must be a non-empty string.")

        if not source or not target or not evidence or relation_type not in ALLOWED_RELATION_TYPES:
            continue
        if source.casefold() not in entity_index:
            errors.append(f"{path}.source references missing entity '{source}'.")
            continue
        if target.casefold() not in entity_index:
            errors.append(f"{path}.target references missing entity '{target}'.")
            continue
        if not _evidence_exists(evidence, normalized_article_text):
            errors.append(f"{path}.evidence must be an exact quote from the article text.")
            continue

        key = (source.casefold(), target.casefold(), relation_type, evidence)
        if key in seen_relations:
            continue
        seen_relations.add(key)
        normalized_relations.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "evidence": evidence,
            }
        )

    if errors:
        return ValidationResult(None, errors)

    normalized = {
        "entities": normalized_entities,
        "relations": normalized_relations,
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
        "model": model,
        "extracted_at": datetime.now(tz=UTC).isoformat(),
        "entities": extraction["entities"],
        "relations": extraction["relations"],
    }


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
