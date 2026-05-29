# GeoKG Evaluation Log

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
| 2026-05-29T23:15:33+00:00 | event-v1 baseline | 10 | 74 | 65 | 0.899 | 0.828 | 0.216 | 0.849 | 0.476 | 0.585 | 0.983 | 0.864 | 0.407 | 0.831 | 0.324 | 10 reviewed gold articles |
