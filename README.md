# GeoEventGraph

Event-driven geospatial knowledge graph pipeline for extracting, validating, aggregating, and visualizing geopolitical relationships from news corpora.

GeoEventGraph currently demonstrates the workflow on a curated BBC News topic corpus about Middle East conflict dynamics. The design is intentionally broader than this first dataset: new sources, ontologies, extraction models, geocoders, and visual analytics views can be added without changing the core pipeline shape.

The Python package and CLI modules are currently named `geokg`.

## What It Does

- Crawls BBC topic pages and saves article HTML into a local corpus.
- Normalizes saved BBC HTML into stable article-level JSONL.
- Uses an Ollama-compatible local LLM endpoint for ontology-constrained entity and relation extraction.
- Canonicalizes entity names, applies geocode overrides, caches Nominatim lookups, and flags locations for review.
- Aggregates cleaned extractions into weighted temporal graph artifacts.
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
| Post-process + geocode | `geokg.postprocess_extractions` | `data/postprocessed/article_extractions_clean.jsonl`, `data/postprocessed/geocoded_locations.jsonl`, `data/postprocessed/location_review.csv` |
| Aggregate graph | `geokg.aggregate_graph` | `data/graph/graph.json`, `data/graph/nodes.json`, `data/graph/edges.json`, `data/graph/summary.json` |
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
make frontend-build
```

Useful variables can be overridden at runtime:

```bash
make crawl SINCE=2026-02-01 UNTIL=2026-04-15
make extract OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=gpt-oss-120b
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

### 3. Extract Entities And Relations

Start an Ollama-compatible server first, then run:

```bash
export GEOKG_OLLAMA_BASE_URL=http://127.0.0.1:11434
export GEOKG_OLLAMA_MODEL=gpt-oss-120b

python3 -m geokg.extract_relations \
  --input data/normalized/articles.jsonl \
  --output-dir data/extractions \
  --resume
```

You can also pass `--base-url`, `--model`, `--limit`, `--timeout-seconds`, `--temperature`, and `--num-ctx` directly.

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

## LeanBabel Notes

For the LeanBabel environment, use the direct runner as the main entry point:

```bash
bash run_extract_leanbabel_direct.sh --gpus 2 --model gpt-oss-120b
```

Notes:

- Do not point your local machine at `http://leanbabel:11434`.
- The intended pattern is to start Ollama locally on the LeanBabel server at `127.0.0.1:<port>`.
- The runner uses `OLLAMA_HOST`, `OLLAMA_MODELS`, and `ollama list` in the same style as existing LeanBabel Ollama workflows.
- If the installed model tag differs from `gpt-oss-120b`, set `OLLAMA_MODEL_OVERRIDE` to the exact name shown by `ollama list`.

## Data And Publishing Notes

- The public repository should not publish raw BBC HTML from `corpus/`.
- The public repository should publish the small synthetic examples in `samples/` so new users can understand the schemas without needing the private/local corpus.
- `data/reference/entity_aliases.csv` and `data/reference/geocode_overrides.csv` should be versioned because they capture project logic.
- `data/reference/geocode_cache.json` should stay local by default because it is a third-party lookup cache, not source code.
- Generated artifacts under `data/normalized/`, `data/extractions/`, `data/postprocessed/`, `data/graph/`, and `frontend/dist/` should stay out of Git by default. Regenerate them locally with the pipeline or publish a curated release artifact later.
- Runtime logs such as `logs_runner/`, local virtual environments, and local model files should stay out of Git.
- The included `.gitignore` implements this policy for an initial GitHub push.

## Sample Data

The `samples/` directory contains synthetic records for:

- normalized article JSONL
- extracted entity/relation JSONL
- frontend-style graph JSON

These files are documentation and onboarding fixtures, not factual data or model-evaluation benchmarks.

## Development Roadmap

1. Generalize source ingestion with a small adapter interface for BBC, RSS, CSV/JSONL imports, and future non-news corpora.
2. Add extraction evaluation: a gold sample, precision/recall metrics, model comparisons, prompt versioning, and regression tests for ontology compliance.
3. Improve geospatial validation with Wikidata/GeoNames fallback, coordinate confidence, uncertainty radius, and a small manual review UI.
4. Evolve the schema from entity-relation triples toward event records with participants, roles, time spans, locations, evidence, and confidence.
5. Serve graph data through a backend API so the frontend can filter by date, source, entity type, relation type, and confidence without rebuilding.
6. Add stronger provenance views: source article drill-down, evidence search, relation-level confidence, and exportable graph slices.
7. Add CI tests, sample-backed documentation, and optional Docker/devcontainer setup for reproducible onboarding.
8. Prepare an academic evaluation track covering LLM relation extraction quality, geocoding error types, and temporal graph analysis.

## License

This project is released under the MIT License. See `LICENSE`.
