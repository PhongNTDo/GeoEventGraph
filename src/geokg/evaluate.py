"""Evaluation helpers for GeoKG gold annotations and model predictions."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PREDICTIONS = Path("data/postprocessed_event_v1/article_extractions_clean.jsonl")
DEFAULT_FAILURES = Path("data/extractions_event_v1/failures.jsonl")
DEFAULT_GOLD = Path("data/gold/event_mentions.gold.jsonl")
DEFAULT_CANDIDATES = Path("data/eval/annotation_candidates.jsonl")
DEFAULT_REPORT = Path("data/eval/report.json")
DEFAULT_MARKDOWN_REPORT = Path("data/eval/report.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidates = subparsers.add_parser(
        "generate-candidates",
        help="Create a draft annotation file from current cleaned predictions.",
    )
    candidates.add_argument(
        "--predictions",
        type=Path,
        default=DEFAULT_PREDICTIONS,
        help="Cleaned article extraction JSONL used as draft annotations.",
    )
    candidates.add_argument(
        "--failures",
        type=Path,
        default=DEFAULT_FAILURES,
        help="Optional extraction failures JSONL to include as hard cases.",
    )
    candidates.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="Output JSONL candidate file.",
    )
    candidates.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of candidate articles to select when --article-id is not used.",
    )
    candidates.add_argument(
        "--article-id",
        action="append",
        default=[],
        help="Specific article ID to include. Can be passed multiple times.",
    )
    candidates.add_argument(
        "--include-failures",
        action="store_true",
        help="Include extraction failure records after selected prediction records.",
    )
    candidates.set_defaults(func=_run_generate_candidates)

    score = subparsers.add_parser(
        "score",
        help="Score predictions against human-curated gold annotations.",
    )
    score.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help="Human-curated gold JSONL file.",
    )
    score.add_argument(
        "--predictions",
        type=Path,
        default=DEFAULT_PREDICTIONS,
        help="Cleaned article extraction JSONL to score.",
    )
    score.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT,
        help="Output JSON report path.",
    )
    score.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_REPORT,
        help="Output Markdown report path.",
    )
    score.add_argument(
        "--allow-draft-gold",
        action="store_true",
        help="Allow rows whose annotation_status is not 'gold'. Intended for tests only.",
    )
    score.set_defaults(func=_run_score)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


def generate_annotation_candidates(
    records: list[dict[str, Any]],
    *,
    failures: list[dict[str, Any]] | None = None,
    limit: int = 10,
    article_ids: list[str] | None = None,
    include_failures: bool = False,
) -> list[dict[str, Any]]:
    """Build draft gold rows from existing pipeline outputs."""

    failures = failures or []
    article_ids = article_ids or []
    record_by_id = {
        record.get("article_id"): record
        for record in records
        if isinstance(record.get("article_id"), str)
    }

    if article_ids:
        selected_records = [record_by_id[item] for item in article_ids if item in record_by_id]
    else:
        selected_records = _select_representative_records(records, limit)

    rows = [_candidate_from_prediction(record) for record in selected_records]

    if include_failures:
        selected_ids = {row["article_id"] for row in rows}
        for failure in failures:
            article_id = failure.get("article_id")
            if not isinstance(article_id, str) or article_id in selected_ids:
                continue
            rows.append(_candidate_from_failure(failure))
            selected_ids.add(article_id)
            if not article_ids and len(rows) >= limit:
                break

    return rows


def score_predictions(
    *,
    gold_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    allow_draft_gold: bool = False,
) -> dict[str, Any]:
    """Score cleaned predictions against curated gold records."""

    _validate_gold_records(gold_records, allow_draft_gold=allow_draft_gold)
    prediction_by_id = {
        record.get("article_id"): record
        for record in prediction_records
        if isinstance(record.get("article_id"), str)
    }
    gold_article_ids = [
        record["article_id"]
        for record in gold_records
        if isinstance(record.get("article_id"), str)
    ]
    missing_prediction_ids = [
        article_id for article_id in gold_article_ids if article_id not in prediction_by_id
    ]

    gold_entities = _collect_article_level_keys(gold_records, "entities", _entity_key)
    pred_entities = _collect_article_level_keys(
        [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids],
        "entities",
        _entity_key,
    )
    gold_relations = _collect_article_level_keys(gold_records, "relations", _relation_key)
    pred_relations = _collect_article_level_keys(
        [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids],
        "relations",
        _relation_key,
    )
    gold_event_keys = _collect_article_level_keys(gold_records, "events", _event_exact_key)
    pred_event_keys = _collect_article_level_keys(
        [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids],
        "events",
        _event_exact_key,
    )
    gold_participants = _collect_event_nested_keys(
        gold_records,
        "participants",
        _participant_key,
    )
    pred_participants = _collect_event_nested_keys(
        [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids],
        "participants",
        _participant_key,
    )
    gold_event_relations = _collect_event_nested_keys(
        gold_records,
        "relations",
        _relation_key,
    )
    pred_event_relations = _collect_event_nested_keys(
        [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids],
        "relations",
        _relation_key,
    )

    matched_pairs = _match_all_events(gold_records, prediction_by_id)
    matched_event_metrics = _matched_event_field_metrics(matched_pairs)

    gold_event_count = sum(len(_safe_list(record.get("events"))) for record in gold_records)
    pred_event_count = sum(
        len(_safe_list(prediction_by_id.get(article_id, {}).get("events")))
        for article_id in gold_article_ids
    )
    soft_event_counts = {
        "tp": len(matched_pairs),
        "fp": max(0, pred_event_count - len(matched_pairs)),
        "fn": max(0, gold_event_count - len(matched_pairs)),
    }

    report = {
        "gold": {
            "article_count": len(gold_records),
            "event_count": gold_event_count,
        },
        "predictions": {
            "article_count_in_scope": len(gold_article_ids) - len(missing_prediction_ids),
            "event_count_in_scope": pred_event_count,
            "missing_article_count": len(missing_prediction_ids),
        },
        "missing_prediction_article_ids": missing_prediction_ids,
        "metrics": {
            "entities": _metric_block(gold_entities, pred_entities, label_index=2),
            "relations": _metric_block(gold_relations, pred_relations, label_index=3),
            "events_exact": _metric_block(gold_event_keys, pred_event_keys, label_index=1),
            "events_soft": _counts_to_prf(soft_event_counts),
            "participants": _metric_block(gold_participants, pred_participants, label_index=6),
            "event_relations": _metric_block(
                gold_event_relations,
                pred_event_relations,
                label_index=6,
            ),
            "matched_event_fields": matched_event_metrics,
            "geocoding": _geocode_metrics(
                [prediction_by_id.get(article_id, {}) for article_id in gold_article_ids]
            ),
        },
    }
    return report


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    metrics = report["metrics"]
    lines = [
        "# GeoKG Evaluation Report",
        "",
        "## Scope",
        "",
        f"- Gold articles: {report['gold']['article_count']}",
        f"- Gold events: {report['gold']['event_count']}",
        f"- Prediction articles in scope: {report['predictions']['article_count_in_scope']}",
        f"- Prediction events in scope: {report['predictions']['event_count_in_scope']}",
        f"- Missing prediction articles: {report['predictions']['missing_article_count']}",
        "",
        "## Core Metrics",
        "",
        "| Metric | Precision | Recall | F1 | TP | FP | FN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in (
        "entities",
        "relations",
        "events_exact",
        "events_soft",
        "participants",
        "event_relations",
    ):
        item = metrics[name]["micro"] if "micro" in metrics[name] else metrics[name]
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    _format_number(item["precision"]),
                    _format_number(item["recall"]),
                    _format_number(item["f1"]),
                    str(item["tp"]),
                    str(item["fp"]),
                    str(item["fn"]),
                ]
            )
            + " |"
        )

    fields = metrics["matched_event_fields"]
    lines.extend(
        [
            "",
            "## Matched Event Fields",
            "",
            f"- Matched events: {fields['matched_event_count']}",
            f"- Event type accuracy: {_format_optional_rate(fields['event_type_accuracy'])}",
            f"- Event date accuracy: {_format_optional_rate(fields['event_date_accuracy'])}",
            f"- Date precision accuracy: {_format_optional_rate(fields['date_precision_accuracy'])}",
            f"- Location accuracy: {_format_optional_rate(fields['location_accuracy'])}",
            f"- Evidence exact match: {_format_optional_rate(fields['evidence_exact_match_rate'])}",
            f"- Evidence fuzzy match: {_format_optional_rate(fields['evidence_fuzzy_match_rate'])}",
            "",
            "## Geocoding",
            "",
        ]
    )
    geocoding = metrics["geocoding"]
    lines.extend(
        [
            f"- Predicted located events: {geocoding['located_event_count']}",
            f"- Located events with coordinates: {geocoding['located_event_with_coordinates_count']}",
            f"- Located event coordinate rate: {_format_optional_rate(geocoding['located_event_coordinate_rate'])}",
        ]
    )
    if report["missing_prediction_article_ids"]:
        lines.extend(["", "## Missing Prediction Articles", ""])
        lines.extend(f"- `{article_id}`" for article_id in report["missing_prediction_article_ids"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_generate_candidates(args: argparse.Namespace) -> None:
    records = _load_jsonl(args.predictions)
    failures = _load_jsonl(args.failures) if args.failures.exists() else []
    rows = generate_annotation_candidates(
        records,
        failures=failures,
        limit=args.limit,
        article_ids=args.article_id,
        include_failures=args.include_failures,
    )
    _write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "candidate_count": len(rows),
                "output": str(args.output),
                "next_step": "Copy selected rows into data/gold/event_mentions.gold.jsonl and curate them.",
            },
            ensure_ascii=False,
        )
    )


def _run_score(args: argparse.Namespace) -> None:
    if not args.gold.exists():
        raise SystemExit(
            f"Gold file not found: {args.gold}. Run `make eval-candidates`, then curate "
            "data/gold/event_mentions.gold.jsonl before scoring."
        )
    gold_records = _load_jsonl(args.gold)
    prediction_records = _load_jsonl(args.predictions)
    report = score_predictions(
        gold_records=gold_records,
        prediction_records=prediction_records,
        allow_draft_gold=args.allow_draft_gold,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(report, args.markdown_output)
    print(
        json.dumps(
            {
                "gold_articles": report["gold"]["article_count"],
                "gold_events": report["gold"]["event_count"],
                "report": str(args.output),
                "markdown_report": str(args.markdown_output),
            },
            ensure_ascii=False,
        )
    )


def _select_representative_records(
    records: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    eligible = [record for record in records if _safe_list(record.get("events"))]
    selected: list[dict[str, Any]] = []
    covered_event_types: set[str] = set()

    while eligible and len(selected) < limit:
        best_index = 0
        best_score: tuple[Any, ...] | None = None
        for index, record in enumerate(eligible):
            event_types = {
                event.get("event_type")
                for event in _safe_list(record.get("events"))
                if isinstance(event.get("event_type"), str)
            }
            new_types = event_types - covered_event_types
            score = (
                len(new_types),
                int(_record_has_missing_geocode(record)),
                int(_record_has_review_flags(record)),
                len(_safe_list(record.get("events"))),
                -index,
            )
            if best_score is None or score > best_score:
                best_index = index
                best_score = score
        record = eligible.pop(best_index)
        selected.append(record)
        covered_event_types.update(
            event.get("event_type")
            for event in _safe_list(record.get("events"))
            if isinstance(event.get("event_type"), str)
        )

    return selected


def _candidate_from_prediction(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": record.get("article_id"),
        "title": record.get("title"),
        "source": record.get("source"),
        "source_url": record.get("url") or record.get("source_url"),
        "published_at": record.get("published_at"),
        "annotation_status": "needs_human_review",
        "annotation_notes": [
            "This row is generated from model output and is not gold yet.",
            "Delete incorrect items, add missing items, correct labels/dates/locations/evidence, then set annotation_status to 'gold'.",
        ],
        "entities": [
            _project_entity(entity)
            for entity in _safe_list(record.get("entities"))
            if _project_entity(entity) is not None
        ],
        "relations": _project_relations(record.get("relations")),
        "events": _project_events(record.get("events")),
    }


def _candidate_from_failure(failure: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": failure.get("article_id"),
        "title": failure.get("title"),
        "source": None,
        "source_url": None,
        "published_at": None,
        "annotation_status": "needs_human_review",
        "annotation_notes": [
            "This article failed extraction. Add gold entities/events manually if it should be in the benchmark.",
            f"Extraction failure: {failure.get('error')}",
        ],
        "entities": [],
        "relations": [],
        "events": [],
    }


def _project_entity(entity: Any) -> dict[str, Any] | None:
    if not isinstance(entity, dict):
        return None
    name = entity.get("name")
    entity_type = entity.get("type")
    if not isinstance(name, str) or not isinstance(entity_type, str):
        return None
    output: dict[str, Any] = {"name": name, "type": entity_type}
    aliases = [alias for alias in _safe_list(entity.get("aliases")) if isinstance(alias, str)]
    if aliases:
        output["aliases"] = aliases
    return output


def _project_relation(relation: Any) -> dict[str, Any] | None:
    if not isinstance(relation, dict):
        return None
    source = relation.get("source")
    target = relation.get("target")
    relation_type = relation.get("type")
    if not all(isinstance(value, str) and value for value in (source, target, relation_type)):
        return None
    output = {"source": source, "target": target, "type": relation_type}
    evidence = relation.get("evidence")
    if isinstance(evidence, str) and evidence:
        output["evidence"] = evidence
    return output


def _project_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        return None
    output: dict[str, Any] = {
        "event_type": event_type,
        "event_date": event.get("event_date"),
        "date_precision": event.get("date_precision"),
        "location": event.get("location") or "",
        "participants": _project_participants(event.get("participants")),
        "relations": _project_relations(event.get("relations")),
        "summary": event.get("summary"),
        "evidence": event.get("evidence"),
        "confidence": event.get("confidence"),
    }
    location_geocode = event.get("location_geocode")
    if isinstance(location_geocode, dict):
        output["location_geocode"] = {
            key: location_geocode.get(key)
            for key in (
                "latitude",
                "longitude",
                "geocode_source",
                "geocode_display_name",
            )
            if location_geocode.get(key) is not None
        }
    elif event.get("latitude") is not None or event.get("longitude") is not None:
        output["location_geocode"] = {
            "latitude": event.get("latitude"),
            "longitude": event.get("longitude"),
            "geocode_source": event.get("location_geocode_source"),
            "geocode_display_name": event.get("location_geocode_display_name"),
        }
    return output


def _project_events(events: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event in _safe_list(events):
        projected = _project_event(event)
        if projected is not None:
            output.append(projected)
    return output


def _project_relations(relations: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for relation in _safe_list(relations):
        projected = _project_relation(relation)
        if projected is not None:
            output.append(projected)
    return output


def _project_participants(participants: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for participant in _safe_list(participants):
        projected = _project_participant(participant)
        if projected is not None:
            output.append(projected)
    return output


def _project_participant(participant: Any) -> dict[str, Any] | None:
    if not isinstance(participant, dict):
        return None
    name = participant.get("name")
    entity_type = participant.get("type")
    role = participant.get("role")
    if not all(isinstance(value, str) and value for value in (name, entity_type, role)):
        return None
    return {"name": name, "type": entity_type, "role": role}


def _validate_gold_records(
    gold_records: list[dict[str, Any]],
    *,
    allow_draft_gold: bool,
) -> None:
    if not gold_records:
        raise SystemExit(
            "Gold file has no rows. Add human-curated JSONL rows before running evaluation."
        )
    draft_ids = [
        record.get("article_id")
        for record in gold_records
        if record.get("annotation_status") != "gold"
    ]
    if draft_ids and not allow_draft_gold:
        raise SystemExit(
            "Gold file still contains rows whose annotation_status is not 'gold': "
            + ", ".join(str(item) for item in draft_ids)
        )
    missing_ids = [index for index, record in enumerate(gold_records, start=1) if not record.get("article_id")]
    if missing_ids:
        raise SystemExit(f"Gold rows missing article_id: {missing_ids}")


def _match_all_events(
    gold_records: list[dict[str, Any]],
    prediction_by_id: dict[Any, dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for gold_record in gold_records:
        article_id = gold_record.get("article_id")
        prediction = prediction_by_id.get(article_id, {})
        pairs.extend(_match_events(_safe_list(gold_record.get("events")), _safe_list(prediction.get("events"))))
    return pairs


def _match_events(
    gold_events: list[Any],
    pred_events: list[Any],
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    normalized_gold = [event for event in gold_events if isinstance(event, dict)]
    normalized_pred = [event for event in pred_events if isinstance(event, dict)]
    unused_pred = set(range(len(normalized_pred)))
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []

    for gold_event in normalized_gold:
        best_index: int | None = None
        best_score = 0.0
        for pred_index in unused_pred:
            score = _event_similarity(gold_event, normalized_pred[pred_index])
            if score > best_score:
                best_index = pred_index
                best_score = score
        if best_index is not None and best_score >= 0.45:
            unused_pred.remove(best_index)
            pairs.append((gold_event, normalized_pred[best_index], best_score))
    return pairs


def _event_similarity(gold_event: dict[str, Any], pred_event: dict[str, Any]) -> float:
    type_score = 1.0 if gold_event.get("event_type") == pred_event.get("event_type") else 0.0
    date_score = 1.0 if _norm_date(gold_event.get("event_date")) == _norm_date(pred_event.get("event_date")) else 0.0
    location_score = 1.0 if _norm(gold_event.get("location")) == _norm(pred_event.get("location")) else 0.0
    participant_score = _jaccard(
        {_participant_key(item) for item in _safe_list(gold_event.get("participants")) if _participant_key(item)},
        {_participant_key(item) for item in _safe_list(pred_event.get("participants")) if _participant_key(item)},
    )
    relation_score = _jaccard(
        {_relation_key(item) for item in _safe_list(gold_event.get("relations")) if _relation_key(item)},
        {_relation_key(item) for item in _safe_list(pred_event.get("relations")) if _relation_key(item)},
    )
    return (
        0.30 * type_score
        + 0.18 * date_score
        + 0.12 * location_score
        + 0.20 * participant_score
        + 0.20 * relation_score
    )


def _matched_event_field_metrics(
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]],
) -> dict[str, Any]:
    if not pairs:
        return {
            "matched_event_count": 0,
            "event_type_accuracy": None,
            "event_date_accuracy": None,
            "date_precision_accuracy": None,
            "location_accuracy": None,
            "evidence_exact_match_rate": None,
            "evidence_fuzzy_match_rate": None,
            "mean_match_similarity": None,
        }

    counts = Counter()
    for gold_event, pred_event, similarity in pairs:
        counts["matched"] += 1
        counts["similarity_sum"] += similarity
        counts["event_type"] += int(gold_event.get("event_type") == pred_event.get("event_type"))
        counts["event_date"] += int(_norm_date(gold_event.get("event_date")) == _norm_date(pred_event.get("event_date")))
        counts["date_precision"] += int(gold_event.get("date_precision") == pred_event.get("date_precision"))
        counts["location"] += int(_norm(gold_event.get("location")) == _norm(pred_event.get("location")))
        counts["evidence_exact"] += int(_norm_evidence(gold_event.get("evidence")) == _norm_evidence(pred_event.get("evidence")))
        counts["evidence_fuzzy"] += int(_evidence_fuzzy_match(gold_event.get("evidence"), pred_event.get("evidence")))

    total = counts["matched"]
    return {
        "matched_event_count": total,
        "event_type_accuracy": counts["event_type"] / total,
        "event_date_accuracy": counts["event_date"] / total,
        "date_precision_accuracy": counts["date_precision"] / total,
        "location_accuracy": counts["location"] / total,
        "evidence_exact_match_rate": counts["evidence_exact"] / total,
        "evidence_fuzzy_match_rate": counts["evidence_fuzzy"] / total,
        "mean_match_similarity": counts["similarity_sum"] / total,
    }


def _collect_article_level_keys(
    records: list[dict[str, Any]],
    field: str,
    key_func: Any,
) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    for record in records:
        article_id = record.get("article_id")
        if not isinstance(article_id, str):
            continue
        for item in _safe_list(record.get(field)):
            key = key_func(item)
            if key is not None:
                keys.add((article_id, *key))
    return keys


def _collect_event_nested_keys(
    records: list[dict[str, Any]],
    field: str,
    key_func: Any,
) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    for record in records:
        article_id = record.get("article_id")
        if not isinstance(article_id, str):
            continue
        for event in _safe_list(record.get("events")):
            if not isinstance(event, dict):
                continue
            event_anchor = (
                event.get("event_type"),
                _norm_date(event.get("event_date")),
                _norm(event.get("location")),
            )
            for item in _safe_list(event.get(field)):
                key = key_func(item)
                if key is not None:
                    keys.add((article_id, *event_anchor, *key))
    return keys


def _metric_block(
    gold_keys: set[tuple[Any, ...]],
    pred_keys: set[tuple[Any, ...]],
    *,
    label_index: int,
) -> dict[str, Any]:
    block = {"micro": _set_prf(gold_keys, pred_keys), "by_label": {}}
    labels = sorted(
        {
            key[label_index]
            for key in gold_keys | pred_keys
            if len(key) > label_index and key[label_index] not in (None, "")
        }
    )
    for label in labels:
        gold_subset = {key for key in gold_keys if len(key) > label_index and key[label_index] == label}
        pred_subset = {key for key in pred_keys if len(key) > label_index and key[label_index] == label}
        block["by_label"][str(label)] = _set_prf(gold_subset, pred_subset)
    return block


def _geocode_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    located = 0
    with_coordinates = 0
    for record in records:
        for event in _safe_list(record.get("events")):
            if not isinstance(event, dict) or not event.get("location"):
                continue
            located += 1
            location_geocode = event.get("location_geocode")
            latitude = None
            longitude = None
            if isinstance(location_geocode, dict):
                latitude = location_geocode.get("latitude")
                longitude = location_geocode.get("longitude")
            else:
                latitude = event.get("latitude")
                longitude = event.get("longitude")
            if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
                with_coordinates += 1
    return {
        "located_event_count": located,
        "located_event_with_coordinates_count": with_coordinates,
        "located_event_coordinate_rate": with_coordinates / located if located else None,
    }


def _entity_key(entity: Any) -> tuple[str, str] | None:
    if not isinstance(entity, dict):
        return None
    name = _norm(entity.get("name"))
    entity_type = entity.get("type")
    if not name or not isinstance(entity_type, str) or not entity_type:
        return None
    return (name, entity_type)


def _relation_key(relation: Any) -> tuple[str, str, str] | None:
    if not isinstance(relation, dict):
        return None
    source = _norm(relation.get("source"))
    target = _norm(relation.get("target"))
    relation_type = relation.get("type")
    if not source or not target or not isinstance(relation_type, str) or not relation_type:
        return None
    return (source, target, relation_type)


def _participant_key(participant: Any) -> tuple[str, str, str] | None:
    if not isinstance(participant, dict):
        return None
    name = _norm(participant.get("name"))
    entity_type = participant.get("type")
    role = participant.get("role")
    if not name or not isinstance(entity_type, str) or not isinstance(role, str):
        return None
    return (name, entity_type, role)


def _event_exact_key(event: Any) -> tuple[Any, ...] | None:
    if not isinstance(event, dict):
        return None
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        return None
    participants = tuple(
        sorted(
            key
            for key in (_participant_key(item) for item in _safe_list(event.get("participants")))
            if key is not None
        )
    )
    relations = tuple(
        sorted(
            key
            for key in (_relation_key(item) for item in _safe_list(event.get("relations")))
            if key is not None
        )
    )
    return (
        event_type,
        _norm_date(event.get("event_date")),
        event.get("date_precision"),
        _norm(event.get("location")),
        participants,
        relations,
    )


def _set_prf(
    gold_keys: set[tuple[Any, ...]],
    pred_keys: set[tuple[Any, ...]],
) -> dict[str, Any]:
    tp = len(gold_keys & pred_keys)
    fp = len(pred_keys - gold_keys)
    fn = len(gold_keys - pred_keys)
    return _counts_to_prf({"tp": tp, "fp": fp, "fn": fn})


def _counts_to_prf(counts: dict[str, int]) -> dict[str, Any]:
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _record_has_missing_geocode(record: dict[str, Any]) -> bool:
    for event in _safe_list(record.get("events")):
        if not isinstance(event, dict) or not event.get("location"):
            continue
        location_geocode = event.get("location_geocode")
        if not isinstance(location_geocode, dict):
            return True
        if location_geocode.get("latitude") is None or location_geocode.get("longitude") is None:
            return True
    return False


def _record_has_review_flags(record: dict[str, Any]) -> bool:
    if _safe_list(record.get("postprocess_review_flags")):
        return True
    for entity in _safe_list(record.get("entities")):
        if isinstance(entity, dict) and _safe_list(entity.get("review_flags")):
            return True
    for event in _safe_list(record.get("events")):
        if isinstance(event, dict) and _safe_list(event.get("review_flags")):
            return True
    return False


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row at {path}:{line_number} must be an object.")
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _norm(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().casefold().split())


def _norm_date(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _norm_evidence(value: Any) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold()) if isinstance(value, str) else ""


def _evidence_fuzzy_match(left: Any, right: Any) -> bool:
    left_norm = _norm_evidence(left)
    right_norm = _norm_evidence(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm or left_norm in right_norm or right_norm in left_norm:
        return True
    return _jaccard(set(left_norm.split()), set(right_norm.split())) >= 0.8


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _format_number(value: float) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    return f"{value:.3f}"


def _format_optional_rate(value: float | None) -> str:
    return "N/A" if value is None else _format_number(value)


if __name__ == "__main__":
    raise SystemExit(main())
