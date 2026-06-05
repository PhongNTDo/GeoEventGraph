# Gold Evaluation Data

This directory is for human-curated evaluation records. These files are the
answer key used by `make eval`.

## Workflow

Use `docs/ANNOTATION_GUIDELINES.md` when reviewing model-assisted annotations or
editing gold rows.

1. Generate draft annotation candidates:

   ```bash
   make eval-candidates EVAL_LIMIT=10
   ```

   This writes `data/eval/annotation_candidates.jsonl`. That file is generated
   from current model output, so it is only a draft.

2. Copy selected candidate rows into:

   ```text
   data/gold/event_mentions.gold.jsonl
   ```

   Or use the model-assisted workflow:

   ```bash
   make eval-packets
   make eval-model-drafts OPENAI_API_KEY_FILE=OpenAI_key.txt OPENAI_ANNOTATION_MODEL=gpt-5.4
   ```

   This creates editable per-article JSON files in:

   ```text
   data/eval/model_review/
   ```

3. Manually correct each copied row:

   - remove false entities, relations, or events;
   - add missing entities, relations, or events;
   - correct entity types and participant roles;
   - correct event dates and date precision;
   - correct event location and geocode fields when known;
   - make sure evidence is an exact article quote;
   - set `annotation_status` to `gold`.

   If you use model-assisted drafts, edit each `data/eval/model_review/*.json`
   file and set `annotation_status` to `gold` after checking it. Then run:

   ```bash
   make eval-gold-from-reviewed
   ```

4. Run:

   ```bash
   make eval
   ```

   The scorer refuses rows that still have `annotation_status` other than
   `gold`, unless the internal test-only `--allow-draft-gold` flag is used.

5. Append the run to the tracked accuracy log:

   ```bash
   make eval-log EVAL_RUN_LABEL="event-v1 baseline" EVAL_RUN_NOTES="10 reviewed gold articles"
   ```

   This updates `EVALUATION_LOG.md`. Use a short label and note so future
   ontology, prompt, geocoder, and model changes can be compared.

6. Generate detailed error analysis:

   ```bash
   make eval-error-analysis
   ```

   This writes:

   ```text
   data/eval/error_analysis.md
   data/eval/errors/
   ```

   Inspect these files before changing prompts, ontology, geocoding, or model
   settings. They show which gold events were missed, which predictions were
   extra, where participant roles differ, and where located events still lack
   coordinates.

7. For the recommended hybrid extraction experiment on only the curated gold
   articles, run:

   ```bash
   make eval-extract-gold-hybrid-leanbabel EVAL_EXPERIMENT_NAME=event-v2-hybrid OLLAMA_MODEL=gpt-oss:120b
   ```

   Then score and log the experiment:

   ```bash
   make eval-experiment-from-extractions \
     EVAL_EXPERIMENT_NAME=event-v2-hybrid \
     EVAL_EXPERIMENT_LOG_LABEL="event-v2-hybrid LeanBabel" \
     EVAL_EXPERIMENT_LOG_NOTES="event-v1 candidates with per-event verifier and deterministic relation repair"
   ```

   This appends the compact comparison row to `EVALUATION_LOG.md` and writes
   detailed generated reports under `data/eval/event-v2-hybrid/`.

   See `docs/HYBRID_EXTRACTION.md` for the method and diagram. The older staged
   extractor remains documented in `docs/MULTI_STAGE_EXTRACTION.md`, but it is
   not the current recommended direction as-is.

## Format

The gold file is JSONL: one JSON object per article. Each article contains
article metadata, top-level entities and relations, and article-level event
mentions. See `event_mentions.gold.example.jsonl` for a synthetic example.

The gold file should stay small at first. Start with 10 articles, then expand to
30-50 once the format is comfortable.
