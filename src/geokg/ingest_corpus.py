"""CLI for normalizing saved article HTML into JSONL."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from geokg.bbc_html import BBCParseError, parse_bbc_html_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("corpus"),
        help="Directory containing saved HTML files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/normalized"),
        help="Directory for normalized JSONL output.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    html_files = sorted(input_dir.glob("*.html"))
    if not html_files:
        raise SystemExit(f"No HTML files found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    articles_path = output_dir / "articles.jsonl"
    summary_path = output_dir / "summary.json"

    articles = []
    failures: list[dict[str, str]] = []
    sections = Counter()
    languages = Counter()

    for html_file in html_files:
        try:
            article = parse_bbc_html_file(html_file)
        except BBCParseError as exc:
            failures.append({"filename": html_file.name, "error": str(exc)})
            continue

        articles.append(article)
        if article.section:
            sections[article.section] += 1
        if article.language:
            languages[article.language] += 1

    with articles_path.open("w", encoding="utf-8") as handle:
        for article in articles:
            handle.write(json.dumps(article.to_dict(), ensure_ascii=False))
            handle.write("\n")

    summary = {
        "input_dir": str(input_dir),
        "output_articles": str(articles_path),
        "article_count": len(articles),
        "failure_count": len(failures),
        "sections": dict(sections),
        "languages": dict(languages),
        "failures": failures,
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "article_count": len(articles),
                "failure_count": len(failures),
                "output": str(articles_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
