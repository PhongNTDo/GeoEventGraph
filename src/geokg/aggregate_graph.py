"""CLI for aggregating cleaned article extractions into graph artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NodeAggregate:
    id: str
    name: str
    type: str
    latitude: float | None = None
    longitude: float | None = None
    geocode_source: str | None = None
    geocode_display_name: str | None = None
    aliases: set[str] = field(default_factory=set)
    article_ids: set[str] = field(default_factory=set)
    relation_ids: set[str] = field(default_factory=set)
    first_seen: str | None = None
    last_seen: str | None = None
    review_flags: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geocode_source": self.geocode_source,
            "geocode_display_name": self.geocode_display_name,
            "aliases": sorted(self.aliases),
            "article_ids": sorted(self.article_ids),
            "article_count": len(self.article_ids),
            "relation_count": len(self.relation_ids),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "review_flags": self.review_flags,
        }


@dataclass(slots=True)
class EdgeAggregate:
    id: str
    source: str
    target: str
    type: str
    article_ids: set[str] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)
    evidences: list[dict[str, Any]] = field(default_factory=list)
    review_flags: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        sorted_dates = sorted(self.dates)
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "weight": len(self.evidences),
            "article_ids": sorted(self.article_ids),
            "article_count": len(self.article_ids),
            "dates": sorted_dates,
            "first_seen": sorted_dates[0] if sorted_dates else None,
            "last_seen": sorted_dates[-1] if sorted_dates else None,
            "evidences": self.evidences,
            "review_flags": self.review_flags,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/postprocessed/article_extractions_clean.jsonl"),
        help="Cleaned extraction JSONL input.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/graph"),
        help="Output directory for aggregated graph artifacts.",
    )
    parser.add_argument(
        "--export-networkx",
        action="store_true",
        help="Also export a NetworkX node-link JSON artifact if networkx is installed.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    records = _load_jsonl(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    graph_payload = build_graph_payload(records)
    events_payload = build_events_payload(records, graph_payload["nodes"])
    graph_payload["metadata"]["event_count"] = events_payload["metadata"]["event_count"]
    graph_payload["metadata"]["event_type_counts"] = events_payload["metadata"][
        "event_type_counts"
    ]

    graph_path = args.output_dir / "graph.json"
    nodes_path = args.output_dir / "nodes.json"
    edges_path = args.output_dir / "edges.json"
    events_path = args.output_dir / "events.json"
    summary_path = args.output_dir / "summary.json"

    _write_json(graph_path, graph_payload)
    _write_json(nodes_path, graph_payload["nodes"])
    _write_json(edges_path, graph_payload["edges"])
    _write_json(events_path, events_payload)
    _write_json(summary_path, graph_payload["metadata"])

    networkx_path = None
    if args.export_networkx:
        networkx_path = _export_networkx_if_available(
            graph_payload,
            args.output_dir / "graph_networkx_node_link.json",
        )

    response = {
        "records": len(records),
        "nodes": len(graph_payload["nodes"]),
        "edges": len(graph_payload["edges"]),
        "events": len(events_payload["events"]),
        "graph_json": str(graph_path),
        "events_json": str(events_path),
        "summary_json": str(summary_path),
    }
    if networkx_path is not None:
        response["networkx_json"] = str(networkx_path)
    print(json.dumps(response))
    return 0


def build_graph_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    node_map: dict[str, NodeAggregate] = {}
    edge_map: dict[str, EdgeAggregate] = {}
    node_id_by_name: dict[str, str] = {}
    relation_type_counts = Counter()
    node_type_counts = Counter()
    all_dates: set[str] = set()
    skipped_relations = 0

    for record in records:
        article_id = record.get("article_id")
        published_at = _normalize_date(record.get("published_at"))
        title = record.get("title")
        source_publication = record.get("source")
        entity_records = record.get("entities", [])
        relation_records = record.get("relations", [])

        for entity in entity_records:
            node = _upsert_node(node_map, node_id_by_name, entity, article_id, published_at)
            if node is not None:
                node_type_counts[node.type] += 0  # keep keys stable once created

        for relation in relation_records:
            source_name = relation.get("source")
            target_name = relation.get("target")
            relation_type = relation.get("type")
            evidence = relation.get("evidence")
            if not all(isinstance(v, str) and v for v in (source_name, target_name, relation_type, evidence)):
                skipped_relations += 1
                continue
            source_id = node_id_by_name.get(source_name.casefold())
            target_id = node_id_by_name.get(target_name.casefold())
            if source_id is None or target_id is None:
                skipped_relations += 1
                continue

            edge_id = build_edge_id(source_id, target_id, relation_type)
            edge = edge_map.get(edge_id)
            if edge is None:
                edge = EdgeAggregate(
                    id=edge_id,
                    source=source_id,
                    target=target_id,
                    type=relation_type,
                )
                edge_map[edge_id] = edge

            if isinstance(article_id, str):
                edge.article_ids.add(article_id)
            if published_at is not None:
                edge.dates.add(published_at)
                all_dates.add(published_at)
            edge.evidences.append(
                {
                    "article_id": article_id,
                    "published_at": published_at,
                    "title": title,
                    "source_publication": source_publication,
                    "evidence": evidence,
                }
            )
            edge.review_flags = _merge_flags(edge.review_flags, relation.get("review_flags", []))
            node_map[source_id].relation_ids.add(edge_id)
            node_map[target_id].relation_ids.add(edge_id)
            relation_type_counts[relation_type] += 1

    nodes = sorted((node.to_dict() for node in node_map.values()), key=lambda item: item["id"])
    edges = sorted((edge.to_dict() for edge in edge_map.values()), key=lambda item: item["id"])
    for node in nodes:
        node_type_counts[node["type"]] += 1

    metadata = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_type_counts": dict(node_type_counts),
        "edge_type_counts": dict(relation_type_counts),
        "timeline": {
            "available_dates": sorted(all_dates),
            "min_date": min(all_dates) if all_dates else None,
            "max_date": max(all_dates) if all_dates else None,
        },
        "skipped_relations": skipped_relations,
    }
    return {"nodes": nodes, "edges": edges, "metadata": metadata}


def build_events_payload(
    records: list[dict[str, Any]],
    nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    node_by_name = {
        node.get("name", "").casefold(): node
        for node in (nodes or [])
        if isinstance(node.get("name"), str)
    }
    events: list[dict[str, Any]] = []
    event_type_counts = Counter()
    all_dates: set[str] = set()

    for record in records:
        article_id = record.get("article_id")
        article_date = _normalize_date(record.get("published_at"))
        title = record.get("title")
        source_publication = record.get("source")
        source_url = record.get("url") or record.get("source_url")
        model = record.get("model")
        prompt_version = record.get("prompt_version")

        for index, event in enumerate(record.get("events", [])):
            if not isinstance(event, dict):
                continue
            event_type = event.get("event_type")
            if not isinstance(event_type, str) or not event_type:
                continue

            event_date = _normalize_event_date(event.get("event_date")) or article_date
            if event_date:
                all_dates.add(event_date)
            event_type_counts[event_type] += 1

            location = event.get("location") if isinstance(event.get("location"), str) else ""
            location_node = node_by_name.get(location.casefold()) if location else None
            location_geocode = event.get("location_geocode", {})
            latitude = _pick_coordinate(None, location_geocode.get("latitude") if isinstance(location_geocode, dict) else None)
            longitude = _pick_coordinate(None, location_geocode.get("longitude") if isinstance(location_geocode, dict) else None)
            location_geocode_source = (
                location_geocode.get("geocode_source") if isinstance(location_geocode, dict) else None
            )
            location_geocode_display_name = (
                location_geocode.get("geocode_display_name") if isinstance(location_geocode, dict) else None
            )
            if latitude is None and location_node is not None:
                latitude = _pick_coordinate(None, location_node.get("latitude"))
            if longitude is None and location_node is not None:
                longitude = _pick_coordinate(None, location_node.get("longitude"))
            if location_geocode_source is None and location_node is not None:
                location_geocode_source = location_node.get("geocode_source")
            if location_geocode_display_name is None and location_node is not None:
                location_geocode_display_name = location_node.get("geocode_display_name")

            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                event_id = _build_fallback_event_id(article_id, index, event_type)

            events.append(
                {
                    "id": event_id,
                    "event_id": event_id,
                    "event_type": event_type,
                    "event_date": event_date,
                    "date_precision": event.get("date_precision"),
                    "location": location,
                    "location_node_id": location_node.get("id") if location_node else None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "location_geocode_source": location_geocode_source,
                    "location_geocode_display_name": location_geocode_display_name,
                    "participants": _enrich_event_participants(
                        event.get("participants", []),
                        node_by_name,
                    ),
                    "relations": _enrich_event_relations(
                        event.get("relations", []),
                        node_by_name,
                    ),
                    "summary": event.get("summary"),
                    "evidence": event.get("evidence"),
                    "confidence": event.get("confidence"),
                    "review_status": event.get("review_status"),
                    "review_flags": event.get("review_flags", []),
                    "validation_status": _event_validation_status(
                        event=event,
                        source_url=source_url,
                        latitude=latitude,
                        longitude=longitude,
                    ),
                    "article_id": article_id,
                    "published_at": article_date,
                    "title": title,
                    "source_publication": source_publication,
                    "source_url": source_url,
                    "model": model,
                    "prompt_version": prompt_version,
                }
            )

    events.sort(key=lambda item: (item.get("event_date") or "", item["id"]))
    metadata = {
        "event_count": len(events),
        "event_type_counts": dict(event_type_counts),
        "timeline": {
            "available_dates": sorted(all_dates),
            "min_date": min(all_dates) if all_dates else None,
            "max_date": max(all_dates) if all_dates else None,
        },
    }
    return {"events": events, "metadata": metadata}


def _upsert_node(
    node_map: dict[str, NodeAggregate],
    node_id_by_name: dict[str, str],
    entity: dict[str, Any],
    article_id: str | None,
    published_at: str | None,
) -> NodeAggregate | None:
    name = entity.get("name")
    entity_type = entity.get("type")
    if not isinstance(name, str) or not isinstance(entity_type, str):
        return None

    node_id = node_id_by_name.get(name.casefold())
    if node_id is None:
        node_id = build_node_id(name, entity_type)
        node_id_by_name[name.casefold()] = node_id
        node_map[node_id] = NodeAggregate(id=node_id, name=name, type=entity_type)

    node = node_map[node_id]
    aliases = entity.get("aliases", [])
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str) and alias and alias != node.name:
                node.aliases.add(alias)

    if isinstance(article_id, str):
        node.article_ids.add(article_id)
    if published_at is not None:
        node.first_seen = _min_date(node.first_seen, published_at)
        node.last_seen = _max_date(node.last_seen, published_at)

    node.latitude = _pick_coordinate(node.latitude, entity.get("latitude"))
    node.longitude = _pick_coordinate(node.longitude, entity.get("longitude"))
    if node.geocode_source is None and isinstance(entity.get("geocode_source"), str):
        node.geocode_source = entity.get("geocode_source")
    if node.geocode_display_name is None and isinstance(entity.get("geocode_display_name"), str):
        node.geocode_display_name = entity.get("geocode_display_name")
    node.review_flags = _merge_flags(node.review_flags, entity.get("review_flags", []))
    return node


def build_node_id(name: str, entity_type: str) -> str:
    return f"{entity_type}:{_slugify(name)}"


def build_edge_id(source_id: str, target_id: str, relation_type: str) -> str:
    return f"{source_id}|{relation_type}|{target_id}"


def _enrich_event_participants(
    participants: Any,
    node_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(participants, list):
        return []

    enriched: list[dict[str, Any]] = []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        name = participant.get("name")
        if not isinstance(name, str) or not name:
            continue
        node = node_by_name.get(name.casefold())
        enriched.append(
            {
                "name": name,
                "type": participant.get("type"),
                "role": participant.get("role"),
                "node_id": node.get("id") if node else None,
            }
        )
    return enriched


def _enrich_event_relations(
    relations: Any,
    node_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(relations, list):
        return []

    enriched: list[dict[str, Any]] = []
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source = relation.get("source")
        target = relation.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        source_node = node_by_name.get(source.casefold())
        target_node = node_by_name.get(target.casefold())
        enriched.append(
            {
                "source": source,
                "target": target,
                "source_id": source_node.get("id") if source_node else None,
                "target_id": target_node.get("id") if target_node else None,
                "type": relation.get("type"),
                "evidence": relation.get("evidence"),
            }
        )
    return enriched


def _event_validation_status(
    *,
    event: dict[str, Any],
    source_url: Any,
    latitude: float | None,
    longitude: float | None,
) -> str:
    if not event.get("evidence"):
        return "missing_evidence"
    if not isinstance(event.get("participants"), list) or not event["participants"]:
        return "missing_participants"
    if not isinstance(event.get("relations"), list) or not event["relations"]:
        return "missing_relations"
    if not source_url:
        return "missing_source_url"
    if event.get("location") and (latitude is None or longitude is None):
        return "missing_geocode"
    if event.get("review_flags"):
        return "needs_review"
    return "schema_validated"


def _build_fallback_event_id(article_id: Any, index: int, event_type: str) -> str:
    article_slug = _slugify(article_id if isinstance(article_id, str) else "article")
    return f"event:{article_slug}:{index + 1:03d}:{_slugify(event_type)}"


def _slugify(value: str) -> str:
    lowered = value.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered)
    return normalized.strip("-")


def _normalize_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _normalize_event_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    stripped = value.strip()
    if re.match(r"^\d{4}(-\d{2}){0,2}$", stripped):
        return stripped
    return _normalize_date(stripped)


def _min_date(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left <= right else right


def _max_date(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right


def _pick_coordinate(current: float | None, candidate: Any) -> float | None:
    if current is not None:
        return current
    if isinstance(candidate, (int, float)):
        return float(candidate)
    return None


def _merge_flags(
    existing: list[dict[str, str]],
    incoming: Any,
) -> list[dict[str, str]]:
    if not isinstance(incoming, list):
        return existing
    seen = {(flag.get("code"), flag.get("message")) for flag in existing if isinstance(flag, dict)}
    merged = list(existing)
    for flag in incoming:
        if not isinstance(flag, dict):
            continue
        code = flag.get("code")
        message = flag.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        merged.append({"code": code, "message": message})
    return merged


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _export_networkx_if_available(payload: dict[str, Any], path: Path) -> Path | None:
    try:
        import networkx as nx  # type: ignore
    except Exception:
        return None

    graph = nx.MultiDiGraph()
    for node in payload["nodes"]:
        node_id = node["id"]
        attrs = dict(node)
        attrs.pop("id", None)
        graph.add_node(node_id, **attrs)

    for edge in payload["edges"]:
        attrs = dict(edge)
        edge_id = attrs.pop("id")
        source = attrs.pop("source")
        target = attrs.pop("target")
        relation_type = attrs.get("type")
        graph.add_edge(source, target, key=edge_id, relation_type=relation_type, **attrs)

    data = nx.node_link_data(graph)
    _write_json(path, data)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
