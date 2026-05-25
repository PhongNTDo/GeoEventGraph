"""Crawl BBC topic pages and save article HTML into corpus/."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from geokg.bbc_html import BBCParseError, load_bbc_initial_data


DEFAULT_TOPIC_URL = "https://www.bbc.co.uk/news/topics/cjnwl8q4ggwt"
DEFAULT_SINCE = date(2026, 2, 1)
ARTICLE_PATH_PATTERN = re.compile(r"^/news/articles/[a-z0-9]+/?$")


@dataclass(slots=True)
class TopicPromo:
    headline: str
    url: str
    type: str | None
    published_at: str | None
    page_number: int
    article_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic-url",
        default=DEFAULT_TOPIC_URL,
        help="BBC topic page URL to crawl.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("corpus"),
        help="Directory where article HTML files will be saved.",
    )
    parser.add_argument(
        "--since",
        type=parse_cli_date,
        default=DEFAULT_SINCE,
        help="Inclusive start date in YYYY-MM-DD format. Default: 2026-02-01.",
    )
    parser.add_argument(
        "--until",
        type=parse_cli_date,
        default=date.today(),
        help="Inclusive end date in YYYY-MM-DD format. Default: today.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay between HTTP requests.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional hard cap on the number of listing pages to scan.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download article HTML even if the target file already exists.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print page-level crawl progress.",
    )
    return parser


def parse_cli_date(value: str) -> date:
    return date.fromisoformat(value)


def fetch_html(url: str, *, timeout_seconds: float) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; GeoKGCrawler/0.1; "
                "+https://www.bbc.co.uk/news/topics/cjnwl8q4ggwt)"
            )
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def build_topic_page_url(topic_url: str, page_number: int) -> str:
    split = urlsplit(topic_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    if page_number <= 1:
        query.pop("page", None)
    else:
        query["page"] = str(page_number)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query),
            split.fragment,
        )
    )


def parse_topic_page(
    html: str,
    *,
    base_url: str = "https://www.bbc.co.uk",
) -> tuple[list[TopicPromo], dict[str, Any]]:
    initial_data = load_bbc_initial_data(html)
    data = initial_data.get("data", {})

    for key, payload in data.items():
        if not key.startswith("simple-promo-grid?") or not isinstance(payload, dict):
            continue
        page_data = payload.get("data", {})
        page_info = page_data.get("page", {})
        page_number = int(page_info.get("index", 1))
        promos: list[TopicPromo] = []
        for item in page_data.get("promos", []):
            relative_url = item.get("url")
            if not relative_url:
                continue
            article_id = extract_article_id(relative_url)
            promos.append(
                TopicPromo(
                    headline=item.get("headline") or item.get("contentTitle") or "",
                    url=urljoin(base_url, relative_url),
                    type=item.get("type"),
                    published_at=item.get("lastPublished"),
                    page_number=page_number,
                    article_id=article_id,
                )
            )
        return promos, page_info

    raise BBCParseError("Missing topic promo grid in BBC initial data")


def extract_article_id(url: str) -> str | None:
    match = re.search(r"/news/articles/([a-z0-9]+)/?$", url)
    return match.group(1) if match else None


def is_regular_article_promo(promo: TopicPromo) -> bool:
    path = urlsplit(promo.url).path
    if promo.type != "article":
        return False
    if not ARTICLE_PATH_PATTERN.match(path):
        return False
    return True


def parse_bbc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_output_filename(promo: TopicPromo) -> str:
    article_id = promo.article_id or "unknown-article"
    published = parse_bbc_datetime(promo.published_at)
    prefix = published.date().isoformat() if published else "undated"
    return f"{prefix}__{article_id}.html"


def crawl_topic(
    topic_url: str,
    *,
    output_dir: Path,
    since: date,
    until: date,
    delay_seconds: float,
    timeout_seconds: float,
    overwrite: bool,
    max_pages: int | None,
    verbose: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "crawl_manifest.jsonl"
    summary_path = output_dir / "crawl_summary.json"
    manifest_path.write_text("", encoding="utf-8")

    seen_urls: set[str] = set()
    downloaded = 0
    skipped_existing = 0
    skipped_non_article = 0
    skipped_out_of_range = 0
    failures: list[dict[str, str]] = []

    page_number = 1
    total_pages: int | None = None

    while True:
        if max_pages is not None and page_number > max_pages:
            break
        if total_pages is not None and page_number > total_pages:
            break

        listing_url = build_topic_page_url(topic_url, page_number)
        try:
            listing_html = fetch_html(listing_url, timeout_seconds=timeout_seconds)
            promos, page_info = parse_topic_page(listing_html, base_url=topic_url)
        except Exception as exc:  # pragma: no cover - network errors are environment-specific
            failures.append({"url": listing_url, "error": str(exc)})
            break

        total_pages = int(page_info.get("total", page_number))
        if verbose:
            print(f"Scanning page {page_number}/{total_pages}: {listing_url}")
        dated_promos = [parse_bbc_datetime(promo.published_at) for promo in promos]
        dated_promos = [value for value in dated_promos if value is not None]

        with manifest_path.open("a", encoding="utf-8") as manifest_handle:
            for promo in promos:
                if promo.url in seen_urls:
                    continue
                seen_urls.add(promo.url)

                if not is_regular_article_promo(promo):
                    skipped_non_article += 1
                    continue

                published = parse_bbc_datetime(promo.published_at)
                if published is None:
                    skipped_out_of_range += 1
                    continue
                published_date = published.date()
                if published_date < since or published_date > until:
                    skipped_out_of_range += 1
                    continue

                filename = build_output_filename(promo)
                destination = output_dir / filename
                record = promo.to_dict()
                record["filename"] = filename

                if destination.exists() and not overwrite:
                    skipped_existing += 1
                    record["status"] = "exists"
                    manifest_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    continue

                try:
                    article_html = fetch_html(promo.url, timeout_seconds=timeout_seconds)
                    destination.write_text(article_html, encoding="utf-8")
                except Exception as exc:  # pragma: no cover - network errors are environment-specific
                    failures.append({"url": promo.url, "error": str(exc)})
                    record["status"] = "failed"
                    manifest_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    continue

                downloaded += 1
                record["status"] = "downloaded"
                manifest_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                manifest_handle.flush()
                if verbose:
                    print(f"  downloaded {filename}")
                time.sleep(delay_seconds)

        if dated_promos:
            newest_on_page = max(dated_promos).date()
            if newest_on_page < since:
                break
        page_number += 1
        time.sleep(delay_seconds)

    summary = {
        "topic_url": topic_url,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "downloaded_count": downloaded,
        "skipped_existing_count": skipped_existing,
        "skipped_non_article_count": skipped_non_article,
        "skipped_out_of_range_count": skipped_out_of_range,
        "failure_count": len(failures),
        "failures": failures,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    args = build_parser().parse_args()
    if args.until < args.since:
        raise SystemExit("--until must be on or after --since")

    summary = crawl_topic(
        args.topic_url,
        output_dir=args.output_dir,
        since=args.since,
        until=args.until,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        overwrite=args.overwrite,
        max_pages=args.max_pages,
        verbose=args.verbose,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
