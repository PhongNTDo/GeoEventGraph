"""Build manual side-by-side review packets for gold vs prediction cases."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from geokg.evaluate import (
    DEFAULT_GOLD,
    DEFAULT_PREDICTIONS,
    _evidence_fuzzy_match,
    _event_similarity,
    _load_jsonl,
    _norm,
    _norm_date,
    _norm_evidence,
    _participant_key,
    _relation_key,
    _safe_list,
)


DEFAULT_ARTICLES = Path("data/normalized/articles.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/eval/case_review")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=0.45,
        help="Minimum event similarity for automatic gold/prediction pairing.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = None
    if args.report is not None and args.report.exists():
        report = json.loads(args.report.read_text(encoding="utf-8"))
    review = build_case_review(
        gold_records=_load_jsonl(args.gold),
        prediction_records=_load_jsonl(args.predictions),
        article_records=_load_jsonl(args.articles) if args.articles.exists() else [],
        report=report,
        match_threshold=args.match_threshold,
    )
    write_case_review(review, args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "index": str(args.output_dir / "index.md"),
                "csv": str(args.output_dir / "case_review.csv"),
                "json": str(args.output_dir / "case_review.json"),
                "article_count": review["summary"]["article_count"],
                "matched_events": review["summary"]["matched_events"],
                "missed_gold_events": review["summary"]["missed_gold_events"],
                "extra_hybrid_events": review["summary"]["extra_prediction_events"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_case_review(
    *,
    gold_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    article_records: list[dict[str, Any]] | None = None,
    report: dict[str, Any] | None = None,
    match_threshold: float = 0.45,
) -> dict[str, Any]:
    prediction_by_id = {
        record.get("article_id"): record
        for record in prediction_records
        if isinstance(record.get("article_id"), str)
    }
    article_by_id = {
        record.get("article_id"): record
        for record in article_records or []
        if isinstance(record.get("article_id"), str)
    }

    article_reviews: list[dict[str, Any]] = []
    for gold_record in gold_records:
        article_id = gold_record["article_id"]
        prediction = prediction_by_id.get(article_id, {})
        article = article_by_id.get(article_id, {})
        article_reviews.append(
            build_article_review(
                gold_record=gold_record,
                prediction_record=prediction,
                article_record=article,
                match_threshold=match_threshold,
            )
        )

    summary = {
        "article_count": len(article_reviews),
        "gold_events": sum(item["counts"]["gold_events"] for item in article_reviews),
        "prediction_events": sum(item["counts"]["prediction_events"] for item in article_reviews),
        "matched_events": sum(item["counts"]["matched_events"] for item in article_reviews),
        "missed_gold_events": sum(item["counts"]["missed_gold_events"] for item in article_reviews),
        "extra_prediction_events": sum(
            item["counts"]["extra_prediction_events"] for item in article_reviews
        ),
    }
    return {
        "summary": summary,
        "report": report or {},
        "articles": article_reviews,
    }


def build_article_review(
    *,
    gold_record: dict[str, Any],
    prediction_record: dict[str, Any],
    article_record: dict[str, Any],
    match_threshold: float,
) -> dict[str, Any]:
    article_id = gold_record["article_id"]
    title = (
        gold_record.get("title")
        or prediction_record.get("title")
        or article_record.get("title")
        or ""
    )
    source_url = (
        gold_record.get("source_url")
        or gold_record.get("url")
        or prediction_record.get("source_url")
        or prediction_record.get("url")
        or article_record.get("url")
        or ""
    )
    gold_events = [item for item in _safe_list(gold_record.get("events")) if isinstance(item, dict)]
    prediction_events = [
        item for item in _safe_list(prediction_record.get("events")) if isinstance(item, dict)
    ]
    matched, missed, extra = match_article_events(
        gold_events=gold_events,
        prediction_events=prediction_events,
        threshold=match_threshold,
    )
    article_text = article_record.get("text", "")

    matched_reviews = [
        build_matched_event_review(pair, article_text=article_text) for pair in matched
    ]
    missed_reviews = [
        {
            "gold_index": gold_index,
            "best_prediction_similarity": best_prediction_similarity(event, prediction_events),
            "gold_event": add_event_context(event, article_text),
        }
        for gold_index, event in missed
    ]
    extra_reviews = [
        {
            "prediction_index": pred_index,
            "best_gold_similarity": best_gold_similarity(event, gold_events),
            "prediction_event": add_event_context(event, article_text),
        }
        for pred_index, event in extra
    ]

    return {
        "article_id": article_id,
        "title": title,
        "source": gold_record.get("source") or prediction_record.get("source") or article_record.get("source"),
        "source_url": source_url,
        "published_at": (
            gold_record.get("published_at")
            or prediction_record.get("published_at")
            or article_record.get("published_at")
        ),
        "counts": {
            "gold_events": len(gold_events),
            "prediction_events": len(prediction_events),
            "matched_events": len(matched_reviews),
            "missed_gold_events": len(missed_reviews),
            "extra_prediction_events": len(extra_reviews),
        },
        "matched_events": matched_reviews,
        "missed_gold_events": missed_reviews,
        "extra_prediction_events": extra_reviews,
        "entity_diff": diff_entities(gold_record, prediction_record),
        "relation_diff": diff_relations(gold_record, prediction_record),
    }


def match_article_events(
    *,
    gold_events: list[dict[str, Any]],
    prediction_events: list[dict[str, Any]],
    threshold: float,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
]:
    unused_prediction_indexes = set(range(len(prediction_events)))
    matched: list[dict[str, Any]] = []
    missed: list[tuple[int, dict[str, Any]]] = []
    for gold_index, gold_event in enumerate(gold_events):
        best_prediction_index: int | None = None
        best_score = 0.0
        for prediction_index in unused_prediction_indexes:
            score = _event_similarity(gold_event, prediction_events[prediction_index])
            if score > best_score:
                best_prediction_index = prediction_index
                best_score = score
        if best_prediction_index is not None and best_score >= threshold:
            unused_prediction_indexes.remove(best_prediction_index)
            matched.append(
                {
                    "gold_index": gold_index,
                    "prediction_index": best_prediction_index,
                    "similarity": best_score,
                    "gold_event": gold_event,
                    "prediction_event": prediction_events[best_prediction_index],
                }
            )
        else:
            missed.append((gold_index, gold_event))
    extra = [(index, prediction_events[index]) for index in sorted(unused_prediction_indexes)]
    return matched, missed, extra


def build_matched_event_review(
    pair: dict[str, Any],
    *,
    article_text: str,
) -> dict[str, Any]:
    gold_event = pair["gold_event"]
    prediction_event = pair["prediction_event"]
    participant_diff = diff_participants(gold_event, prediction_event)
    relation_diff = diff_event_relations(gold_event, prediction_event)
    field_mismatches = matched_field_mismatches(gold_event, prediction_event)
    if participant_diff["missing"] or participant_diff["extra"] or participant_diff["role_mismatches"]:
        field_mismatches.append("participants")
    if relation_diff["missing"] or relation_diff["extra"]:
        field_mismatches.append("event_relations")
    return {
        "gold_index": pair["gold_index"],
        "prediction_index": pair["prediction_index"],
        "match_similarity": round(pair["similarity"], 3),
        "field_mismatches": field_mismatches,
        "gold_event": add_event_context(gold_event, article_text),
        "prediction_event": add_event_context(prediction_event, article_text),
        "participant_diff": participant_diff,
        "relation_diff": relation_diff,
        "review_decision": "",
        "review_notes": "",
    }


def matched_field_mismatches(
    gold_event: dict[str, Any],
    prediction_event: dict[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    if gold_event.get("event_type") != prediction_event.get("event_type"):
        mismatches.append("event_type")
    if _norm_date(gold_event.get("event_date")) != _norm_date(prediction_event.get("event_date")):
        mismatches.append("event_date")
    if gold_event.get("date_precision") != prediction_event.get("date_precision"):
        mismatches.append("date_precision")
    if _norm(gold_event.get("location")) != _norm(prediction_event.get("location")):
        mismatches.append("location")
    if _norm_evidence(gold_event.get("evidence")) != _norm_evidence(
        prediction_event.get("evidence")
    ):
        mismatches.append(
            "evidence_fuzzy_match"
            if _evidence_fuzzy_match(gold_event.get("evidence"), prediction_event.get("evidence"))
            else "evidence_mismatch"
        )
    return mismatches


def diff_entities(
    gold_record: dict[str, Any],
    prediction_record: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return diff_items(
        _safe_list(gold_record.get("entities")),
        _safe_list(prediction_record.get("entities")),
        key_func=entity_key,
    )


def diff_relations(
    gold_record: dict[str, Any],
    prediction_record: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return diff_items(
        _safe_list(gold_record.get("relations")),
        _safe_list(prediction_record.get("relations")),
        key_func=_relation_key,
    )


def diff_participants(
    gold_event: dict[str, Any],
    prediction_event: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    gold = {
        _participant_key(item): item
        for item in _safe_list(gold_event.get("participants"))
        if _participant_key(item)
    }
    prediction = {
        _participant_key(item): item
        for item in _safe_list(prediction_event.get("participants"))
        if _participant_key(item)
    }
    gold_by_entity = {
        (_norm(item.get("name")), item.get("type")): item
        for item in _safe_list(gold_event.get("participants"))
        if isinstance(item, dict)
    }
    prediction_by_entity = {
        (_norm(item.get("name")), item.get("type")): item
        for item in _safe_list(prediction_event.get("participants"))
        if isinstance(item, dict)
    }
    missing: list[dict[str, Any]] = []
    role_mismatches: list[dict[str, Any]] = []
    for key in sorted(gold.keys() - prediction.keys()):
        item = gold[key]
        same_entity = prediction_by_entity.get((_norm(item.get("name")), item.get("type")))
        if same_entity is None:
            missing.append(item)
        else:
            role_mismatches.append({"gold": item, "prediction": same_entity})
    extra: list[dict[str, Any]] = []
    for key in sorted(prediction.keys() - gold.keys()):
        item = prediction[key]
        same_entity = gold_by_entity.get((_norm(item.get("name")), item.get("type")))
        if same_entity is None:
            extra.append(item)
    return {
        "missing": missing,
        "extra": extra,
        "role_mismatches": role_mismatches,
    }


def diff_event_relations(
    gold_event: dict[str, Any],
    prediction_event: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return diff_items(
        _safe_list(gold_event.get("relations")),
        _safe_list(prediction_event.get("relations")),
        key_func=_relation_key,
    )


def diff_items(
    gold_items: list[Any],
    prediction_items: list[Any],
    *,
    key_func: Any,
) -> dict[str, list[dict[str, Any]]]:
    gold = {key_func(item): item for item in gold_items if key_func(item)}
    prediction = {key_func(item): item for item in prediction_items if key_func(item)}
    return {
        "missing": [gold[key] for key in sorted(gold.keys() - prediction.keys())],
        "extra": [prediction[key] for key in sorted(prediction.keys() - gold.keys())],
    }


def entity_key(entity: Any) -> tuple[str, str] | None:
    if not isinstance(entity, dict):
        return None
    name = _norm(entity.get("name"))
    entity_type = entity.get("type")
    if not name or not isinstance(entity_type, str):
        return None
    return name, entity_type


def best_prediction_similarity(event: dict[str, Any], prediction_events: list[dict[str, Any]]) -> float:
    if not prediction_events:
        return 0.0
    return round(max(_event_similarity(event, prediction) for prediction in prediction_events), 3)


def best_gold_similarity(event: dict[str, Any], gold_events: list[dict[str, Any]]) -> float:
    if not gold_events:
        return 0.0
    return round(max(_event_similarity(gold, event) for gold in gold_events), 3)


def add_event_context(event: dict[str, Any], article_text: str) -> dict[str, Any]:
    copied = dict(event)
    copied["source_context"] = nearby_context(article_text, event.get("evidence", ""))
    return copied


def nearby_context(article_text: Any, evidence: Any, window: int = 220) -> str:
    if not isinstance(article_text, str) or not isinstance(evidence, str):
        return ""
    normalized_text = " ".join(article_text.split())
    normalized_evidence = " ".join(evidence.split())
    if not normalized_text or not normalized_evidence:
        return ""
    index = normalized_text.casefold().find(normalized_evidence.casefold())
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(normalized_text), index + len(normalized_evidence) + window)
    return normalized_text[start:end].strip()


def write_case_review(review: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "case_review.json").write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_case_review_csv(review, output_dir / "case_review.csv")
    article_dir = output_dir / "articles"
    article_dir.mkdir(parents=True, exist_ok=True)
    for article_review in review["articles"]:
        article_path = article_dir / f"{safe_filename(article_review['article_id'])}.md"
        article_path.write_text(article_markdown(article_review), encoding="utf-8")
    (output_dir / "index.md").write_text(index_markdown(review), encoding="utf-8")


def write_case_review_csv(review: dict[str, Any], path: Path) -> None:
    rows = case_review_csv_rows(review)
    fieldnames = [
        "article_id",
        "title",
        "status",
        "gold_index",
        "hybrid_index",
        "match_similarity",
        "field_mismatches",
        "gold_event_type",
        "hybrid_event_type",
        "gold_event_date",
        "hybrid_event_date",
        "gold_location",
        "hybrid_location",
        "gold_summary",
        "hybrid_summary",
        "gold_evidence",
        "hybrid_evidence",
        "review_decision",
        "review_notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def case_review_csv_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for article in review["articles"]:
        base = {"article_id": article["article_id"], "title": article["title"]}
        for pair in article["matched_events"]:
            rows.append(
                {
                    **base,
                    "status": "matched",
                    "gold_index": pair["gold_index"],
                    "hybrid_index": pair["prediction_index"],
                    "match_similarity": pair["match_similarity"],
                    "field_mismatches": ", ".join(pair["field_mismatches"]),
                    **event_csv_fields(pair["gold_event"], pair["prediction_event"]),
                    "review_decision": "",
                    "review_notes": "",
                }
            )
        for item in article["missed_gold_events"]:
            rows.append(
                {
                    **base,
                    "status": "missed_gold",
                    "gold_index": item["gold_index"],
                    "hybrid_index": "",
                    "match_similarity": item["best_prediction_similarity"],
                    "field_mismatches": "unmatched_gold",
                    **event_csv_fields(item["gold_event"], {}),
                    "review_decision": "",
                    "review_notes": "",
                }
            )
        for item in article["extra_prediction_events"]:
            rows.append(
                {
                    **base,
                    "status": "extra_hybrid",
                    "gold_index": "",
                    "hybrid_index": item["prediction_index"],
                    "match_similarity": item["best_gold_similarity"],
                    "field_mismatches": "unmatched_hybrid",
                    **event_csv_fields({}, item["prediction_event"]),
                    "review_decision": "",
                    "review_notes": "",
                }
            )
    return rows


def event_csv_fields(
    gold_event: dict[str, Any],
    prediction_event: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gold_event_type": gold_event.get("event_type", ""),
        "hybrid_event_type": prediction_event.get("event_type", ""),
        "gold_event_date": gold_event.get("event_date", ""),
        "hybrid_event_date": prediction_event.get("event_date", ""),
        "gold_location": gold_event.get("location", ""),
        "hybrid_location": prediction_event.get("location", ""),
        "gold_summary": gold_event.get("summary", ""),
        "hybrid_summary": prediction_event.get("summary", ""),
        "gold_evidence": gold_event.get("evidence", ""),
        "hybrid_evidence": prediction_event.get("evidence", ""),
    }


def index_markdown(review: dict[str, Any]) -> str:
    summary = review["summary"]
    lines = [
        "# Hybrid Case Review",
        "",
        "Manual review packet for gold annotations vs hybrid extraction output.",
        "",
        "Use `case_review.csv` for editable decisions. Suggested decision values: "
        "`gold_correct`, `hybrid_better`, `merge_needed`, `both_wrong`, `uncertain`.",
        "",
        "## Summary",
        "",
        f"- Articles: {summary['article_count']}",
        f"- Gold events: {summary['gold_events']}",
        f"- Hybrid events: {summary['prediction_events']}",
        f"- Matched events: {summary['matched_events']}",
        f"- Missed gold events: {summary['missed_gold_events']}",
        f"- Extra hybrid events: {summary['extra_prediction_events']}",
        "",
    ]
    metrics = review.get("report", {}).get("metrics", {})
    if metrics:
        lines.extend(
            [
                "## Metric Snapshot",
                "",
                f"- Event soft F1: {format_metric(metrics.get('events_soft'), 'f1')}",
                f"- Event exact F1: {format_metric(metrics.get('events_exact'), 'f1')}",
                f"- Participant F1: {format_metric(metrics.get('participants'), 'f1')}",
                f"- Event relation F1: {format_metric(metrics.get('event_relations'), 'f1')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Article Packets",
            "",
            "| Article | Gold | Hybrid | Matched | Missed Gold | Extra Hybrid |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for article in review["articles"]:
        counts = article["counts"]
        filename = f"articles/{safe_filename(article['article_id'])}.md"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"[`{article['article_id']}`]({filename})",
                    str(counts["gold_events"]),
                    str(counts["prediction_events"]),
                    str(counts["matched_events"]),
                    str(counts["missed_gold_events"]),
                    str(counts["extra_prediction_events"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def article_markdown(article: dict[str, Any]) -> str:
    lines = [
        f"# {article['article_id']}",
        "",
        f"**Title:** {escape_markdown_text(article.get('title', ''))}",
        "",
    ]
    if article.get("source_url"):
        lines.append(f"**Source:** {article['source_url']}")
        lines.append("")
    if article.get("published_at"):
        lines.append(f"**Published:** {article['published_at']}")
        lines.append("")

    counts = article["counts"]
    lines.extend(
        [
            "## Review Checklist",
            "",
            "- [ ] Check matched events field by field.",
            "- [ ] Check missed gold events: did hybrid miss them, or is gold too broad?",
            "- [ ] Check extra hybrid events: false positive, or should gold be expanded?",
            "- [ ] Record decisions in `../case_review.csv`.",
            "",
            "## Counts",
            "",
            "| Gold | Hybrid | Matched | Missed Gold | Extra Hybrid |",
            "| ---: | ---: | ---: | ---: | ---: |",
            "| "
            + " | ".join(
                [
                    str(counts["gold_events"]),
                    str(counts["prediction_events"]),
                    str(counts["matched_events"]),
                    str(counts["missed_gold_events"]),
                    str(counts["extra_prediction_events"]),
                ]
            )
            + " |",
            "",
            "## Matched Events",
            "",
        ]
    )
    if not article["matched_events"]:
        lines.extend(["No matched events.", ""])
    for index, pair in enumerate(article["matched_events"], start=1):
        lines.extend(matched_event_markdown(index, pair))

    lines.extend(["## Missed Gold Events", ""])
    if not article["missed_gold_events"]:
        lines.extend(["No missed gold events.", ""])
    for item in article["missed_gold_events"]:
        lines.extend(
            [
                f"### Gold #{item['gold_index'] + 1}",
                "",
                f"Best hybrid similarity: `{item['best_prediction_similarity']}`",
                "",
                event_markdown("Gold", item["gold_event"]),
            ]
        )

    lines.extend(["## Extra Hybrid Events", ""])
    if not article["extra_prediction_events"]:
        lines.extend(["No extra hybrid events.", ""])
    for item in article["extra_prediction_events"]:
        lines.extend(
            [
                f"### Hybrid #{item['prediction_index'] + 1}",
                "",
                f"Best gold similarity: `{item['best_gold_similarity']}`",
                "",
                event_markdown("Hybrid", item["prediction_event"]),
            ]
        )

    lines.extend(
        [
            "## Article-Level Entity Diff",
            "",
            diff_markdown(article["entity_diff"], label="entities"),
            "",
            "## Article-Level Relation Diff",
            "",
            diff_markdown(article["relation_diff"], label="relations"),
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def matched_event_markdown(index: int, pair: dict[str, Any]) -> list[str]:
    gold_event = pair["gold_event"]
    prediction_event = pair["prediction_event"]
    mismatches = ", ".join(pair["field_mismatches"]) or "none"
    lines = [
        f"### Match {index}: Gold #{pair['gold_index'] + 1} vs Hybrid #{pair['prediction_index'] + 1}",
        "",
        f"- Similarity: `{pair['match_similarity']}`",
        f"- Field mismatches: `{mismatches}`",
        "",
        "| Field | Gold | Hybrid |",
        "| --- | --- | --- |",
    ]
    for field in ("event_type", "event_date", "date_precision", "location", "summary"):
        lines.append(
            "| "
            + " | ".join(
                [
                    field,
                    markdown_cell(gold_event.get(field, "")),
                    markdown_cell(prediction_event.get(field, "")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "#### Evidence",
            "",
            "| Gold | Hybrid |",
            "| --- | --- |",
            f"| {markdown_cell(gold_event.get('evidence', ''))} | {markdown_cell(prediction_event.get('evidence', ''))} |",
            "",
            "#### Source Context",
            "",
            "| Gold Context | Hybrid Context |",
            "| --- | --- |",
            f"| {markdown_cell(gold_event.get('source_context', ''))} | {markdown_cell(prediction_event.get('source_context', ''))} |",
            "",
            "#### Participants",
            "",
            "Gold:",
            "",
            participant_table(gold_event.get("participants")),
            "",
            "Hybrid:",
            "",
            participant_table(prediction_event.get("participants")),
            "",
            "Participant diff:",
            "",
            participant_diff_markdown(pair["participant_diff"]),
            "",
            "#### Event Relations",
            "",
            "Gold:",
            "",
            relation_table(gold_event.get("relations")),
            "",
            "Hybrid:",
            "",
            relation_table(prediction_event.get("relations")),
            "",
            "Relation diff:",
            "",
            diff_markdown(pair["relation_diff"], label="relations"),
            "",
        ]
    )
    return lines


def event_markdown(label: str, event: dict[str, Any]) -> str:
    lines = [
        f"**{label} event:** `{event.get('event_type', '')}` | "
        f"`{event.get('event_date', '')}` | `{event.get('date_precision', '')}` | "
        f"location: `{event.get('location', '')}`",
        "",
        f"Summary: {escape_markdown_text(event.get('summary', ''))}",
        "",
        f"Evidence: {escape_markdown_text(event.get('evidence', ''))}",
        "",
    ]
    if event.get("source_context"):
        lines.extend(
            [
                f"Context: {escape_markdown_text(event.get('source_context', ''))}",
                "",
            ]
        )
    lines.extend(
        [
            "Participants:",
            "",
            participant_table(event.get("participants")),
            "",
            "Relations:",
            "",
            relation_table(event.get("relations")),
            "",
        ]
    )
    return "\n".join(lines)


def participant_table(participants: Any) -> str:
    rows = [
        [
            item.get("name", ""),
            item.get("type", ""),
            item.get("role", ""),
        ]
        for item in _safe_list(participants)
        if isinstance(item, dict)
    ]
    return markdown_table(["Name", "Type", "Role"], rows)


def relation_table(relations: Any) -> str:
    rows = [
        [
            item.get("source", ""),
            item.get("target", ""),
            item.get("type", ""),
            item.get("evidence", ""),
        ]
        for item in _safe_list(relations)
        if isinstance(item, dict)
    ]
    return markdown_table(["Source", "Target", "Type", "Evidence"], rows)


def participant_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        f"- Missing: {compact_items(diff['missing'])}",
        f"- Extra: {compact_items(diff['extra'])}",
    ]
    if diff["role_mismatches"]:
        role_rows = []
        for item in diff["role_mismatches"]:
            role_rows.append(
                [
                    item["gold"].get("name", ""),
                    item["gold"].get("role", ""),
                    item["prediction"].get("role", ""),
                ]
            )
        lines.extend(["", markdown_table(["Name", "Gold Role", "Hybrid Role"], role_rows)])
    else:
        lines.append("- Role mismatches: none")
    return "\n".join(lines)


def diff_markdown(diff: dict[str, Any], *, label: str) -> str:
    missing = compact_items(diff.get("missing", []))
    extra = compact_items(diff.get("extra", []))
    return f"- Missing {label}: {missing}\n- Extra {label}: {extra}"


def compact_items(items: Any) -> str:
    rows = [compact_item(item) for item in _safe_list(items) if isinstance(item, dict)]
    return "; ".join(rows) if rows else "none"


def compact_item(item: dict[str, Any]) -> str:
    if {"name", "type", "role"} <= item.keys():
        return f"{item.get('name')} ({item.get('type')}, {item.get('role')})"
    if {"name", "type"} <= item.keys():
        return f"{item.get('name')} ({item.get('type')})"
    if {"source", "target", "type"} <= item.keys():
        return f"{item.get('source')} -> {item.get('target')} ({item.get('type')})"
    return json.dumps(item, ensure_ascii=False)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "None."
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(value) for value in row) + " |")
    return "\n".join(lines)


def markdown_cell(value: Any) -> str:
    text = escape_markdown_text(value)
    text = text.replace("\n", " ")
    return text or ""


def escape_markdown_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return text


def format_metric(metric: Any, field: str) -> str:
    if not isinstance(metric, dict):
        return "N/A"
    block = metric.get("micro") if isinstance(metric.get("micro"), dict) else metric
    value = block.get(field) if isinstance(block, dict) else None
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:.3f}"


def safe_filename(value: Any) -> str:
    text = str(value) if value is not None else "article"
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text)
    return text.strip("-") or "article"


if __name__ == "__main__":
    raise SystemExit(main())
