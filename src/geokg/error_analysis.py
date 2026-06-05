"""Generate detailed error analysis from GeoKG gold annotations."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geokg.evaluate import (
    DEFAULT_GOLD,
    DEFAULT_PREDICTIONS,
    DEFAULT_REPORT,
    _evidence_fuzzy_match,
    _event_similarity,
    _load_jsonl,
    _norm,
    _norm_date,
    _norm_evidence,
    _safe_list,
)


DEFAULT_OUTPUT = Path("data/eval/error_analysis.md")
DEFAULT_ERROR_DIR = Path("data/eval/errors")


@dataclass(slots=True)
class MatchedEvent:
    article_id: str
    title: str
    gold_index: int
    pred_index: int
    gold_event: dict[str, Any]
    pred_event: dict[str, Any]
    similarity: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--error-dir", type=Path, default=DEFAULT_ERROR_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_error_analysis(
        gold_records=_load_jsonl(args.gold),
        prediction_records=_load_jsonl(args.predictions),
        report=json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {},
    )
    write_error_analysis(result, output=args.output, error_dir=args.error_dir)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "error_dir": str(args.error_dir),
                "event_error_count": len(result["event_errors"]),
                "participant_error_count": len(result["participant_errors"]),
                "geocoding_error_count": len(result["geocoding_errors"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_error_analysis(
    *,
    gold_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prediction_by_id = {
        record.get("article_id"): record
        for record in prediction_records
        if isinstance(record.get("article_id"), str)
    }
    entity_errors: list[dict[str, Any]] = []
    relation_errors: list[dict[str, Any]] = []
    event_errors: list[dict[str, Any]] = []
    participant_errors: list[dict[str, Any]] = []
    event_relation_errors: list[dict[str, Any]] = []
    geocoding_errors: list[dict[str, Any]] = []
    article_summaries: list[dict[str, Any]] = []

    for gold_record in gold_records:
        article_id = gold_record["article_id"]
        title = gold_record.get("title", "")
        pred_record = prediction_by_id.get(article_id, {})

        entity_errors.extend(_compare_entities(article_id, title, gold_record, pred_record))
        relation_errors.extend(_compare_relations(article_id, title, gold_record, pred_record))

        matched_events, missed_events, extra_events = _match_article_events(
            article_id=article_id,
            title=title,
            gold_events=_safe_list(gold_record.get("events")),
            pred_events=_safe_list(pred_record.get("events")),
        )
        event_errors.extend(
            _event_level_errors(article_id, title, matched_events, missed_events, extra_events)
        )
        participant_errors.extend(_participant_level_errors(matched_events))
        event_relation_errors.extend(_event_relation_level_errors(matched_events))
        geocoding_errors.extend(
            _geocoding_errors(article_id, title, matched_events, missed_events, extra_events)
        )
        article_summaries.append(
            {
                "article_id": article_id,
                "title": title,
                "gold_events": len(_safe_list(gold_record.get("events"))),
                "pred_events": len(_safe_list(pred_record.get("events"))),
                "matched_events": len(matched_events),
                "missed_events": len(missed_events),
                "extra_events": len(extra_events),
                "entity_errors": sum(1 for item in entity_errors if item["article_id"] == article_id),
                "relation_errors": sum(1 for item in relation_errors if item["article_id"] == article_id),
                "participant_errors": sum(
                    1 for item in participant_errors if item["article_id"] == article_id
                ),
                "event_relation_errors": sum(
                    1 for item in event_relation_errors if item["article_id"] == article_id
                ),
                "geocoding_errors": sum(
                    1 for item in geocoding_errors if item["article_id"] == article_id
                ),
            }
        )

    return {
        "report": report or {},
        "article_summaries": article_summaries,
        "entity_errors": entity_errors,
        "relation_errors": relation_errors,
        "event_errors": event_errors,
        "participant_errors": participant_errors,
        "event_relation_errors": event_relation_errors,
        "geocoding_errors": geocoding_errors,
    }


def write_error_analysis(
    result: dict[str, Any],
    *,
    output: Path,
    error_dir: Path,
) -> None:
    error_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(error_dir / "articles.csv", result["article_summaries"])
    _write_csv(error_dir / "entities.csv", result["entity_errors"])
    _write_csv(error_dir / "relations.csv", result["relation_errors"])
    _write_csv(error_dir / "events.csv", result["event_errors"])
    _write_csv(error_dir / "participants.csv", result["participant_errors"])
    _write_csv(error_dir / "event_relations.csv", result["event_relation_errors"])
    _write_csv(error_dir / "geocoding.csv", result["geocoding_errors"])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_build_markdown(result, error_dir), encoding="utf-8")


def _compare_entities(
    article_id: str,
    title: str,
    gold_record: dict[str, Any],
    pred_record: dict[str, Any],
) -> list[dict[str, Any]]:
    gold = {_entity_key(item): item for item in _safe_list(gold_record.get("entities")) if _entity_key(item)}
    pred = {_entity_key(item): item for item in _safe_list(pred_record.get("entities")) if _entity_key(item)}
    errors: list[dict[str, Any]] = []
    for key in sorted(gold.keys() - pred.keys()):
        item = gold[key]
        errors.append(
            {
                "article_id": article_id,
                "title": title,
                "error_type": "missing_entity",
                "name": item.get("name"),
                "type": item.get("type"),
                "notes": "Gold entity was not present in prediction.",
            }
        )
    for key in sorted(pred.keys() - gold.keys()):
        item = pred[key]
        errors.append(
            {
                "article_id": article_id,
                "title": title,
                "error_type": "extra_entity",
                "name": item.get("name"),
                "type": item.get("type"),
                "notes": "Prediction entity was not present in gold.",
            }
        )
    return errors


def _compare_relations(
    article_id: str,
    title: str,
    gold_record: dict[str, Any],
    pred_record: dict[str, Any],
) -> list[dict[str, Any]]:
    gold = {
        _relation_key(item): item
        for item in _safe_list(gold_record.get("relations"))
        if _relation_key(item)
    }
    pred = {
        _relation_key(item): item
        for item in _safe_list(pred_record.get("relations"))
        if _relation_key(item)
    }
    errors: list[dict[str, Any]] = []
    for key in sorted(gold.keys() - pred.keys()):
        errors.append(_relation_error_row(article_id, title, "missing_relation", gold[key]))
    for key in sorted(pred.keys() - gold.keys()):
        errors.append(_relation_error_row(article_id, title, "extra_relation", pred[key]))
    return errors


def _match_article_events(
    *,
    article_id: str,
    title: str,
    gold_events: list[Any],
    pred_events: list[Any],
) -> tuple[list[MatchedEvent], list[tuple[int, dict[str, Any]]], list[tuple[int, dict[str, Any]]]]:
    normalized_gold = [(index, event) for index, event in enumerate(gold_events) if isinstance(event, dict)]
    normalized_pred = [(index, event) for index, event in enumerate(pred_events) if isinstance(event, dict)]
    unused_pred = set(range(len(normalized_pred)))
    matched: list[MatchedEvent] = []
    missed: list[tuple[int, dict[str, Any]]] = []

    for gold_index, gold_event in normalized_gold:
        best_local_index: int | None = None
        best_score = 0.0
        for local_pred_index in unused_pred:
            _, pred_event = normalized_pred[local_pred_index]
            score = _event_similarity(gold_event, pred_event)
            if score > best_score:
                best_local_index = local_pred_index
                best_score = score
        if best_local_index is not None and best_score >= 0.45:
            unused_pred.remove(best_local_index)
            pred_index, pred_event = normalized_pred[best_local_index]
            matched.append(
                MatchedEvent(
                    article_id=article_id,
                    title=title,
                    gold_index=gold_index,
                    pred_index=pred_index,
                    gold_event=gold_event,
                    pred_event=pred_event,
                    similarity=best_score,
                )
            )
        else:
            missed.append((gold_index, gold_event))

    extra = [normalized_pred[index] for index in sorted(unused_pred)]
    return matched, missed, extra


def _event_level_errors(
    article_id: str,
    title: str,
    matched: list[MatchedEvent],
    missed: list[tuple[int, dict[str, Any]]],
    extra: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for gold_index, gold_event in missed:
        errors.append(
            _event_error_row(
                article_id=article_id,
                title=title,
                error_type="missed_event",
                gold_index=gold_index,
                pred_index=None,
                similarity=None,
                gold_event=gold_event,
                pred_event={},
                issue_details="Gold event had no matching prediction.",
            )
        )
    for pred_index, pred_event in extra:
        errors.append(
            _event_error_row(
                article_id=article_id,
                title=title,
                error_type="extra_event",
                gold_index=None,
                pred_index=pred_index,
                similarity=None,
                gold_event={},
                pred_event=pred_event,
                issue_details="Prediction event had no matching gold event.",
            )
        )
    for pair in matched:
        issues = _matched_event_issues(pair.gold_event, pair.pred_event)
        if not issues:
            continue
        errors.append(
            _event_error_row(
                article_id=pair.article_id,
                title=pair.title,
                error_type="matched_event_field_mismatch",
                gold_index=pair.gold_index,
                pred_index=pair.pred_index,
                similarity=pair.similarity,
                gold_event=pair.gold_event,
                pred_event=pair.pred_event,
                issue_details="; ".join(issues),
            )
        )
    return errors


def _participant_level_errors(matched: list[MatchedEvent]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for pair in matched:
        gold = {
            _participant_key(item): item
            for item in _safe_list(pair.gold_event.get("participants"))
            if _participant_key(item)
        }
        pred = {
            _participant_key(item): item
            for item in _safe_list(pair.pred_event.get("participants"))
            if _participant_key(item)
        }
        gold_by_name_type = {
            (_norm(item.get("name")), item.get("type")): item
            for item in _safe_list(pair.gold_event.get("participants"))
            if isinstance(item, dict)
        }
        pred_by_name_type = {
            (_norm(item.get("name")), item.get("type")): item
            for item in _safe_list(pair.pred_event.get("participants"))
            if isinstance(item, dict)
        }
        for key in sorted(gold.keys() - pred.keys()):
            item = gold[key]
            same_entity = pred_by_name_type.get((_norm(item.get("name")), item.get("type")))
            errors.append(
                _participant_error_row(
                    pair,
                    "role_mismatch" if same_entity is not None else "missing_participant",
                    gold_participant=item,
                    pred_participant=same_entity or {},
                )
            )
        for key in sorted(pred.keys() - gold.keys()):
            item = pred[key]
            same_entity = gold_by_name_type.get((_norm(item.get("name")), item.get("type")))
            if same_entity is not None:
                continue
            errors.append(
                _participant_error_row(
                    pair,
                    "extra_participant",
                    gold_participant={},
                    pred_participant=item,
                )
            )
    return errors


def _event_relation_level_errors(matched: list[MatchedEvent]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for pair in matched:
        gold = {
            _relation_key(item): item
            for item in _safe_list(pair.gold_event.get("relations"))
            if _relation_key(item)
        }
        pred = {
            _relation_key(item): item
            for item in _safe_list(pair.pred_event.get("relations"))
            if _relation_key(item)
        }
        for key in sorted(gold.keys() - pred.keys()):
            errors.append(
                _event_relation_error_row(pair, "missing_event_relation", gold[key], {})
            )
        for key in sorted(pred.keys() - gold.keys()):
            errors.append(
                _event_relation_error_row(pair, "extra_event_relation", {}, pred[key])
            )
    return errors


def _geocoding_errors(
    article_id: str,
    title: str,
    matched: list[MatchedEvent],
    missed: list[tuple[int, dict[str, Any]]],
    extra: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for pair in matched:
        gold_location = pair.gold_event.get("location") or ""
        pred_location = pair.pred_event.get("location") or ""
        if gold_location and not pred_location:
            errors.append(_geocode_error_row(pair, "missing_predicted_location"))
            continue
        if gold_location and pred_location and _norm(gold_location) != _norm(pred_location):
            errors.append(_geocode_error_row(pair, "location_mismatch"))
        if pred_location and not _event_has_coordinates(pair.pred_event):
            errors.append(_geocode_error_row(pair, "predicted_location_missing_coordinates"))
    for _, event in missed:
        if event.get("location"):
            errors.append(
                {
                    "article_id": article_id,
                    "title": title,
                    "error_type": "missed_located_event",
                    "gold_event_type": event.get("event_type"),
                    "pred_event_type": "",
                    "gold_location": event.get("location"),
                    "pred_location": "",
                    "gold_coordinates": _coords_label(event),
                    "pred_coordinates": "",
                    "gold_summary": event.get("summary"),
                    "pred_summary": "",
                }
            )
    for _, event in extra:
        if event.get("location") and not _event_has_coordinates(event):
            errors.append(
                {
                    "article_id": article_id,
                    "title": title,
                    "error_type": "extra_located_event_missing_coordinates",
                    "gold_event_type": "",
                    "pred_event_type": event.get("event_type"),
                    "gold_location": "",
                    "pred_location": event.get("location"),
                    "gold_coordinates": "",
                    "pred_coordinates": _coords_label(event),
                    "gold_summary": "",
                    "pred_summary": event.get("summary"),
                }
            )
    return errors


def _matched_event_issues(gold_event: dict[str, Any], pred_event: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if gold_event.get("event_type") != pred_event.get("event_type"):
        issues.append("event_type")
    if _norm_date(gold_event.get("event_date")) != _norm_date(pred_event.get("event_date")):
        issues.append("event_date")
    if gold_event.get("date_precision") != pred_event.get("date_precision"):
        issues.append("date_precision")
    if _norm(gold_event.get("location")) != _norm(pred_event.get("location")):
        issues.append("location")
    if _norm_evidence(gold_event.get("evidence")) != _norm_evidence(pred_event.get("evidence")):
        issues.append(
            "evidence_fuzzy_match"
            if _evidence_fuzzy_match(gold_event.get("evidence"), pred_event.get("evidence"))
            else "evidence_mismatch"
        )
    return issues


def _event_error_row(
    *,
    article_id: str,
    title: str,
    error_type: str,
    gold_index: int | None,
    pred_index: int | None,
    similarity: float | None,
    gold_event: dict[str, Any],
    pred_event: dict[str, Any],
    issue_details: str,
) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "error_type": error_type,
        "gold_index": gold_index,
        "pred_index": pred_index,
        "match_similarity": _format_optional_float(similarity),
        "gold_event_type": gold_event.get("event_type", ""),
        "pred_event_type": pred_event.get("event_type", ""),
        "gold_event_date": gold_event.get("event_date", ""),
        "pred_event_date": pred_event.get("event_date", ""),
        "gold_date_precision": gold_event.get("date_precision", ""),
        "pred_date_precision": pred_event.get("date_precision", ""),
        "gold_location": gold_event.get("location", ""),
        "pred_location": pred_event.get("location", ""),
        "gold_summary": gold_event.get("summary", ""),
        "pred_summary": pred_event.get("summary", ""),
        "gold_evidence": gold_event.get("evidence", ""),
        "pred_evidence": pred_event.get("evidence", ""),
        "issue_details": issue_details,
    }


def _participant_error_row(
    pair: MatchedEvent,
    error_type: str,
    *,
    gold_participant: dict[str, Any],
    pred_participant: dict[str, Any],
) -> dict[str, Any]:
    return {
        "article_id": pair.article_id,
        "title": pair.title,
        "error_type": error_type,
        "gold_index": pair.gold_index,
        "pred_index": pair.pred_index,
        "match_similarity": _format_optional_float(pair.similarity),
        "event_type": pair.gold_event.get("event_type"),
        "event_date": pair.gold_event.get("event_date"),
        "gold_name": gold_participant.get("name", ""),
        "pred_name": pred_participant.get("name", ""),
        "gold_type": gold_participant.get("type", ""),
        "pred_type": pred_participant.get("type", ""),
        "gold_role": gold_participant.get("role", ""),
        "pred_role": pred_participant.get("role", ""),
        "gold_summary": pair.gold_event.get("summary", ""),
        "pred_summary": pair.pred_event.get("summary", ""),
    }


def _event_relation_error_row(
    pair: MatchedEvent,
    error_type: str,
    gold_relation: dict[str, Any],
    pred_relation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "article_id": pair.article_id,
        "title": pair.title,
        "error_type": error_type,
        "gold_index": pair.gold_index,
        "pred_index": pair.pred_index,
        "match_similarity": _format_optional_float(pair.similarity),
        "event_type": pair.gold_event.get("event_type"),
        "event_date": pair.gold_event.get("event_date"),
        "gold_source": gold_relation.get("source", ""),
        "pred_source": pred_relation.get("source", ""),
        "gold_target": gold_relation.get("target", ""),
        "pred_target": pred_relation.get("target", ""),
        "gold_type": gold_relation.get("type", ""),
        "pred_type": pred_relation.get("type", ""),
        "gold_evidence": gold_relation.get("evidence", ""),
        "pred_evidence": pred_relation.get("evidence", ""),
    }


def _relation_error_row(
    article_id: str,
    title: str,
    error_type: str,
    relation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "error_type": error_type,
        "source": relation.get("source"),
        "target": relation.get("target"),
        "type": relation.get("type"),
        "evidence": relation.get("evidence", ""),
    }


def _geocode_error_row(pair: MatchedEvent, error_type: str) -> dict[str, Any]:
    return {
        "article_id": pair.article_id,
        "title": pair.title,
        "error_type": error_type,
        "gold_event_type": pair.gold_event.get("event_type"),
        "pred_event_type": pair.pred_event.get("event_type"),
        "gold_location": pair.gold_event.get("location", ""),
        "pred_location": pair.pred_event.get("location", ""),
        "gold_coordinates": _coords_label(pair.gold_event),
        "pred_coordinates": _coords_label(pair.pred_event),
        "gold_summary": pair.gold_event.get("summary", ""),
        "pred_summary": pair.pred_event.get("summary", ""),
    }


def _build_markdown(result: dict[str, Any], error_dir: Path) -> str:
    report = result.get("report") or {}
    metrics = report.get("metrics", {})
    article_summaries = result["article_summaries"]
    counters = {
        "entity": Counter(row["error_type"] for row in result["entity_errors"]),
        "relation": Counter(row["error_type"] for row in result["relation_errors"]),
        "event": Counter(row["error_type"] for row in result["event_errors"]),
        "participant": Counter(row["error_type"] for row in result["participant_errors"]),
        "event_relation": Counter(row["error_type"] for row in result["event_relation_errors"]),
        "geocoding": Counter(row["error_type"] for row in result["geocoding_errors"]),
    }
    weakest_participants = _counter_table(counters["participant"], limit=8)
    weakest_events = _counter_table(counters["event"], limit=8)
    lines = [
        "# GeoKG Error Analysis",
        "",
        "Generated from the current gold annotations and prediction artifacts.",
        "",
        "## Metric Snapshot",
        "",
    ]
    if metrics:
        lines.extend(
            [
                f"- Entity F1: {_metric_f1(metrics.get('entities'))}",
                f"- Relation F1: {_metric_f1(metrics.get('relations'))}",
                f"- Event exact F1: {_metric_f1(metrics.get('events_exact'))}",
                f"- Event soft F1: {_metric_f1(metrics.get('events_soft'))}",
                f"- Participant F1: {_metric_f1(metrics.get('participants'))}",
                f"- Event relation F1: {_metric_f1(metrics.get('event_relations'))}",
                f"- Evidence exact match: {_format_optional_float(metrics.get('matched_event_fields', {}).get('evidence_exact_match_rate'))}",
                f"- Evidence fuzzy match: {_format_optional_float(metrics.get('matched_event_fields', {}).get('evidence_fuzzy_match_rate'))}",
                f"- Geocode coordinate rate: {_format_optional_float(metrics.get('geocoding', {}).get('located_event_coordinate_rate'))}",
                "",
            ]
        )
    lines.extend(
        [
            "## Error CSVs",
            "",
            f"- `{error_dir / 'articles.csv'}`",
            f"- `{error_dir / 'entities.csv'}`",
            f"- `{error_dir / 'relations.csv'}`",
            f"- `{error_dir / 'events.csv'}`",
            f"- `{error_dir / 'participants.csv'}`",
            f"- `{error_dir / 'event_relations.csv'}`",
            f"- `{error_dir / 'geocoding.csv'}`",
            "",
            "## Error Counts",
            "",
            f"- Entity errors: {len(result['entity_errors'])} ({_counter_summary(counters['entity'])})",
            f"- Relation errors: {len(result['relation_errors'])} ({_counter_summary(counters['relation'])})",
            f"- Event errors: {len(result['event_errors'])} ({_counter_summary(counters['event'])})",
            f"- Participant errors: {len(result['participant_errors'])} ({_counter_summary(counters['participant'])})",
            f"- Event relation errors: {len(result['event_relation_errors'])} ({_counter_summary(counters['event_relation'])})",
            f"- Geocoding errors: {len(result['geocoding_errors'])} ({_counter_summary(counters['geocoding'])})",
            "",
            "## Dominant Event Error Types",
            "",
            weakest_events or "No event errors found.",
            "",
            "## Dominant Participant Error Types",
            "",
            weakest_participants or "No participant errors found.",
            "",
            "## Most Problematic Articles",
            "",
            "| Article | Gold Events | Pred Events | Matched | Missed | Extra | Participant Errors | Geocoding Errors |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(
        article_summaries,
        key=lambda item: (
            item["missed_events"] + item["extra_events"] + item["participant_errors"],
            item["geocoding_errors"],
        ),
        reverse=True,
    )[:10]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['article_id']}`",
                    str(row["gold_events"]),
                    str(row["pred_events"]),
                    str(row["matched_events"]),
                    str(row["missed_events"]),
                    str(row["extra_events"]),
                    str(row["participant_errors"]),
                    str(row["geocoding_errors"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Initial Interpretation",
            "",
            "- High event soft F1 with low exact event F1 usually means the model often finds the right event family but disagrees on exact participants, relations, date precision, location, or evidence.",
            "- Participant and event-relation CSVs should be inspected before changing the ontology or prompt.",
            "- Geocoding rows separate missing coordinates from location mismatches, which helps decide whether extraction or geocoding should be fixed first.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _entity_key(entity: Any) -> tuple[str, str] | None:
    if not isinstance(entity, dict):
        return None
    name = _norm(entity.get("name"))
    entity_type = entity.get("type")
    if not name or not isinstance(entity_type, str):
        return None
    return name, entity_type


def _relation_key(relation: Any) -> tuple[str, str, str] | None:
    if not isinstance(relation, dict):
        return None
    source = _norm(relation.get("source"))
    target = _norm(relation.get("target"))
    relation_type = relation.get("type")
    if not source or not target or not isinstance(relation_type, str):
        return None
    return source, target, relation_type


def _participant_key(participant: Any) -> tuple[str, str, str] | None:
    if not isinstance(participant, dict):
        return None
    name = _norm(participant.get("name"))
    entity_type = participant.get("type")
    role = participant.get("role")
    if not name or not isinstance(entity_type, str) or not isinstance(role, str):
        return None
    return name, entity_type, role


def _event_has_coordinates(event: dict[str, Any]) -> bool:
    geocode = event.get("location_geocode")
    if isinstance(geocode, dict):
        latitude = geocode.get("latitude")
        longitude = geocode.get("longitude")
    else:
        latitude = event.get("latitude")
        longitude = event.get("longitude")
    return isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))


def _coords_label(event: dict[str, Any]) -> str:
    geocode = event.get("location_geocode")
    if isinstance(geocode, dict):
        latitude = geocode.get("latitude")
        longitude = geocode.get("longitude")
    else:
        latitude = event.get("latitude")
        longitude = event.get("longitude")
    if latitude is None or longitude is None:
        return ""
    return f"{latitude},{longitude}"


def _metric_f1(metric: Any) -> str:
    if not isinstance(metric, dict):
        return "N/A"
    block = metric.get("micro") if isinstance(metric.get("micro"), dict) else metric
    return _format_optional_float(block.get("f1"))


def _format_optional_float(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{value:.3f}"


def _counter_summary(counter: Counter[str]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counter.most_common())


def _counter_table(counter: Counter[str], *, limit: int) -> str:
    if not counter:
        return ""
    lines = ["| Error Type | Count |", "| --- | ---: |"]
    for key, value in counter.most_common(limit):
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
