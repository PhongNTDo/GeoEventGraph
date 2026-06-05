"""CLI for post-processing extracted entities/relations and geocoding locations."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from geokg.geocoding import Geocoder, review_geocode_result
from geokg.postprocess import clean_extraction_record, load_aliases


GEOCODE_REVIEW_FIELDS = [
    "location_name",
    "article_id",
    "event_summary",
    "source_url",
    "current_latitude",
    "current_longitude",
    "suggested_latitude",
    "suggested_longitude",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/extractions/article_extractions.jsonl"),
        help="Raw extraction JSONL input.",
    )
    parser.add_argument(
        "--article-metadata",
        type=Path,
        default=Path("data/normalized/articles.jsonl"),
        help="Optional normalized article JSONL used to backfill source URLs and metadata.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/postprocessed"),
        help="Output directory for cleaned records and geocoding artifacts.",
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("data/reference/entity_aliases.csv"),
        help="CSV of alias -> canonical entity mappings.",
    )
    parser.add_argument(
        "--geocode-overrides",
        type=Path,
        default=Path("data/reference/geocode_overrides.csv"),
        help="CSV of manual geocode overrides.",
    )
    parser.add_argument(
        "--geocode-cache",
        type=Path,
        default=Path("data/reference/geocode_cache.json"),
        help="Persistent cache of geocoding responses.",
    )
    parser.add_argument(
        "--geocode-user-agent",
        default="GeoKG/0.1",
        help="User-Agent string for Nominatim requests.",
    )
    parser.add_argument(
        "--geocode-timeout-seconds",
        type=int,
        default=30,
        help="HTTP timeout for geocoding requests.",
    )
    parser.add_argument(
        "--geocode-delay-seconds",
        type=float,
        default=1.1,
        help="Minimum delay between live Nominatim requests.",
    )
    parser.add_argument(
        "--geocode-max-retries",
        type=int,
        default=2,
        help="Retries for transient Nominatim failures, including HTTP 429.",
    )
    parser.add_argument(
        "--offline-geocoding",
        action="store_true",
        help="Use only geocode overrides/cache and do not call Nominatim.",
    )
    parser.add_argument(
        "--geocode-review",
        type=Path,
        default=None,
        help=(
            "CSV for manual event geocode review. Defaults to "
            "<output-dir>/geocode_review.csv and preserves existing suggested coordinates."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    records = _load_jsonl(args.input)
    article_metadata = _load_article_metadata(args.article_metadata)
    records = [_merge_article_metadata(record, article_metadata) for record in records]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    aliases = load_aliases(args.aliases)
    geocoder = Geocoder(
        overrides_path=args.geocode_overrides,
        cache_path=args.geocode_cache,
        user_agent=args.geocode_user_agent,
        timeout_seconds=args.geocode_timeout_seconds,
        min_delay_seconds=args.geocode_delay_seconds,
        max_retries=args.geocode_max_retries,
        allow_remote=not args.offline_geocoding,
    )

    cleaned_records = [clean_extraction_record(record, aliases) for record in records]
    unique_locations = _collect_unique_locations(cleaned_records)
    geocoded_locations = _geocode_locations(unique_locations, geocoder)
    geocoder.persist_cache()

    cleaned_path = args.output_dir / "article_extractions_clean.jsonl"
    events_path = args.output_dir / "events_clean.jsonl"
    geocoded_path = args.output_dir / "geocoded_locations.jsonl"
    review_path = args.output_dir / "location_review.csv"
    geocode_review_path = args.geocode_review or args.output_dir / "geocode_review.csv"
    summary_path = args.output_dir / "summary.json"

    suggestions = _load_geocode_review_suggestions(geocode_review_path)
    cleaned_records = _attach_geocodes(cleaned_records, geocoded_locations, suggestions)

    _write_jsonl(cleaned_path, cleaned_records)
    flattened_events = _flatten_events(cleaned_records)
    _write_jsonl(events_path, flattened_events)
    _write_jsonl(geocoded_path, geocoded_locations.values())
    _write_review_csv(review_path, geocoded_locations)
    _write_geocode_review_csv(geocode_review_path, flattened_events, suggestions)
    _write_summary(
        summary_path,
        cleaned_records,
        flattened_events,
        geocoded_locations,
        review_path,
        geocode_review_path,
    )

    print(
        json.dumps(
            {
                "cleaned_records": len(cleaned_records),
                "cleaned_events": len(flattened_events),
                "unique_locations": len(geocoded_locations),
                "output_dir": str(args.output_dir),
                "events_jsonl": str(events_path),
                "review_csv": str(review_path),
                "geocode_review_csv": str(geocode_review_path),
            }
        )
    )
    return 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_article_metadata(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(path):
        article_id = row.get("article_id")
        if not isinstance(article_id, str) or not article_id:
            continue
        metadata[article_id] = {
            key: row.get(key)
            for key in ("title", "source", "published_at", "url")
            if row.get(key) is not None
        }
    return metadata


def _merge_article_metadata(
    record: dict[str, Any],
    article_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    article_id = record.get("article_id")
    if not isinstance(article_id, str):
        return record
    metadata = article_metadata.get(article_id)
    if metadata is None:
        return record

    merged = dict(record)
    for key, value in metadata.items():
        if merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def _collect_unique_locations(records: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    locations: list[str] = []
    for record in records:
        for entity in record.get("entities", []):
            if entity.get("type") != "StrategicLocation":
                continue
            name = entity.get("name")
            if not isinstance(name, str):
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            locations.append(name)
        for event in record.get("events", []):
            if not isinstance(event, dict):
                continue
            location = event.get("location")
            if not isinstance(location, str) or not location:
                continue
            key = location.casefold()
            if key in seen:
                continue
            seen.add(key)
            locations.append(location)
    return locations


def _geocode_locations(
    locations: list[str],
    geocoder: Geocoder,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for name in locations:
        record = geocoder.geocode(name)
        review_flags = review_geocode_result(name, record)
        output[name.casefold()] = {
            "name": name,
            "latitude": record.latitude,
            "longitude": record.longitude,
            "display_name": record.display_name,
            "geocode_source": record.source,
            "osm_type": record.osm_type,
            "osm_category": record.osm_category,
            "osm_addresstype": record.osm_addresstype,
            "raw_importance": record.raw_importance,
            "notes": record.notes,
            "review_flags": review_flags,
        }
    return output


def _attach_geocodes(
    records: list[dict[str, Any]],
    geocoded_locations: dict[str, dict[str, Any]],
    suggestions: dict[tuple[str, str, str], tuple[float | None, float | None]] | None = None,
) -> list[dict[str, Any]]:
    suggestions = suggestions or {}
    suggestions_by_location = _suggestions_by_location(suggestions)
    enriched_records: list[dict[str, Any]] = []
    for record in records:
        enriched = dict(record)
        entities: list[dict[str, Any]] = []
        for entity in record.get("entities", []):
            copied = dict(entity)
            if copied.get("type") == "StrategicLocation":
                geo = geocoded_locations.get(copied["name"].casefold())
                if geo is not None:
                    suggested_latitude, suggested_longitude = suggestions_by_location.get(
                        copied["name"].casefold(),
                        (None, None),
                    )
                    latitude, longitude = _preferred_coordinates(
                        geo["latitude"],
                        geo["longitude"],
                        suggested_latitude,
                        suggested_longitude,
                    )
                    copied["latitude"] = latitude
                    copied["longitude"] = longitude
                    copied["current_latitude"] = geo["latitude"]
                    copied["current_longitude"] = geo["longitude"]
                    copied["suggested_latitude"] = suggested_latitude
                    copied["suggested_longitude"] = suggested_longitude
                    copied["geocode_source"] = geo["geocode_source"]
                    copied["geocode_display_name"] = geo["display_name"]
                    if geo["review_flags"]:
                        flags = copied.setdefault("review_flags", [])
                        existing = {(flag["code"], flag["message"]) for flag in flags}
                        for flag in geo["review_flags"]:
                            key = (flag["code"], flag["message"])
                            if key not in existing:
                                flags.append(flag)
            entities.append(copied)
        enriched["entities"] = entities
        events: list[dict[str, Any]] = []
        for event in record.get("events", []):
            if not isinstance(event, dict):
                continue
            copied_event = dict(event)
            location = copied_event.get("location")
            if isinstance(location, str) and location:
                geo = geocoded_locations.get(location.casefold())
                if geo is not None:
                    suggestion_key = _geocode_review_key(
                        location_name=location,
                        article_id=record.get("article_id"),
                        event_summary=copied_event.get("summary"),
                    )
                    suggested_latitude, suggested_longitude = suggestions.get(
                        suggestion_key,
                        suggestions_by_location.get(location.casefold(), (None, None)),
                    )
                    latitude, longitude = _preferred_coordinates(
                        geo["latitude"],
                        geo["longitude"],
                        suggested_latitude,
                        suggested_longitude,
                    )
                    copied_event["location_geocode"] = {
                        "latitude": latitude,
                        "longitude": longitude,
                        "current_latitude": geo["latitude"],
                        "current_longitude": geo["longitude"],
                        "suggested_latitude": suggested_latitude,
                        "suggested_longitude": suggested_longitude,
                        "geocode_source": geo["geocode_source"],
                        "geocode_display_name": geo["display_name"],
                    }
                    if geo["review_flags"]:
                        flags = copied_event.setdefault("review_flags", [])
                        existing = {
                            (flag["code"], flag["message"])
                            for flag in flags
                            if isinstance(flag, dict)
                        }
                        for flag in geo["review_flags"]:
                            key = (flag["code"], flag["message"])
                            if key not in existing:
                                flags.append(flag)
            events.append(copied_event)
        enriched["events"] = events
        enriched_records.append(enriched)
    return enriched_records


def _flatten_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for record in records:
        for event in record.get("events", []):
            if not isinstance(event, dict):
                continue
            copied = dict(event)
            copied["article_id"] = record.get("article_id")
            copied["title"] = record.get("title")
            copied["source"] = record.get("source")
            copied["source_url"] = record.get("url") or record.get("source_url")
            copied["published_at"] = record.get("published_at")
            copied["model"] = record.get("model")
            copied["prompt_version"] = record.get("prompt_version")
            copied["extracted_at"] = record.get("extracted_at")
            events.append(copied)
    return events


def _write_jsonl(path: Path, rows: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _write_review_csv(path: Path, geocoded_locations: dict[str, dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "name",
            "latitude",
            "longitude",
            "display_name",
            "geocode_source",
            "review_code",
            "review_message",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for location in geocoded_locations.values():
            flags = location.get("review_flags", [])
            if not flags:
                continue
            for flag in flags:
                writer.writerow(
                    {
                        "name": location["name"],
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                        "display_name": location["display_name"],
                        "geocode_source": location["geocode_source"],
                        "review_code": flag["code"],
                        "review_message": flag["message"],
                    }
                )


def _load_geocode_review_suggestions(
    path: Path,
) -> dict[tuple[str, str, str], tuple[float | None, float | None]]:
    if not path.exists():
        return {}
    suggestions: dict[tuple[str, str, str], tuple[float | None, float | None]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = _geocode_review_key(
                location_name=row.get("location_name"),
                article_id=row.get("article_id"),
                event_summary=row.get("event_summary"),
            )
            latitude = _safe_float(row.get("suggested_latitude"))
            longitude = _safe_float(row.get("suggested_longitude"))
            if latitude is None and longitude is None:
                continue
            suggestions[key] = (latitude, longitude)
    return suggestions


def _write_geocode_review_csv(
    path: Path,
    events: list[dict[str, Any]],
    suggestions: dict[tuple[str, str, str], tuple[float | None, float | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        location = event.get("location")
        if not isinstance(location, str) or not location:
            continue
        article_id = event.get("article_id")
        summary = event.get("summary")
        key = _geocode_review_key(
            location_name=location,
            article_id=article_id,
            event_summary=summary,
        )
        if key in seen:
            continue
        seen.add(key)
        location_geocode = event.get("location_geocode", {})
        current_latitude = None
        current_longitude = None
        if isinstance(location_geocode, dict):
            current_latitude = location_geocode.get("current_latitude")
            current_longitude = location_geocode.get("current_longitude")
            if current_latitude is None:
                current_latitude = location_geocode.get("latitude")
            if current_longitude is None:
                current_longitude = location_geocode.get("longitude")
        suggested_latitude, suggested_longitude = suggestions.get(key, (None, None))
        rows.append(
            {
                "location_name": location,
                "article_id": article_id or "",
                "event_summary": summary or "",
                "source_url": event.get("source_url") or "",
                "current_latitude": current_latitude,
                "current_longitude": current_longitude,
                "suggested_latitude": suggested_latitude,
                "suggested_longitude": suggested_longitude,
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GEOCODE_REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: _csv_value(row.get(field))
                    for field in GEOCODE_REVIEW_FIELDS
                }
            )


def _geocode_review_key(
    *,
    location_name: Any,
    article_id: Any,
    event_summary: Any,
) -> tuple[str, str, str]:
    return (
        _normalize_key(location_name),
        _normalize_key(article_id),
        _normalize_key(event_summary),
    )


def _suggestions_by_location(
    suggestions: dict[tuple[str, str, str], tuple[float | None, float | None]],
) -> dict[str, tuple[float | None, float | None]]:
    output: dict[str, tuple[float | None, float | None]] = {}
    for key, coordinates in suggestions.items():
        latitude, longitude = coordinates
        if latitude is None or longitude is None:
            continue
        location_key = key[0]
        if location_key not in output:
            output[location_key] = coordinates
    return output


def _preferred_coordinates(
    current_latitude: Any,
    current_longitude: Any,
    suggested_latitude: Any,
    suggested_longitude: Any,
) -> tuple[float | None, float | None]:
    suggested_latitude = _safe_float(suggested_latitude)
    suggested_longitude = _safe_float(suggested_longitude)
    if suggested_latitude is not None and suggested_longitude is not None:
        return suggested_latitude, suggested_longitude
    return _safe_float(current_latitude), _safe_float(current_longitude)


def _normalize_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _csv_value(value: Any) -> Any:
    return "" if value is None else value


def _write_summary(
    path: Path,
    records: list[dict[str, Any]],
    events: list[dict[str, Any]],
    geocoded_locations: dict[str, dict[str, Any]],
    review_path: Path,
    geocode_review_path: Path,
) -> None:
    relation_counts = Counter()
    entity_counts = Counter()
    event_counts = Counter()
    review_count = 0
    for record in records:
        for entity in record.get("entities", []):
            entity_counts[entity.get("type", "unknown")] += 1
        for relation in record.get("relations", []):
            relation_counts[relation.get("type", "unknown")] += 1
    for event in events:
        event_counts[event.get("event_type", "unknown")] += 1
    for location in geocoded_locations.values():
        review_count += len(location.get("review_flags", []))

    summary = {
        "cleaned_record_count": len(records),
        "cleaned_event_count": len(events),
        "entity_type_counts": dict(entity_counts),
        "relation_type_counts": dict(relation_counts),
        "event_type_counts": dict(event_counts),
        "geocoded_location_count": len(geocoded_locations),
        "location_review_flag_count": review_count,
        "location_review_csv": str(review_path),
        "geocode_review_csv": str(geocode_review_path),
    }
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
