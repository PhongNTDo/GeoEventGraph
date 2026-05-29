"""Append evaluation report summaries to a tracked Markdown log."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_REPORT = Path("data/eval/report.json")
DEFAULT_LOG = Path("EVALUATION_LOG.md")

HEADER = """# GeoKG Evaluation Log

This tracked log records compact summaries from `data/eval/report.json`.
The full JSON and Markdown reports under `data/eval/` are generated artifacts,
while this file is intended to preserve comparable accuracy snapshots over time.

Run:

```bash
make eval
make eval-log EVAL_RUN_LABEL="short label" EVAL_RUN_NOTES="what changed"
```

| Timestamp UTC | Label | Gold Articles | Gold Events | Pred Events | Entity F1 | Relation F1 | Event Exact F1 | Event Soft F1 | Participant F1 | Event Relation F1 | Event Type Acc | Date Acc | Evidence Exact | Evidence Fuzzy | Geocode Rate | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--notes", default="")
    parser.add_argument("--timestamp", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    timestamp = args.timestamp or datetime.now(tz=UTC).isoformat(timespec="seconds")
    row = build_log_row(
        report=report,
        timestamp=timestamp,
        label=args.label,
        notes=args.notes,
    )
    append_log_row(args.log, row)
    print(json.dumps({"log": str(args.log), "label": args.label, "timestamp": timestamp}))
    return 0


def build_log_row(
    *,
    report: dict[str, Any],
    timestamp: str,
    label: str,
    notes: str,
) -> str:
    metrics = report["metrics"]
    matched_fields = metrics["matched_event_fields"]
    geocoding = metrics["geocoding"]
    values = [
        timestamp,
        label,
        report["gold"]["article_count"],
        report["gold"]["event_count"],
        report["predictions"]["event_count_in_scope"],
        _metric_f1(metrics["entities"]),
        _metric_f1(metrics["relations"]),
        _metric_f1(metrics["events_exact"]),
        _metric_f1(metrics["events_soft"]),
        _metric_f1(metrics["participants"]),
        _metric_f1(metrics["event_relations"]),
        _format_rate(matched_fields.get("event_type_accuracy")),
        _format_rate(matched_fields.get("event_date_accuracy")),
        _format_rate(matched_fields.get("evidence_exact_match_rate")),
        _format_rate(matched_fields.get("evidence_fuzzy_match_rate")),
        _format_rate(geocoding.get("located_event_coordinate_rate")),
        notes,
    ]
    return "| " + " | ".join(_escape_cell(value) for value in values) + " |\n"


def append_log_row(path: Path, row: str) -> None:
    if not path.exists():
        path.write_text(HEADER + row, encoding="utf-8")
        return

    content = path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content + row, encoding="utf-8")


def _metric_f1(block: dict[str, Any]) -> str:
    metric = block["micro"] if "micro" in block else block
    return _format_rate(metric.get("f1"))


def _format_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:.3f}"


def _escape_cell(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
