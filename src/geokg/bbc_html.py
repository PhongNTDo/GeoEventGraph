"""BBC HTML parsing helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any


INITIAL_DATA_PATTERN = re.compile(
    r'window\.__INITIAL_DATA__="(?P<data>.*?)";</script>',
    re.DOTALL,
)
JSON_LD_PATTERN = re.compile(
    r'<script[^>]+type="application/ld\+json">(?P<data>.*?)</script>',
    re.DOTALL,
)


class BBCParseError(RuntimeError):
    """Raised when a BBC HTML export cannot be parsed."""


@dataclass(slots=True)
class NormalizedArticle:
    article_id: str
    source: str
    source_type: str
    title: str
    published_at: str | None
    updated_at: str | None
    url: str | None
    description: str | None
    authors: list[str]
    section: str | None
    language: str | None
    filename: str
    text: str
    paragraphs: list[str]
    word_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_bbc_html_file(path: Path) -> NormalizedArticle:
    html = path.read_text(encoding="utf-8")
    initial_data = load_bbc_initial_data(html)
    json_ld = _load_json_ld(html)
    article_payload = _find_article_payload(initial_data)
    metadata = article_payload["data"]["metadata"]
    content = article_payload["data"]["content"]

    paragraphs = _extract_paragraphs(content)
    if not paragraphs:
        raise BBCParseError(f"No article paragraphs found in {path.name}")

    title = (
        metadata.get("seoHeadline")
        or json_ld.get("headline")
        or _fallback_title_from_filename(path.name)
    )
    published_at = _isoformat_ms(metadata.get("firstPublished")) or json_ld.get(
        "datePublished"
    )
    updated_at = _isoformat_ms(metadata.get("lastUpdated")) or json_ld.get(
        "dateModified"
    )
    url = metadata.get("locators", {}).get("canonicalUrl") or json_ld.get("url")
    description = metadata.get("description") or json_ld.get("description")
    authors = _extract_authors(json_ld)
    section = metadata.get("section", {}).get("name")
    language = metadata.get("languageCode") or html_language(html)
    article_id = _extract_article_id(url, metadata.get("urn"), path.stem)
    text = "\n\n".join(paragraphs)

    return NormalizedArticle(
        article_id=article_id,
        source="BBC News",
        source_type="html",
        title=title,
        published_at=published_at,
        updated_at=updated_at,
        url=url,
        description=description,
        authors=authors,
        section=section,
        language=language,
        filename=path.name,
        text=text,
        paragraphs=paragraphs,
        word_count=len(text.split()),
    )


def html_language(html: str) -> str | None:
    match = re.search(r'<html[^>]+lang="([^"]+)"', html)
    return match.group(1) if match else None


def load_bbc_initial_data(html: str) -> dict[str, Any]:
    match = INITIAL_DATA_PATTERN.search(html)
    if not match:
        raise BBCParseError("Missing BBC initial data script")

    raw_data = match.group("data")
    decoded = json.loads(f'"{raw_data}"')
    return json.loads(decoded)


def _load_json_ld(html: str) -> dict[str, Any]:
    match = JSON_LD_PATTERN.search(html)
    if not match:
        return {}

    try:
        return json.loads(unescape(match.group("data")))
    except json.JSONDecodeError:
        return {}


def _find_article_payload(initial_data: dict[str, Any]) -> dict[str, Any]:
    data = initial_data.get("data", {})
    for key, payload in data.items():
        if key.startswith("article?") and isinstance(payload, dict):
            return payload
    raise BBCParseError("Missing article payload in BBC initial data")


def _extract_paragraphs(content: dict[str, Any]) -> list[str]:
    blocks = content.get("model", {}).get("blocks", [])
    collected: list[tuple[tuple[str, ...], str]] = []

    def walk(node: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "paragraph":
                text = _clean_text(node.get("model", {}).get("text", ""))
                if text:
                    collected.append((path + (node_type,), text))
            model = node.get("model")
            if isinstance(model, dict):
                for value in model.values():
                    walk(value, path + ((node_type,) if node_type else ()))
            elif isinstance(model, list):
                for value in model:
                    walk(value, path + ((node_type,) if node_type else ()))
        elif isinstance(node, list):
            for value in node:
                walk(value, path)

    walk(blocks)

    paragraphs: list[str] = []
    for block_path, text in collected:
        if "headline" in block_path:
            continue
        if "altText" in block_path:
            continue
        if "image" in block_path:
            continue
        if "uploaderEmbed" in block_path:
            continue
        if _looks_like_boilerplate(text):
            continue
        paragraphs.append(text)

    return _dedupe_preserve_order(paragraphs)


def _extract_authors(json_ld: dict[str, Any]) -> list[str]:
    author_value = json_ld.get("author", [])
    if isinstance(author_value, dict):
        author_value = [author_value]

    authors: list[str] = []
    for item in author_value:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                authors.append(name)
    return authors


def _extract_article_id(url: str | None, urn: str | None, fallback: str) -> str:
    if url:
        match = re.search(r"/([a-z0-9]+)$", url)
        if match:
            return match.group(1)
    if urn:
        return urn.rsplit(":", 1)[-1]
    return _slugify(fallback)


def _isoformat_ms(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()


def _fallback_title_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return stem.rsplit(" - BBC News", 1)[0].replace("_", "?")


def _clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _looks_like_boilerplate(text: str) -> bool:
    boilerplate_prefixes = (
        "Follow the twists and turns of",
        "You can also get in touch",
        "Sign up for",
    )
    boilerplate_exact = {
        "Do you have any views, comments or questions about this story?",
    }
    return text in boilerplate_exact or text.startswith(boilerplate_prefixes)


def _slugify(value: str) -> str:
    lowered = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered)
    return normalized.strip("-")
