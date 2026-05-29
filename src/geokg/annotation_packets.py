"""Create model-assisted gold annotation packets and drafts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_ARTICLES = Path("data/normalized/articles.jsonl")
DEFAULT_CANDIDATES = Path("data/eval/annotation_candidates.jsonl")
DEFAULT_PACKET_DIR = Path("data/eval/annotation_packets")
DEFAULT_REVIEW_DIR = Path("data/eval/model_review")
DEFAULT_MODEL_JSONL = Path("data/eval/model_review/event_mentions.model_reviewed.jsonl")
DEFAULT_GOLD = Path("data/gold/event_mentions.gold.jsonl")
DEFAULT_API_KEY_FILE = Path("OpenAI_key.txt")
DEFAULT_MODEL = "gpt-5.4"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ENTITY_TYPES = [
    "NationState",
    "NonStateActor",
    "PoliticalLeader",
    "StrategicLocation",
    "MilitaryAsset",
]
RELATION_TYPES = [
    "ATTACKED",
    "THREATENED",
    "NEGOTIATED_WITH",
    "SUPPORTED",
    "SANCTIONED",
    "BLOCKADED",
]
EVENT_TYPES = [
    "AttackEvent",
    "ThreatEvent",
    "NegotiationEvent",
    "SupportEvent",
    "SanctionEvent",
    "BlockadeEvent",
]
DATE_PRECISIONS = ["day", "month", "year", "article_date", "unknown"]
PARTICIPANT_ROLES = [
    "initiator",
    "target",
    "mediator",
    "supporter",
    "sanctioning_actor",
    "affected_location",
    "military_asset",
    "participant",
]


DEVELOPER_INSTRUCTIONS = """You are preparing evaluation gold annotations for GeoKG.

Return exactly one JSON object that follows the supplied schema.

Goal:
- Correct the draft candidate using the original article text.
- Output the final GeoKG article-level annotation row in the same format.

Rules:
- Extract only geopolitical facts explicitly supported by the article text.
- Keep only entities, relations, and events relevant to the GeoKG ontology.
- Remove candidate items that are wrong, unsupported, duplicated, or too vague.
- Add important missing entities, relations, and events.
- Evidence fields must be exact short quotes copied from the article text.
- Do not invent facts, actors, dates, places, or relations.
- If the article reports a claim, keep the event grounded as a reported/claimed event in the summary.
- Use article published date only when the article does not state a clearer event date.
- Use an empty string for location when no concrete event location is stated.
- Set annotation_status to "model_reviewed". A human will later change it to "gold" after checking.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    packets = subparsers.add_parser(
        "build-packets",
        help="Build per-article annotation packets from candidates and source text.",
    )
    packets.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    packets.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    packets.add_argument("--output-dir", type=Path, default=DEFAULT_PACKET_DIR)
    packets.set_defaults(func=_run_build_packets)

    model = subparsers.add_parser(
        "model-review",
        help="Send packets to OpenAI and write model-reviewed annotation drafts.",
    )
    model.add_argument("--packet-dir", type=Path, default=DEFAULT_PACKET_DIR)
    model.add_argument("--review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    model.add_argument("--jsonl-output", type=Path, default=DEFAULT_MODEL_JSONL)
    model.add_argument("--api-key-file", type=Path, default=DEFAULT_API_KEY_FILE)
    model.add_argument("--model", default=DEFAULT_MODEL)
    model.add_argument("--limit", type=int, default=None)
    model.add_argument("--overwrite", action="store_true")
    model.add_argument("--delay-seconds", type=float, default=0.5)
    model.add_argument("--timeout-seconds", type=float, default=240.0)
    model.set_defaults(func=_run_model_review)

    finalize = subparsers.add_parser(
        "finalize-gold",
        help="Combine reviewed per-article JSON files into the gold JSONL file.",
    )
    finalize.add_argument("--review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    finalize.add_argument("--output", type=Path, default=DEFAULT_GOLD)
    finalize.add_argument(
        "--promote-model-reviewed",
        action="store_true",
        help="Treat model_reviewed rows as gold while combining. Prefer manual review first.",
    )
    finalize.set_defaults(func=_run_finalize_gold)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


def build_annotation_packets(
    *,
    candidate_rows: list[dict[str, Any]],
    article_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    article_by_id = {
        article.get("article_id"): article
        for article in article_rows
        if isinstance(article.get("article_id"), str)
    }
    packets: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        article_id = candidate.get("article_id")
        if not isinstance(article_id, str):
            continue
        article = article_by_id.get(article_id, {})
        packets.append(
            {
                "article_id": article_id,
                "title": candidate.get("title") or article.get("title"),
                "source": candidate.get("source") or article.get("source"),
                "source_url": candidate.get("source_url")
                or candidate.get("url")
                or article.get("url"),
                "published_at": candidate.get("published_at") or article.get("published_at"),
                "annotation_goal": (
                    "Correct the draft candidate into one final-format model_reviewed "
                    "annotation row. Human review will later promote it to gold."
                ),
                "allowed_entity_types": ENTITY_TYPES,
                "allowed_relation_types": RELATION_TYPES,
                "allowed_event_types": EVENT_TYPES,
                "allowed_participant_roles": PARTICIPANT_ROLES,
                "article": {
                    "article_id": article_id,
                    "title": article.get("title") or candidate.get("title"),
                    "source": article.get("source") or candidate.get("source"),
                    "published_at": article.get("published_at") or candidate.get("published_at"),
                    "url": article.get("url") or candidate.get("source_url"),
                    "text": article.get("text", ""),
                },
                "draft_candidate": candidate,
                "output_schema_hint": gold_row_schema(),
            }
        )
    return packets


def write_packets(packets: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for packet in packets:
        article_id = packet["article_id"]
        (output_dir / f"{article_id}.packet.json").write_text(
            json.dumps(packet, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{article_id}.packet.md").write_text(
            packet_to_markdown(packet),
            encoding="utf-8",
        )


def packet_to_markdown(packet: dict[str, Any]) -> str:
    return (
        f"# Annotation Packet: {packet['article_id']}\n\n"
        f"Title: {packet.get('title')}\n\n"
        f"Source URL: {packet.get('source_url')}\n\n"
        "## Instructions\n\n"
        f"{DEVELOPER_INSTRUCTIONS}\n\n"
        "## Article Text\n\n"
        f"{packet['article'].get('text', '')}\n\n"
        "## Draft Candidate\n\n"
        "```json\n"
        f"{json.dumps(packet['draft_candidate'], indent=2, ensure_ascii=False)}\n"
        "```\n"
    )


def model_review_packets(
    *,
    packet_dir: Path,
    review_dir: Path,
    jsonl_output: Path,
    api_key_file: Path,
    model: str,
    limit: int | None,
    overwrite: bool,
    delay_seconds: float,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    api_key = _read_api_key(api_key_file)
    review_dir.mkdir(parents=True, exist_ok=True)
    packet_paths = sorted(packet_dir.glob("*.packet.json"))
    if limit is not None:
        packet_paths = packet_paths[:limit]

    rows: list[dict[str, Any]] = []
    for index, packet_path in enumerate(packet_paths, start=1):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        article_id = packet["article_id"]
        reviewed_path = review_dir / f"{article_id}.json"
        if reviewed_path.exists() and not overwrite:
            row = json.loads(reviewed_path.read_text(encoding="utf-8"))
            rows.append(row)
            continue

        row = call_openai_annotation(
            packet=packet,
            api_key=api_key,
            model=_normalize_model_name(model),
            timeout_seconds=timeout_seconds,
        )
        row["annotation_status"] = "model_reviewed"
        reviewed_path.write_text(
            json.dumps(row, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (review_dir / f"{article_id}.review.md").write_text(
            review_markdown(row),
            encoding="utf-8",
        )
        rows.append(row)
        if index < len(packet_paths) and delay_seconds > 0:
            time.sleep(delay_seconds)

    _write_jsonl(jsonl_output, rows)
    return rows


def call_openai_annotation(
    *,
    packet: dict[str, Any],
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "developer",
                "content": DEVELOPER_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": json.dumps(packet, ensure_ascii=False),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "geokg_gold_annotation",
                "description": "One GeoKG article-level model-reviewed gold annotation draft.",
                "strict": True,
                "schema": gold_row_schema(),
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        OPENAI_RESPONSES_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc

    text = _extract_response_text(response_payload)
    try:
        row = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI response was not valid JSON: {text[:500]}") from exc
    if not isinstance(row, dict):
        raise RuntimeError("OpenAI response JSON must be an object.")
    return row


def finalize_gold(
    *,
    review_dir: Path,
    output: Path,
    promote_model_reviewed: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(review_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        status = row.get("annotation_status")
        if status == "gold":
            rows.append(row)
            continue
        if promote_model_reviewed and status == "model_reviewed":
            copied = dict(row)
            copied["annotation_status"] = "gold"
            notes = list(copied.get("annotation_notes", []))
            notes.append("Promoted from model_reviewed by finalize-gold --promote-model-reviewed.")
            copied["annotation_notes"] = notes
            rows.append(copied)
    if not rows:
        raise SystemExit(
            f"No gold rows found in {review_dir}. Review per-article JSON files, set "
            "annotation_status to 'gold', then rerun this command."
        )
    _write_jsonl(output, rows)
    return rows


def review_markdown(row: dict[str, Any]) -> str:
    article_id = row.get("article_id", "unknown")
    return (
        f"# Review: {article_id}\n\n"
        "Human checklist:\n\n"
        "- Verify every event is explicitly supported by the article.\n"
        "- Verify every evidence field is an exact quote.\n"
        "- Remove wrong or weak events.\n"
        "- Add missing major events if needed.\n"
        "- Correct entity types, roles, dates, and locations.\n"
        "- When satisfied, edit the paired `.json` file and set "
        '`annotation_status` to `"gold"`.\n\n'
        "Editable JSON file:\n\n"
        f"`data/eval/model_review/{article_id}.json`\n\n"
        "Current model-reviewed draft:\n\n"
        "```json\n"
        f"{json.dumps(row, indent=2, ensure_ascii=False)}\n"
        "```\n"
    )


def gold_row_schema() -> dict[str, Any]:
    entity_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ENTITY_TYPES},
            "aliases": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "type", "aliases"],
    }
    relation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string"},
            "target": {"type": "string"},
            "type": {"type": "string", "enum": RELATION_TYPES},
            "evidence": {"type": "string"},
        },
        "required": ["source", "target", "type", "evidence"],
    }
    participant_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ENTITY_TYPES},
            "role": {"type": "string", "enum": PARTICIPANT_ROLES},
        },
        "required": ["name", "type", "role"],
    }
    geocode_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "latitude": {"type": ["number", "null"]},
            "longitude": {"type": ["number", "null"]},
            "geocode_source": {"type": "string"},
            "geocode_display_name": {"type": "string"},
        },
        "required": [
            "latitude",
            "longitude",
            "geocode_source",
            "geocode_display_name",
        ],
    }
    event_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_type": {"type": "string", "enum": EVENT_TYPES},
            "event_date": {"type": "string"},
            "date_precision": {"type": "string", "enum": DATE_PRECISIONS},
            "location": {"type": "string"},
            "participants": {"type": "array", "items": participant_schema},
            "relations": {"type": "array", "items": relation_schema},
            "summary": {"type": "string"},
            "evidence": {"type": "string"},
            "confidence": {"type": ["number", "null"]},
            "location_geocode": geocode_schema,
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
            "location_geocode",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "article_id": {"type": "string"},
            "title": {"type": "string"},
            "source": {"type": "string"},
            "source_url": {"type": "string"},
            "published_at": {"type": "string"},
            "annotation_status": {"type": "string", "enum": ["model_reviewed"]},
            "annotation_notes": {"type": "array", "items": {"type": "string"}},
            "entities": {"type": "array", "items": entity_schema},
            "relations": {"type": "array", "items": relation_schema},
            "events": {"type": "array", "items": event_schema},
        },
        "required": [
            "article_id",
            "title",
            "source",
            "source_url",
            "published_at",
            "annotation_status",
            "annotation_notes",
            "entities",
            "relations",
            "events",
        ],
    }


def _run_build_packets(args: argparse.Namespace) -> None:
    candidate_rows = _load_jsonl(args.candidates)
    article_rows = _load_jsonl(args.articles)
    packets = build_annotation_packets(candidate_rows=candidate_rows, article_rows=article_rows)
    write_packets(packets, args.output_dir)
    print(json.dumps({"packet_count": len(packets), "output_dir": str(args.output_dir)}))


def _run_model_review(args: argparse.Namespace) -> None:
    rows = model_review_packets(
        packet_dir=args.packet_dir,
        review_dir=args.review_dir,
        jsonl_output=args.jsonl_output,
        api_key_file=args.api_key_file,
        model=args.model,
        limit=args.limit,
        overwrite=args.overwrite,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "model_reviewed_count": len(rows),
                "review_dir": str(args.review_dir),
                "jsonl_output": str(args.jsonl_output),
                "next_step": "Review each data/eval/model_review/*.json file and set annotation_status to gold.",
            }
        )
    )


def _run_finalize_gold(args: argparse.Namespace) -> None:
    rows = finalize_gold(
        review_dir=args.review_dir,
        output=args.output,
        promote_model_reviewed=args.promote_model_reviewed,
    )
    print(json.dumps({"gold_count": len(rows), "output": str(args.output)}))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
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


def _read_api_key(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"OpenAI API key file not found: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"OpenAI API key file is empty: {path}")
    return key


def _normalize_model_name(value: str) -> str:
    stripped = value.strip()
    if stripped.lower() == "gpt 5.4":
        return "gpt-5.4"
    return stripped


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "\n".join(parts)
    raise RuntimeError("OpenAI response did not contain output text.")


if __name__ == "__main__":
    raise SystemExit(main())
