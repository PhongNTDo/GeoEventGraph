# GeoEventGraph

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

*An open-source system that parses news articles into spatiotemporal event signals to build dynamic geospatial knowledge graphs.*

<div align="center">
  <img src="docs/img/GeoEventGraph.png" alt="GeoEventGraph Architecture and Pipeline" width="100%">
</div>


Event-driven geospatial knowledge graph pipeline for extracting, validating, aggregating, and visualizing geopolitical relationships from news corpora.

GeoEventGraph currently demonstrates the workflow on a curated BBC News topic corpus about Middle East conflict dynamics. The design is intentionally broader than this first dataset: new sources, ontologies, extraction models, geocoders, and visual analytics views can be added without changing the core pipeline shape.

The Python package and CLI modules are currently named `geokg`.

## What It Does

- Crawls BBC topic pages and saves article HTML into a local corpus.
- Normalizes saved BBC HTML into stable article-level JSONL.
- Uses an Ollama-compatible local LLM endpoint for ontology-constrained entity, event, and relation extraction.
- Canonicalizes entity names, applies geocode overrides, caches Nominatim lookups, and flags locations for review.
- Aggregates cleaned extractions into event artifacts and weighted temporal graph artifacts.
- Provides a React dashboard with map and topology views, timeline filtering, flagged-location filtering, and article evidence inspection.

## Repository Layout

```text
.
├── src/geokg/                  # Python pipeline modules and CLIs
├── tests/                      # Unit tests for parsing, extraction validation, post-processing, and graph aggregation
├── frontend/                   # Vite + React visualization app
├── samples/                    # Small synthetic sample records safe for public sharing
├── corpus/                     # Saved source HTML corpus for local experiments
├── data/
│   ├── normalized/             # Normalized article JSONL
│   ├── extractions/            # Raw LLM extraction JSONL and failures
│   ├── postprocessed/          # Cleaned extraction records and geocoding review artifacts
│   ├── graph/                  # Frontend-ready graph JSON artifacts
│   └── reference/              # Entity aliases, geocode overrides, and geocode cache
└── project_description.md      # Original project brief
```

## Pipeline

| Stage | CLI | Main outputs |
| --- | --- | --- |
| Crawl | `geokg.crawl_bbc_topic` | `corpus/*.html`, `corpus/crawl_manifest.jsonl`, `corpus/crawl_summary.json` |
| Normalize | `geokg.ingest_corpus` | `data/normalized/articles.jsonl`, `data/normalized/summary.json` |
| Extract | `geokg.extract_relations` | `data/extractions/article_extractions.jsonl`, `data/extractions/failures.jsonl` |
| Post-process + geocode | `geokg.postprocess_extractions` | `data/postprocessed/article_extractions_clean.jsonl`, `data/postprocessed/events_clean.jsonl`, `data/postprocessed/geocoded_locations.jsonl`, `data/postprocessed/location_review.csv` |
| Aggregate graph | `geokg.aggregate_graph` | `data/graph/graph.json`, `data/graph/events.json`, `data/graph/nodes.json`, `data/graph/edges.json`, `data/graph/summary.json` |
| Visualize | `frontend/` | Local Vite dashboard or production build |

## Current Ontology

Allowed entity types:

- `NationState`
- `NonStateActor`
- `PoliticalLeader`
- `StrategicLocation`
- `MilitaryAsset`

Allowed relation types:

- `ATTACKED`
- `THREATENED`
- `NEGOTIATED_WITH`
- `SUPPORTED`
- `SANCTIONED`
- `BLOCKADED`

Allowed event types:

- `AttackEvent`
- `ThreatEvent`
- `NegotiationEvent`
- `SupportEvent`
- `SanctionEvent`
- `BlockadeEvent`

## Quick Start

### Prerequisites

- Python 3.11 or newer.
- Node.js and npm for the frontend.
- An Ollama-compatible chat endpoint for LLM extraction.
- Optional: `networkx` if you want the additional NetworkX node-link export.

### Install Python Package

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

If you do not use an editable install, prefix Python commands with `PYTHONPATH=src`.

### Run Tests

```bash
python3 -m unittest discover -s tests
```

Or from a source checkout without installing the package:

```bash
make test
```

### Phase 1 Evaluation Scaffold

Generate draft annotation candidates from the current event-v1 predictions:

```bash
make eval-candidates EVAL_LIMIT=10
```

This writes `data/eval/annotation_candidates.jsonl`. Copy selected rows into
`data/gold/event_mentions.gold.jsonl`, manually correct them, and set each
row's `annotation_status` to `gold`.

For model-assisted annotation, generate per-article packets that include the
source article text and candidate row:

```bash
make eval-packets
```

Then ask the configured OpenAI model to draft final-format annotation rows:

```bash
make eval-model-drafts OPENAI_API_KEY_FILE=OpenAI_key.txt OPENAI_ANNOTATION_MODEL=gpt-5.4
```

Review and edit the per-article JSON files in `data/eval/model_review/`. When a
row is correct, set `annotation_status` to `gold`, then combine reviewed rows:

```bash
make eval-gold-from-reviewed
```

Then score current predictions against the curated gold file:

```bash
make eval
```

The report is written to `data/eval/report.json` and `data/eval/report.md`.
Append a compact accuracy snapshot to the tracked evaluation history with:

```bash
make eval-log EVAL_RUN_LABEL="event-v1 baseline" EVAL_RUN_NOTES="10 reviewed gold articles"
```

Or run scoring and logging together:

```bash
make eval-and-log EVAL_RUN_LABEL="event-v1 baseline"
```

Generate detailed error-analysis files after scoring:

```bash
make eval-error-analysis
```

This writes `data/eval/error_analysis.md` plus CSVs under
`data/eval/errors/` for article summaries, entity errors, relation errors,
event errors, participant errors, event-relation errors, and geocoding errors.

See `data/gold/README.md` and `docs/ANNOTATION_GUIDELINES.md` for annotation
details.

### Phase 1 Extraction Experiments

Use the experiment targets when testing a new extraction method against only the
curated gold articles. This keeps the run small enough for iteration and makes
the result directly comparable in `EVALUATION_LOG.md`.

The current best extractor remains the `event-v1` baseline artifacts under
`data/extractions_event_v1/` and `data/postprocessed_event_v1/`. The recommended
next experiment is the hybrid extractor documented in
`docs/HYBRID_EXTRACTION.md`. It uses the event-v1 output as candidate events,
then runs one verifier/repair pass per event and rebuilds event relations
deterministically after participants are stable.

Run extraction on the LeanBabel server:

```bash
make eval-extract-gold-hybrid-leanbabel \
  OLLAMA_MODEL=gpt-oss:120b \
  EVAL_EXPERIMENT_NAME=event-v2-hybrid
```

`eval-extract-gold-hybrid-leanbabel` starts a local Ollama server before
extraction. Use `eval-extract-gold-hybrid` only when Ollama is already running
and reachable at `OLLAMA_BASE_URL`. The default candidate file is
`data/extractions_event_v1/article_extractions.jsonl`; override
`HYBRID_CANDIDATES` to test a different one-shot candidate source.

This writes raw outputs under `data/eval/event-v2-hybrid/extractions/`. If
extraction runs on a different machine, bring that experiment directory back to
this checkout before scoring.

Then postprocess, score, generate error analysis, and append the compact result
to `EVALUATION_LOG.md`:

```bash
make eval-experiment-from-extractions \
  EVAL_EXPERIMENT_NAME=event-v2-hybrid \
  EVAL_EXPERIMENT_LOG_LABEL="event-v2-hybrid LeanBabel" \
  EVAL_EXPERIMENT_LOG_NOTES="event-v1 candidates with per-event verifier and deterministic relation repair"
```

The main generated files are:

- `data/eval/event-v2-hybrid/report.json`
- `data/eval/event-v2-hybrid/report.md`
- `data/eval/event-v2-hybrid/error_analysis.md`
- `data/eval/event-v2-hybrid/errors/*.csv`

For manual case-by-case review of gold vs hybrid events, build review packets:

```bash
make eval-case-review-experiment EVAL_EXPERIMENT_NAME=event-v2-hybrid
```

This writes `data/eval/event-v2-hybrid/case_review/index.md`,
per-article Markdown files under `case_review/articles/`, a structured
`case_review.json`, and an editable `case_review.csv` with blank
`review_decision` and `review_notes` columns.

After reviewing the workbook version of the case table, apply the decisions and
rescore against the adjudicated gold file:

```bash
make eval-reviewed-experiment \
  EVAL_EXPERIMENT_NAME=event-v2-hybrid
```

This syncs `case_review.xlsx` back to `case_review.csv`, writes
`data/gold/event_mentions.hybrid_reviewed.gold.jsonl`, writes
`reviewed_report.json` / `reviewed_report.md`, and appends the reviewed result
to `EVALUATION_LOG.md`.

If the same machine can run both extraction and evaluation, use the combined
target:

```bash
make eval-hybrid-experiment EVAL_EXPERIMENT_NAME=event-v2-hybrid
```

The older staged experiment target is still available for reference, but it is
not the recommended next direction as-is.

## Makefile Shortcuts

Common workflow commands are available through `make`:

```bash
make help
make install
make test
make crawl
make normalize
make extract
make postprocess-offline
make graph
make eval-candidates
make eval
make eval-extract-gold
make eval-extract-gold-leanbabel
make eval-extract-gold-hybrid
make eval-extract-gold-hybrid-leanbabel
make eval-extract-gold-staged
make eval-extract-gold-staged-leanbabel
make eval-experiment-from-extractions
make eval-case-review-experiment
make frontend-build
```

Useful variables can be overridden at runtime:

```bash
make crawl SINCE=2026-02-01 UNTIL=2026-04-15
make extract OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=gpt-oss:120b
make eval-extract-gold-hybrid EVAL_EXPERIMENT_NAME=event-v2-hybrid OLLAMA_MODEL=gpt-oss:120b
make eval-extract-gold-hybrid-leanbabel EVAL_EXPERIMENT_NAME=event-v2-hybrid OLLAMA_MODEL=gpt-oss:120b
make postprocess-live GEOCODE_USER_AGENT="GeoEventGraph/0.1 (contact@example.com)"
```

## Run The Pipeline

### 1. Crawl BBC Topic Articles

```bash
python3 -m geokg.crawl_bbc_topic \
  --topic-url https://www.bbc.co.uk/news/topics/cjnwl8q4ggwt \
  --output-dir corpus \
  --since 2026-02-01 \
  --until 2026-04-15
```

The crawler reads BBC topic-page initial data, paginates through `?page=N`, keeps regular `/news/articles/...` items, and skips video/live items.

### 2. Normalize Saved HTML

```bash
python3 -m geokg.ingest_corpus \
  --input-dir corpus \
  --output-dir data/normalized
```

Later stages should consume `data/normalized/articles.jsonl` instead of reading raw HTML directly.

### 3. Extract Entities, Events, And Relations

Start an Ollama-compatible server first, then run:

```bash
export GEOKG_OLLAMA_BASE_URL=http://127.0.0.1:11434
export GEOKG_OLLAMA_MODEL=gpt-oss:120b

python3 -m geokg.extract_relations \
  --input data/normalized/articles.jsonl \
  --output-dir data/extractions \
  --resume
```

You can also pass `--base-url`, `--model`, `--limit`, `--timeout-seconds`, `--temperature`, and `--num-ctx` directly.

Extraction is event-centric in the current schema. The model returns direct `events`, and each event keeps inner compatibility `relations`; the top-level `relations` array remains for the existing graph pipeline and older tooling.

If you have older extraction outputs without `events`, rerun extraction into a fresh output directory or disable resume so existing article IDs are not skipped.

For the LeanBabel server, the direct runner defaults to `gpt-oss:120b`:

```bash
bash run_extract_leanbabel_direct.sh --gpus 2 --model gpt-oss:120b
```

If the installed Ollama tag differs, pass the exact model name shown by `ollama list`.

### 4. Post-Process And Geocode

For reproducible cache/override-only geocoding:

```bash
python3 -m geokg.postprocess_extractions \
  --input data/extractions/article_extractions.jsonl \
  --output-dir data/postprocessed \
  --offline-geocoding
```

For live Nominatim geocoding, use a descriptive user agent and conservative request pacing:

```bash
python3 -m geokg.postprocess_extractions \
  --input data/extractions/article_extractions.jsonl \
  --output-dir data/postprocessed \
  --geocode-user-agent "GeoEventGraph/0.1 (contact@example.com)" \
  --geocode-delay-seconds 1.5 \
  --geocode-max-retries 3
```

Review `data/postprocessed/location_review.csv` before treating the graph as spatially final.

`postprocess_extractions` also writes `data/postprocessed/geocode_review.csv`
for manual event-coordinate review. It has these columns:

```text
location_name,article_id,event_summary,source_url,current_latitude,current_longitude,suggested_latitude,suggested_longitude
```

Leave `suggested_latitude` and `suggested_longitude` blank until you manually
review a location. When those values are present, downstream graph/event
artifacts prefer them over the current geocoder coordinates.

`postprocess_extractions` also reads `data/normalized/articles.jsonl` by default to backfill article URLs into event provenance. Use `--article-metadata <path>` if your normalized article metadata lives elsewhere.

### 5. Aggregate Graph Artifacts

```bash
python3 -m geokg.aggregate_graph \
  --input data/postprocessed/article_extractions_clean.jsonl \
  --output-dir data/graph
```

To also export a NetworkX node-link JSON file:

```bash
python3 -m geokg.aggregate_graph \
  --input data/postprocessed/article_extractions_clean.jsonl \
  --output-dir data/graph \
  --export-networkx
```

### 6. Run Frontend

The frontend imports `data/graph/graph.json` at build time, so rebuild or restart it after regenerating graph artifacts.

```bash
cd frontend
npm install
npm run dev
```

Production build:

```bash
cd frontend
npm run build
```

## Sample Data

The `samples/` directory contains synthetic records for:

- normalized article JSONL
- extracted entity/relation JSONL
- event-centric extraction records
- frontend-style event JSON
- frontend-style graph JSON

These files are documentation and onboarding fixtures, not factual data or model-evaluation benchmarks.


## License

This project is released under the MIT License. See `LICENSE`.
