"""Apply manual case-review decisions to produce an adjudicated gold JSONL."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from geokg.evaluate import _load_jsonl, _safe_list
from geokg.ontology import ALLOWED_ENTITY_TYPES


DEFAULT_REVIEW_XLSX = Path("data/eval/event-v2-hybrid/case_review/case_review.xlsx")
DEFAULT_GOLD = Path("data/gold/event_mentions.gold.jsonl")
DEFAULT_PREDICTIONS = Path(
    "data/eval/event-v2-hybrid/postprocessed/article_extractions_clean.jsonl"
)
DEFAULT_OUTPUT_GOLD = Path("data/gold/event_mentions.hybrid_reviewed.gold.jsonl")
DEFAULT_SYNCED_CSV = Path("data/eval/event-v2-hybrid/case_review/case_review.csv")
DEFAULT_SUMMARY = Path("data/eval/event-v2-hybrid/case_review/adjudication_summary.json")


DECISIONS = {
    "gold_correct",
    "hybrid_better",
    "both_correct",
    "merge_needed",
    "both_wrong",
    "uncertain",
}

HYBRID_DECISIONS = {"hybrid_better", "both_correct"}
GOLD_DECISIONS = {"gold_correct", "merge_needed"}
DROP_DECISIONS = {"both_wrong", "uncertain"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-xlsx", type=Path, default=DEFAULT_REVIEW_XLSX)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output-gold", type=Path, default=DEFAULT_OUTPUT_GOLD)
    parser.add_argument("--synced-csv", type=Path, default=DEFAULT_SYNCED_CSV)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review_rows = read_review_xlsx(args.review_xlsx)
    result = adjudicate_case_review(
        review_rows=review_rows,
        gold_records=_load_jsonl(args.gold),
        prediction_records=_load_jsonl(args.predictions),
    )
    write_jsonl(args.output_gold, result["records"])
    write_review_csv(args.synced_csv, review_rows)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(result["summary"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_gold": str(args.output_gold),
                "synced_csv": str(args.synced_csv),
                "summary": str(args.summary_output),
                **result["summary"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def adjudicate_case_review(
    *,
    review_rows: list[dict[str, Any]],
    gold_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_review_rows(review_rows)
    rows_by_article: dict[str, list[dict[str, Any]]] = {}
    for row in review_rows:
        rows_by_article.setdefault(str(row["article_id"]), []).append(row)

    prediction_by_id = {
        record.get("article_id"): record
        for record in prediction_records
        if isinstance(record.get("article_id"), str)
    }

    output_records: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    status_decision_counts: Counter[str] = Counter()
    for gold_record in gold_records:
        article_id = gold_record["article_id"]
        prediction_record = prediction_by_id.get(article_id, {})
        rows = rows_by_article.get(article_id, [])
        adjudicated, article_counts = adjudicate_article(
            gold_record=gold_record,
            prediction_record=prediction_record,
            review_rows=rows,
        )
        output_records.append(adjudicated)
        source_counts.update(article_counts["source_counts"])
        decision_counts.update(article_counts["decision_counts"])
        status_decision_counts.update(article_counts["status_decision_counts"])

    summary = {
        "article_count": len(output_records),
        "event_count": sum(len(_safe_list(record.get("events"))) for record in output_records),
        "source_counts": dict(sorted(source_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "status_decision_counts": dict(sorted(status_decision_counts.items())),
        "adjudication_rules": {
            "matched_gold_correct": "keep gold event",
            "matched_hybrid_better": "use hybrid event",
            "matched_both_correct": "use hybrid event so accepted hybrid variants are not penalized",
            "matched_merge_needed": "keep gold event unless notes specify a manual merge",
            "both_wrong_or_uncertain": "drop event",
            "missed_gold_gold_correct_or_both_correct": "keep gold event",
            "extra_hybrid_hybrid_better_or_both_correct": "add hybrid event",
        },
    }
    return {"records": output_records, "summary": summary}


def adjudicate_article(
    *,
    gold_record: dict[str, Any],
    prediction_record: dict[str, Any],
    review_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Counter[str]]]:
    gold_events = [event for event in _safe_list(gold_record.get("events")) if isinstance(event, dict)]
    prediction_events = [
        event for event in _safe_list(prediction_record.get("events")) if isinstance(event, dict)
    ]
    entity_index, entity_templates = build_entity_indexes(gold_record, prediction_record)

    selected_events: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    status_decision_counts: Counter[str] = Counter()
    for row in review_rows:
        status = normalize_text(row.get("status"))
        decision = normalize_text(row.get("review_decision"))
        decision_counts[decision] += 1
        status_decision_counts[f"{status}:{decision}"] += 1
        event: dict[str, Any] | None = None
        source = "dropped"

        if status == "matched":
            gold_index = parse_index(row.get("gold_index"))
            hybrid_index = parse_index(row.get("hybrid_index"))
            if decision in HYBRID_DECISIONS:
                event = get_indexed_event(prediction_events, hybrid_index, "hybrid", row)
                source = "hybrid"
            elif decision in GOLD_DECISIONS:
                event = get_indexed_event(gold_events, gold_index, "gold", row)
                source = "gold"
            elif decision in DROP_DECISIONS:
                event = None
            else:
                raise ValueError(f"Unsupported decision for matched row: {decision}")
        elif status == "missed_gold":
            gold_index = parse_index(row.get("gold_index"))
            if decision in {"gold_correct", "both_correct", "merge_needed"}:
                event = get_indexed_event(gold_events, gold_index, "gold", row)
                source = "gold"
            elif decision in {"hybrid_better", *DROP_DECISIONS}:
                event = None
            else:
                raise ValueError(f"Unsupported decision for missed_gold row: {decision}")
        elif status == "extra_hybrid":
            hybrid_index = parse_index(row.get("hybrid_index"))
            if decision in {"hybrid_better", "both_correct", "merge_needed"}:
                event = get_indexed_event(prediction_events, hybrid_index, "hybrid", row)
                source = "hybrid"
            elif decision in {"gold_correct", *DROP_DECISIONS}:
                event = None
            else:
                raise ValueError(f"Unsupported decision for extra_hybrid row: {decision}")
        else:
            raise ValueError(f"Unsupported review status: {status}")

        source_counts[source] += 1
        if event is not None:
            selected_events.append(project_event(event))

    record = {
        "article_id": gold_record.get("article_id"),
        "title": gold_record.get("title") or prediction_record.get("title"),
        "source": gold_record.get("source") or prediction_record.get("source"),
        "source_url": gold_record.get("source_url")
        or gold_record.get("url")
        or prediction_record.get("source_url")
        or prediction_record.get("url"),
        "published_at": gold_record.get("published_at") or prediction_record.get("published_at"),
        "annotation_status": "gold",
        "annotation_notes": build_annotation_notes(gold_record),
        "entities": build_entities(selected_events, entity_index, entity_templates),
        "relations": build_top_level_relations(selected_events),
        "events": selected_events,
    }
    return (
        record,
        {
            "source_counts": source_counts,
            "decision_counts": decision_counts,
            "status_decision_counts": status_decision_counts,
        },
    )


def build_annotation_notes(gold_record: dict[str, Any]) -> list[str]:
    notes = [
        note for note in _safe_list(gold_record.get("annotation_notes")) if isinstance(note, str)
    ]
    notes.append(
        "Adjudicated from data/eval/event-v2-hybrid/case_review/case_review.xlsx."
    )
    notes.append(
        "Review decisions applied by geokg.adjudicate_case_review; see adjudication_summary.json for rules."
    )
    return notes


def validate_review_rows(rows: list[dict[str, Any]]) -> None:
    required = {
        "article_id",
        "status",
        "gold_index",
        "hybrid_index",
        "review_decision",
    }
    if not rows:
        raise ValueError("Review workbook has no data rows.")
    missing_headers = required - set(rows[0].keys())
    if missing_headers:
        raise ValueError(f"Review workbook missing columns: {', '.join(sorted(missing_headers))}")
    blank_decisions = [index for index, row in enumerate(rows, start=2) if not row.get("review_decision")]
    if blank_decisions:
        raise ValueError(f"Review rows missing review_decision: {blank_decisions[:20]}")
    invalid_decisions = sorted(
        {
            normalize_text(row.get("review_decision"))
            for row in rows
            if normalize_text(row.get("review_decision")) not in DECISIONS
        }
    )
    if invalid_decisions:
        raise ValueError(f"Unsupported review_decision values: {', '.join(invalid_decisions)}")


def get_indexed_event(
    events: list[dict[str, Any]],
    index: int | None,
    source: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    if index is None or index < 0 or index >= len(events):
        article_id = row.get("article_id")
        raise ValueError(f"Invalid {source} index {index!r} for article {article_id}.")
    return events[index]


def project_event(event: dict[str, Any]) -> dict[str, Any]:
    output = {
        "event_type": event.get("event_type"),
        "event_date": event.get("event_date"),
        "date_precision": event.get("date_precision"),
        "location": event.get("location") or "",
        "participants": [project_participant(item) for item in _safe_list(event.get("participants"))],
        "relations": [project_relation(item) for item in _safe_list(event.get("relations"))],
        "summary": event.get("summary"),
        "evidence": event.get("evidence"),
        "confidence": event.get("confidence", 1.0),
    }
    output["participants"] = [item for item in output["participants"] if item is not None]
    output["relations"] = [item for item in output["relations"] if item is not None]
    geocode = event.get("location_geocode")
    if isinstance(geocode, dict):
        output["location_geocode"] = {
            key: geocode.get(key)
            for key in (
                "latitude",
                "longitude",
                "current_latitude",
                "current_longitude",
                "suggested_latitude",
                "suggested_longitude",
                "geocode_source",
                "geocode_display_name",
            )
            if geocode.get(key) is not None
        }
    return output


def project_participant(participant: Any) -> dict[str, Any] | None:
    if not isinstance(participant, dict):
        return None
    name = participant.get("name")
    entity_type = participant.get("type")
    role = participant.get("role")
    if not all(isinstance(item, str) and item for item in (name, entity_type, role)):
        return None
    return {"name": name, "type": entity_type, "role": role}


def project_relation(relation: Any) -> dict[str, Any] | None:
    if not isinstance(relation, dict):
        return None
    source = relation.get("source")
    target = relation.get("target")
    relation_type = relation.get("type")
    if not all(isinstance(item, str) and item for item in (source, target, relation_type)):
        return None
    output = {"source": source, "target": target, "type": relation_type}
    evidence = relation.get("evidence")
    if isinstance(evidence, str):
        output["evidence"] = evidence
    return output


def build_entity_indexes(
    gold_record: dict[str, Any],
    prediction_record: dict[str, Any],
) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    entity_index: dict[str, str] = {}
    templates: dict[tuple[str, str], dict[str, Any]] = {}
    for record in (gold_record, prediction_record):
        for entity in _safe_list(record.get("entities")):
            if not isinstance(entity, dict):
                continue
            name = entity.get("name")
            entity_type = entity.get("type")
            if not isinstance(name, str) or entity_type not in ALLOWED_ENTITY_TYPES:
                continue
            key = normalize_key(name)
            entity_index.setdefault(key, entity_type)
            templates.setdefault((key, entity_type), project_entity(entity))
        for event in _safe_list(record.get("events")):
            if not isinstance(event, dict):
                continue
            for participant in _safe_list(event.get("participants")):
                projected = project_participant(participant)
                if projected is None:
                    continue
                key = normalize_key(projected["name"])
                entity_index.setdefault(key, projected["type"])
                templates.setdefault(
                    (key, projected["type"]),
                    {"name": projected["name"], "type": projected["type"], "aliases": []},
                )
            location = event.get("location")
            if isinstance(location, str) and location:
                key = normalize_key(location)
                entity_index.setdefault(key, "StrategicLocation")
                templates.setdefault(
                    (key, "StrategicLocation"),
                    {"name": location, "type": "StrategicLocation", "aliases": []},
                )
    return entity_index, templates


def project_entity(entity: dict[str, Any]) -> dict[str, Any]:
    output = {"name": entity.get("name"), "type": entity.get("type")}
    aliases = [alias for alias in _safe_list(entity.get("aliases")) if isinstance(alias, str)]
    output["aliases"] = aliases
    return output


def build_entities(
    events: list[dict[str, Any]],
    entity_index: dict[str, str],
    templates: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    entities: list[dict[str, Any]] = []

    def add_entity(name: Any, entity_type: Any | None = None) -> None:
        if not isinstance(name, str) or not name:
            return
        resolved_type = entity_type
        if resolved_type not in ALLOWED_ENTITY_TYPES:
            resolved_type = entity_index.get(normalize_key(name))
        if resolved_type not in ALLOWED_ENTITY_TYPES:
            return
        key = (normalize_key(name), str(resolved_type))
        if key in seen:
            return
        seen.add(key)
        template = copy.deepcopy(templates.get(key, {"name": name, "type": resolved_type, "aliases": []}))
        entities.append(template)

    for event in events:
        for participant in _safe_list(event.get("participants")):
            if isinstance(participant, dict):
                add_entity(participant.get("name"), participant.get("type"))
        location = event.get("location")
        if isinstance(location, str) and location:
            add_entity(location, entity_index.get(normalize_key(location), "StrategicLocation"))
        for relation in _safe_list(event.get("relations")):
            if isinstance(relation, dict):
                add_entity(relation.get("source"))
                add_entity(relation.get("target"))
    return entities


def build_top_level_relations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for event in events:
        for relation in _safe_list(event.get("relations")):
            projected = project_relation(relation)
            if projected is None:
                continue
            key = (
                str(projected.get("source", "")).casefold(),
                str(projected.get("target", "")).casefold(),
                str(projected.get("type", "")),
                str(projected.get("evidence", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            relations.append(projected)
    return relations


def read_review_xlsx(path: Path) -> list[dict[str, Any]]:
    rows = read_first_xlsx_sheet(path)
    return [row for row in rows if any(value not in (None, "") for value in row.values())]


def read_first_xlsx_sheet(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_path = first_sheet_path(archive)
        root = ET.fromstring(archive.read(sheet_path))

    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    raw_rows: list[list[Any]] = []
    max_col = 0
    for row_node in root.findall(".//main:sheetData/main:row", ns):
        values: dict[int, Any] = {}
        for cell in row_node.findall("main:c", ns):
            ref = cell.attrib.get("r", "")
            col_index = column_index_from_ref(ref)
            values[col_index] = read_cell_value(cell, shared_strings, ns)
            max_col = max(max_col, col_index)
        if values:
            raw_rows.append([values.get(index) for index in range(1, max_col + 1)])
    if not raw_rows:
        return []
    headers = [normalize_header(value) for value in raw_rows[0]]
    output: list[dict[str, Any]] = []
    for raw_row in raw_rows[1:]:
        output.append(
            {
                header: raw_row[index] if index < len(raw_row) else None
                for index, header in enumerate(headers)
                if header
            }
        )
    return output


def first_sheet_path(archive: zipfile.ZipFile) -> str:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook.find(".//main:sheets/main:sheet", ns)
    if first_sheet is None:
        raise ValueError("Workbook has no sheets.")
    rel_id = first_sheet.attrib.get(f"{{{ns['rel']}}}id")
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("pkgrel:Relationship", ns):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib["Target"]
            return f"xl/{target}" if not target.startswith("xl/") else target
    raise ValueError(f"Could not resolve first sheet relationship {rel_id}.")


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("main:si", ns):
        parts = [node.text or "" for node in item.findall(".//main:t", ns)]
        strings.append("".join(parts))
    return strings


def read_cell_value(
    cell: ET.Element,
    shared_strings: list[str],
    ns: dict[str, str],
) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", ns))
    value_node = cell.find("main:v", ns)
    if value_node is None or value_node.text is None:
        return None
    value = value_node.text
    if cell_type == "s":
        return shared_strings[int(value)]
    if cell_type == "str":
        return value
    if re.match(r"^-?\d+(\.\d+)?$", value):
        number = float(value)
        return int(number) if number.is_integer() else number
    return value


def column_index_from_ref(ref: str) -> int:
    letters = "".join(char for char in ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return index


def normalize_header(value: Any) -> str:
    return normalize_text(value).replace(" ", "_")


def parse_index(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    return int(float(text))


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split()).casefold()


def normalize_key(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})


if __name__ == "__main__":
    raise SystemExit(main())
