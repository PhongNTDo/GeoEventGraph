"""CLI for LLM-based entity, event, and relation extraction using Ollama."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from geokg.extraction import (
    SYSTEM_PROMPT,
    attach_extraction_metadata,
    build_extraction_prompt,
    build_repair_prompt,
    extraction_json_schema,
    normalize_model_json,
    validate_extraction_payload,
)
from geokg.ollama_client import OllamaClient, OllamaError


DEFAULT_BASE_URL = os.environ.get("GEOKG_OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("GEOKG_OLLAMA_MODEL", "gpt-oss:120b")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/normalized/articles.jsonl"),
        help="Normalized article JSONL input.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/extractions"),
        help="Output directory for extraction artifacts.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Ollama base URL, for example http://leanbabel:11434",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Ollama model name.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of articles to process.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip article IDs already present in the output JSONL.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries after invalid JSON or schema validation failures.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="HTTP timeout for each Ollama request.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for extraction.",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=16384,
        help="Context window requested from Ollama.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    articles = list(_load_jsonl(args.input))
    if args.limit is not None:
        articles = articles[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "article_extractions.jsonl"
    failures_path = args.output_dir / "failures.jsonl"

    seen_article_ids = _existing_ids(output_path) if args.resume else set()
    client = OllamaClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds)

    processed = 0
    succeeded = 0
    failed = 0

    with output_path.open("a", encoding="utf-8") as output_handle, failures_path.open(
        "a", encoding="utf-8"
    ) as failure_handle:
        for article in articles:
            article_id = article["article_id"]
            if article_id in seen_article_ids:
                continue

            processed += 1
            try:
                extraction = _extract_single_article(
                    client=client,
                    article=article,
                    model=args.model,
                    max_retries=args.max_retries,
                    temperature=args.temperature,
                    num_ctx=args.num_ctx,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failure_handle.write(
                    json.dumps(
                        {
                            "article_id": article_id,
                            "title": article.get("title"),
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                continue

            output_handle.write(json.dumps(extraction, ensure_ascii=False) + "\n")
            succeeded += 1

    print(
        json.dumps(
            {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "output": str(output_path),
                "failures": str(failures_path),
            }
        )
    )
    return 0


def _extract_single_article(
    *,
    client: OllamaClient,
    article: dict[str, Any],
    model: str,
    max_retries: int,
    temperature: float,
    num_ctx: int,
) -> dict[str, Any]:
    prompt = build_extraction_prompt(article)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    schema = extraction_json_schema()
    options = {"temperature": temperature, "num_ctx": num_ctx}

    last_error = "Unknown extraction failure."
    for _attempt in range(max_retries + 1):
        response = client.chat(
            model=model,
            messages=messages,
            response_format=schema,
            options=options,
        )
        raw_content = response["message"]["content"]
        try:
            payload = normalize_model_json(raw_content)
        except json.JSONDecodeError as exc:
            last_error = f"Model returned invalid JSON: {exc}"
            messages.extend(
                [
                    {"role": "assistant", "content": raw_content},
                    {"role": "user", "content": build_repair_prompt([last_error])},
                ]
            )
            continue

        validation = validate_extraction_payload(payload, article)
        if validation.ok:
            return attach_extraction_metadata(article, validation.normalized, model)

        last_error = "; ".join(validation.errors)
        messages.extend(
            [
                {"role": "assistant", "content": raw_content},
                {"role": "user", "content": build_repair_prompt(validation.errors)},
            ]
        )

    raise OllamaError(last_error)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for row in _load_jsonl(path):
        article_id = row.get("article_id")
        if isinstance(article_id, str):
            ids.add(article_id)
    return ids


if __name__ == "__main__":
    raise SystemExit(main())
