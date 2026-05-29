# Gold Evaluation Data

This directory is for human-curated evaluation records. These files are the
answer key used by `make eval`.

## Workflow

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

## Format

The gold file is JSONL: one JSON object per article. Each article contains
article metadata, top-level entities and relations, and article-level event
mentions. See `event_mentions.gold.example.jsonl` for a synthetic example.

The gold file should stay small at first. Start with 10 articles, then expand to
30-50 once the format is comfortable.
