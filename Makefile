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
EVAL_ERROR_ANALYSIS ?= data/eval/error_analysis.md
EVAL_ERROR_DIR ?= data/eval/errors
EVAL_LIMIT ?= 10
EVAL_EXPERIMENT_NAME ?= event-v2-hybrid
EVAL_EXPERIMENT_DIR ?= data/eval/$(EVAL_EXPERIMENT_NAME)
EVAL_EXTRACT_OUTPUT_DIR ?= $(EVAL_EXPERIMENT_DIR)/extractions
EVAL_POSTPROCESSED_DIR ?= $(EVAL_EXPERIMENT_DIR)/postprocessed
EVAL_EXPERIMENT_REPORT ?= $(EVAL_EXPERIMENT_DIR)/report.json
EVAL_EXPERIMENT_MARKDOWN_REPORT ?= $(EVAL_EXPERIMENT_DIR)/report.md
EVAL_EXPERIMENT_ERROR_ANALYSIS ?= $(EVAL_EXPERIMENT_DIR)/error_analysis.md
EVAL_EXPERIMENT_ERROR_DIR ?= $(EVAL_EXPERIMENT_DIR)/errors
EVAL_CASE_REVIEW_DIR ?= $(EVAL_EXPERIMENT_DIR)/case_review
EVAL_CASE_REVIEW_XLSX ?= $(EVAL_CASE_REVIEW_DIR)/case_review.xlsx
EVAL_REVIEWED_GOLD ?= data/gold/event_mentions.hybrid_reviewed.gold.jsonl
EVAL_REVIEWED_REPORT ?= $(EVAL_EXPERIMENT_DIR)/reviewed_report.json
EVAL_REVIEWED_MARKDOWN_REPORT ?= $(EVAL_EXPERIMENT_DIR)/reviewed_report.md
EVAL_REVIEWED_ERROR_ANALYSIS ?= $(EVAL_EXPERIMENT_DIR)/reviewed_error_analysis.md
EVAL_REVIEWED_ERROR_DIR ?= $(EVAL_EXPERIMENT_DIR)/reviewed_errors
EVAL_REVIEWED_LOG_LABEL ?= $(EVAL_EXPERIMENT_NAME) reviewed gold
EVAL_REVIEWED_LOG_NOTES ?= adjudicated from $(EVAL_CASE_REVIEW_XLSX); both_correct matched rows use hybrid event; merge_needed keeps gold unless manually merged
EVAL_EXPERIMENT_LOG_LABEL ?= $(EVAL_EXPERIMENT_NAME)
EVAL_EXPERIMENT_LOG_NOTES ?= hybrid event-v1 candidates with per-event verifier and deterministic relation repair
EVAL_ARTICLES ?= data/normalized/articles.jsonl
HYBRID_CANDIDATES ?= data/extractions_event_v1/article_extractions.jsonl
HYBRID_EXTRACT_ARGS ?=
EVAL_PACKET_DIR ?= data/eval/annotation_packets
EVAL_REVIEW_DIR ?= data/eval/model_review
EVAL_MODEL_JSONL ?= data/eval/model_review/event_mentions.model_reviewed.jsonl
EVAL_LOG ?= EVALUATION_LOG.md
EVAL_RUN_LABEL ?= baseline
EVAL_RUN_NOTES ?=
OPENAI_API_KEY_FILE ?= OpenAI_key.txt
OPENAI_ANNOTATION_MODEL ?= gpt-5.4
LEANBABEL_PYTHON ?= /dcs/large/u5728153/envs/promptgraph_vllm/bin/python3.11
LEANBABEL_GPUS ?= 2
LEANBABEL_OLLAMA_PORT ?= 11434
LEANBABEL_DIRECT_ARGS ?=
STAGED_EXTRACT_ARGS ?=

.PHONY: help install test crawl normalize extract postprocess-offline postprocess-live graph graph-networkx eval-candidates eval-packets eval-model-drafts eval-gold-from-reviewed eval-extract-gold eval-extract-gold-leanbabel eval-extract-gold-hybrid eval-extract-gold-hybrid-leanbabel eval-extract-gold-staged eval-extract-gold-staged-leanbabel eval-postprocess-experiment eval-score-experiment eval-error-analysis-experiment eval-case-review-experiment eval-apply-case-review eval-score-reviewed-experiment eval-error-analysis-reviewed-experiment eval-log-reviewed-experiment eval-reviewed-experiment eval-log-experiment eval-experiment-from-extractions eval-experiment eval-hybrid-experiment eval-staged-experiment eval eval-error-analysis eval-log eval-and-log frontend-install frontend-dev frontend-build pipeline-from-extractions

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
	@printf '%s\n' '  make eval-extract-gold       Extract only curated gold-set articles'
	@printf '%s\n' '  make eval-extract-gold-leanbabel  Start Ollama on LeanBabel and extract gold-set articles'
	@printf '%s\n' '  make eval-extract-gold-hybrid  Run hybrid event-v1 candidate repair on curated gold-set articles'
	@printf '%s\n' '  make eval-extract-gold-hybrid-leanbabel  Start Ollama on LeanBabel and run hybrid gold extraction'
	@printf '%s\n' '  make eval-extract-gold-staged  Run staged extraction on curated gold-set articles'
	@printf '%s\n' '  make eval-extract-gold-staged-leanbabel  Start Ollama on LeanBabel and run staged gold extraction'
	@printf '%s\n' '  make eval-experiment-from-extractions  Postprocess, score, analyze, and log experiment outputs'
	@printf '%s\n' '  make eval-case-review-experiment  Build manual gold-vs-experiment review packets'
	@printf '%s\n' '  make eval-reviewed-experiment  Apply reviewed case workbook, rescore, analyze, and log'
	@printf '%s\n' '  make eval-experiment         Extract gold articles, then postprocess, score, analyze, and log'
	@printf '%s\n' '  make eval-hybrid-experiment  Run hybrid gold extraction, then postprocess, score, analyze, and log'
	@printf '%s\n' '  make eval-staged-experiment  Run staged gold extraction, then postprocess, score, analyze, and log'
	@printf '%s\n' '  make eval                    Score predictions against curated gold data'
	@printf '%s\n' '  make eval-error-analysis     Generate detailed eval error analysis Markdown and CSVs'
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

eval-extract-gold:
	GEOKG_OLLAMA_BASE_URL=$(OLLAMA_BASE_URL) \
	GEOKG_OLLAMA_MODEL=$(OLLAMA_MODEL) \
	PYTHONPATH=$(PYTHONPATH) \
	$(PYTHON) -m geokg.extract_relations \
		--input $(EVAL_ARTICLES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--base-url $(OLLAMA_BASE_URL) \
		--model $(OLLAMA_MODEL) \
		--article-ids-file $(EVAL_GOLD) \
		$(EXTRACT_ARGS)

eval-extract-gold-leanbabel:
	PYTHON_BIN_OVERRIDE=$(LEANBABEL_PYTHON) \
	bash run_extract_leanbabel_direct.sh \
		--input $(EVAL_ARTICLES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--model $(OLLAMA_MODEL) \
		--ollama-port $(LEANBABEL_OLLAMA_PORT) \
		--gpus $(LEANBABEL_GPUS) \
		--article-ids-file $(EVAL_GOLD) $(LEANBABEL_DIRECT_ARGS)

eval-extract-gold-hybrid:
	GEOKG_OLLAMA_BASE_URL=$(OLLAMA_BASE_URL) \
	GEOKG_OLLAMA_MODEL=$(OLLAMA_MODEL) \
	PYTHONPATH=$(PYTHONPATH) \
	$(PYTHON) -m geokg.hybrid_extraction \
		--input $(HYBRID_CANDIDATES) \
		--articles $(EVAL_ARTICLES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--base-url $(OLLAMA_BASE_URL) \
		--model $(OLLAMA_MODEL) \
		--article-ids-file $(EVAL_GOLD) \
		$(EXTRACT_ARGS) \
		$(HYBRID_EXTRACT_ARGS)

eval-extract-gold-hybrid-leanbabel:
	PYTHON_BIN_OVERRIDE=$(LEANBABEL_PYTHON) \
	bash run_extract_leanbabel_direct.sh \
		--module geokg.hybrid_extraction \
		--input $(HYBRID_CANDIDATES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--model $(OLLAMA_MODEL) \
		--ollama-port $(LEANBABEL_OLLAMA_PORT) \
		--gpus $(LEANBABEL_GPUS) \
		--article-ids-file $(EVAL_GOLD) $(LEANBABEL_DIRECT_ARGS)

eval-extract-gold-staged:
	GEOKG_OLLAMA_BASE_URL=$(OLLAMA_BASE_URL) \
	GEOKG_OLLAMA_MODEL=$(OLLAMA_MODEL) \
	PYTHONPATH=$(PYTHONPATH) \
	$(PYTHON) -m geokg.staged_extraction \
		--input $(EVAL_ARTICLES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--base-url $(OLLAMA_BASE_URL) \
		--model $(OLLAMA_MODEL) \
		--article-ids-file $(EVAL_GOLD) \
		$(EXTRACT_ARGS) \
		$(STAGED_EXTRACT_ARGS)

eval-extract-gold-staged-leanbabel:
	PYTHON_BIN_OVERRIDE=$(LEANBABEL_PYTHON) \
	bash run_extract_leanbabel_direct.sh \
		--module geokg.staged_extraction \
		--input $(EVAL_ARTICLES) \
		--output-dir $(EVAL_EXTRACT_OUTPUT_DIR) \
		--model $(OLLAMA_MODEL) \
		--ollama-port $(LEANBABEL_OLLAMA_PORT) \
		--gpus $(LEANBABEL_GPUS) \
		--article-ids-file $(EVAL_GOLD) $(LEANBABEL_DIRECT_ARGS)

eval-postprocess-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.postprocess_extractions \
		--input $(EVAL_EXTRACT_OUTPUT_DIR)/article_extractions.jsonl \
		--article-metadata $(EVAL_ARTICLES) \
		--output-dir $(EVAL_POSTPROCESSED_DIR) \
		--offline-geocoding

eval-score-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.evaluate score \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--output $(EVAL_EXPERIMENT_REPORT) \
		--markdown-output $(EVAL_EXPERIMENT_MARKDOWN_REPORT)

eval-error-analysis-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.error_analysis \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--report $(EVAL_EXPERIMENT_REPORT) \
		--output $(EVAL_EXPERIMENT_ERROR_ANALYSIS) \
		--error-dir $(EVAL_EXPERIMENT_ERROR_DIR)

eval-case-review-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.case_review \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--articles $(EVAL_ARTICLES) \
		--report $(EVAL_EXPERIMENT_REPORT) \
		--output-dir $(EVAL_CASE_REVIEW_DIR)

eval-apply-case-review:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.adjudicate_case_review \
		--review-xlsx $(EVAL_CASE_REVIEW_XLSX) \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--output-gold $(EVAL_REVIEWED_GOLD) \
		--synced-csv $(EVAL_CASE_REVIEW_DIR)/case_review.csv \
		--summary-output $(EVAL_CASE_REVIEW_DIR)/adjudication_summary.json

eval-score-reviewed-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.evaluate score \
		--gold $(EVAL_REVIEWED_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--output $(EVAL_REVIEWED_REPORT) \
		--markdown-output $(EVAL_REVIEWED_MARKDOWN_REPORT)

eval-error-analysis-reviewed-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.error_analysis \
		--gold $(EVAL_REVIEWED_GOLD) \
		--predictions $(EVAL_POSTPROCESSED_DIR)/article_extractions_clean.jsonl \
		--report $(EVAL_REVIEWED_REPORT) \
		--output $(EVAL_REVIEWED_ERROR_ANALYSIS) \
		--error-dir $(EVAL_REVIEWED_ERROR_DIR)

eval-log-reviewed-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.eval_log \
		--report $(EVAL_REVIEWED_REPORT) \
		--log $(EVAL_LOG) \
		--label "$(EVAL_REVIEWED_LOG_LABEL)" \
		--notes "$(EVAL_REVIEWED_LOG_NOTES)"

eval-reviewed-experiment: eval-apply-case-review eval-score-reviewed-experiment eval-error-analysis-reviewed-experiment eval-log-reviewed-experiment

eval-log-experiment:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.eval_log \
		--report $(EVAL_EXPERIMENT_REPORT) \
		--log $(EVAL_LOG) \
		--label "$(EVAL_EXPERIMENT_LOG_LABEL)" \
		--notes "$(EVAL_EXPERIMENT_LOG_NOTES)"

eval-experiment-from-extractions: eval-postprocess-experiment eval-score-experiment eval-error-analysis-experiment eval-log-experiment

eval-experiment: eval-extract-gold eval-experiment-from-extractions

eval-hybrid-experiment: eval-extract-gold-hybrid eval-experiment-from-extractions

eval-staged-experiment: eval-extract-gold-staged eval-experiment-from-extractions

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.evaluate score \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_PREDICTIONS) \
		--output $(EVAL_REPORT) \
		--markdown-output $(EVAL_MARKDOWN_REPORT)

eval-error-analysis:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m geokg.error_analysis \
		--gold $(EVAL_GOLD) \
		--predictions $(EVAL_PREDICTIONS) \
		--report $(EVAL_REPORT) \
		--output $(EVAL_ERROR_ANALYSIS) \
		--error-dir $(EVAL_ERROR_DIR)

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
