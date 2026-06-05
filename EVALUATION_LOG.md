# GeoKG Evaluation Log

This tracked log records compact summaries from `data/eval/report.json`.
The full JSON and Markdown reports under `data/eval/` are generated artifacts,
while this file is intended to preserve comparable accuracy snapshots over time.

Run:

```bash
make eval
make eval-log EVAL_RUN_LABEL="short label" EVAL_RUN_NOTES="what changed"
make eval-experiment-from-extractions EVAL_EXPERIMENT_LOG_LABEL="experiment label"
make eval-staged-experiment EVAL_EXPERIMENT_LOG_LABEL="staged experiment"
```

| Timestamp UTC | Label | Gold Articles | Gold Events | Pred Events | Entity F1 | Relation F1 | Event Exact F1 | Event Soft F1 | Participant F1 | Event Relation F1 | Event Type Acc | Date Acc | Evidence Exact | Evidence Fuzzy | Geocode Rate | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-05-29T23:15:33+00:00 | event-v1 baseline | 10 | 74 | 65 | 0.899 | 0.828 | 0.216 | 0.849 | 0.476 | 0.585 | 0.983 | 0.864 | 0.407 | 0.831 | 0.324 | 10 reviewed gold articles |
| 2026-06-04T23:07:28+00:00 | event-v1.1 LeanBabel | 10 | 74 | 52 | 0.646 | 0.507 | 0.112 | 0.730 | 0.298 | 0.307 | 1.000 | 0.913 | 0.283 | 0.826 | 0.381 | role templates and core participants; 1 extraction failure |
| 2026-06-04T23:47:07+00:00 | event-v1.2 LeanBabel | 10 | 74 | 62 | 0.767 | 0.585 | 0.206 | 0.779 | 0.359 | 0.353 | 0.981 | 0.868 | 0.151 | 0.642 | 0.323 | relaxed participant guidance and partial evidence salvage |
| 2026-06-05T12:53:07+00:00 | event-v2-staged LeanBabel | 10 | 74 | 54 | 0.489 | 0.373 | 0.047 | 0.484 | 0.082 | 0.092 | 0.968 | 0.581 | 0.065 | 0.516 | 0.109 | evidence-first staged extraction with deterministic relations |
| 2026-06-05T13:18:46+00:00 | event-v2-hybrid LeanBabel | 10 | 74 | 57 | 0.872 | 0.721 | 0.198 | 0.779 | 0.330 | 0.263 | 1.000 | 0.824 | 0.392 | 0.843 | 0.250 | event-v1 candidates with per-event verifier and deterministic relation repair |
