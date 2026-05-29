PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
NPM ?= npm
PYTHONPATH ?= src

TOPIC_URL ?= https://www.bbc.co.uk/news/topics/cjnwl8q4ggwt
SINCE ?= 2026-02-01
UNTIL ?= 2026-04-15

OLLAMA_BASE_URL ?= http://127.0.0.1:11434
OLLAMA_MODEL ?= gpt-oss:120b
EXTRACT_ARGS ?= --resume

GEOCODE_USER_AGENT ?= GeoEventGraph/0.1
GEOCODE_DELAY_SECONDS ?= 1.5
GEOCODE_MAX_RETRIES ?= 3

EVAL_PREDICTIONS ?= data/postprocessed_event_v1/article_extractions_clean.jsonl
EVAL_FAILURES ?= data/extractions_event_v1/failures.jsonl
EVAL_GOLD ?= data/gold/event_mentions.gold.jsonl
EVAL_CANDIDATES ?= data/eval/annotation_candidates.jsonl
EVAL_REPORT ?= data/eval/report.json
EVAL_MARKDOWN_REPORT ?= data/eval/report.md
EVAL_LIMIT ?= 10
EVAL_ARTICLES ?= data/normalized/articles.jsonl
EVAL_PACKET_DIR ?= data/eval/annotation_packets
EVAL_REVIEW_DIR ?= data/eval/model_review
EVAL_MODEL_JSONL ?= data/eval/model_review/event_mentions.model_reviewed.jsonl
EVAL_LOG ?= EVALUATION_LOG.md
EVAL_RUN_LABEL ?= baseline
EVAL_RUN_NOTES ?=
OPENAI_API_KEY_FILE ?= OpenAI_key.txt
OPENAI_ANNOTATION_MODEL ?= gpt-5.4

.PHONY: help install test crawl normalize extract postprocess-offline postprocess-live graph graph-networkx eval-candidates eval-packets eval-model-drafts eval-gold-from-reviewed eval eval-log eval-and-log frontend-install frontend-dev frontend-build pipeline-from-extractions

help:
	@printf '%s\n' 'GeoEventGraph workflow targets:'
	@printf '%s\n' '  make install                 Install Python package in editable mode'
	@printf '%s\n' '  make test                    Run Python unit tests'
	@printf '%s\n' '  make crawl                   Crawl BBC topic HTML into corpus/'
	@printf '%s\n' '  make normalize               Normalize corpus HTML into data/normalized/'
	@printf '%s\n' '  make extract                 Run Ollama-based extraction'
	@printf '%s\n' '  make postprocess-offline     Clean and geocode using cache/overrides only'
	@printf '%s\n' '  make postprocess-live        Clean and geocode with live Nominatim lookups'
	@printf '%s\n' '  make graph                   Build frontend graph artifacts'
	@printf '%s\n' '  make graph-networkx          Build graph artifacts plus NetworkX export'
	@printf '%s\n' '  make eval-candidates         Generate draft gold annotation candidates'
	@printf '%s\n' '  make eval-packets            Build per-article model annotation packets'
	@printf '%s\n' '  make eval-model-drafts       Ask OpenAI model to draft final-format annotations'
	@printf '%s\n' '  make eval-gold-from-reviewed Combine human-reviewed model drafts into gold JSONL'
	@printf '%s\n' '  make eval                    Score predictions against curated gold data'
	@printf '%s\n' '  make eval-log                Append data/eval/report.json to EVALUATION_LOG.md'
	@printf '%s\n' '  make eval-and-log            Run eval, then append the result to the log'
	@printf '%s\n' '  make frontend-install        Install frontend dependencies'
	@printf '%s\n' '  make frontend-dev            Start Vite dev server'
	@printf '%s\n' '  make frontend-build          Build frontend'
	@printf '%s\n' '  make pipeline-from-extractions  Run postprocess-offline and graph'

install:
	$(PIP) install -e .

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

crawl:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.crawl_bbc_topic \
		--topic-url $(TOPIC_URL) \
		--output-dir corpus \
		--since $(SINCE) \
		--until $(UNTIL)

normalize:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.ingest_corpus \
		--input-dir corpus \
		--output-dir data/normalized

extract:
	GEOKG_OLLAMA_BASE_URL=$(OLLAMA_BASE_URL) \
	GEOKG_OLLAMA_MODEL=$(OLLAMA_MODEL) \
	PYTHONPATH=$(PYTHONPATH) \
	$(PYTHON) -m geokg.extract_relations \
		--input data/normalized/articles.jsonl \
		--output-dir data/extractions \
		--base-url $(OLLAMA_BASE_URL) \
		--model $(OLLAMA_MODEL) \
		$(EXTRACT_ARGS)

postprocess-offline:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.postprocess_extractions \
		--input data/extractions/article_extractions.jsonl \
		--output-dir data/postprocessed \
		--offline-geocoding

postprocess-live:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.postprocess_extractions \
		--input data/extractions/article_extractions.jsonl \
		--output-dir data/postprocessed \
		--geocode-user-agent "$(GEOCODE_USER_AGENT)" \
		--geocode-delay-seconds $(GEOCODE_DELAY_SECONDS) \
		--geocode-max-retries $(GEOCODE_MAX_RETRIES)

graph:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.aggregate_graph \
		--input data/postprocessed/article_extractions_clean.jsonl \
		--output-dir data/graph

graph-networkx:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.aggregate_graph \
		--input data/postprocessed/article_extractions_clean.jsonl \
		--output-dir data/graph \
		--export-networkx

eval-candidates:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.evaluate generate-candidates \
		--predictions $(EVAL_PREDICTIONS) \
		--failures $(EVAL_FAILURES) \
		--output $(EVAL_CANDIDATES) \
		--limit $(EVAL_LIMIT)

eval-packets:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.annotation_packets build-packets \
		--candidates $(EVAL_CANDIDATES) \
		--articles $(EVAL_ARTICLES) \
		--output-dir $(EVAL_PACKET_DIR)

eval-model-drafts:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.annotation_packets model-review \
		--packet-dir $(EVAL_PACKET_DIR) \
		--review-dir $(EVAL_REVIEW_DIR) \
		--jsonl-output $(EVAL_MODEL_JSONL) \
		--api-key-file $(OPENAI_API_KEY_FILE) \
		--model "$(OPENAI_ANNOTATION_MODEL)"

eval-gold-from-reviewed:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.annotation_packets finalize-gold \
		--review-dir $(EVAL_REVIEW_DIR) \
		--output $(EVAL_GOLD)

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.evaluate score \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_PREDICTIONS) \
		--output $(EVAL_REPORT) \
		--markdown-output $(EVAL_MARKDOWN_REPORT)

eval-log:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.eval_log \
		--report $(EVAL_REPORT) \
		--log $(EVAL_LOG) \
		--label "$(EVAL_RUN_LABEL)" \
		--notes "$(EVAL_RUN_NOTES)"

eval-and-log: eval eval-log

frontend-install:
	cd frontend && $(NPM) install

frontend-dev:
	cd frontend && $(NPM) run dev

frontend-build:
	cd frontend && $(NPM) run build

pipeline-from-extractions: postprocess-offline graph
