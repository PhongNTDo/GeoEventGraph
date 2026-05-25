#!/bin/bash
# Can be run directly with `bash` on leanbabel or submitted with `sbatch`.
# CHANGE ME: LeanBabel Slurm defaults.
#SBATCH --time=24:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --gres=gpu:2
#SBATCH --job-name=geokg_extract
#SBATCH --output=logs_runner/geokg_extract_%j.out
#SBATCH --error=logs_runner/geokg_extract_%j.err

set -euo pipefail

# CHANGE ME: LeanBabel machine-specific defaults.
PROJECT_ROOT_DEFAULT="/dcs/pg25/u5728153/Projects/GeoKG"
PYTHON_BIN_DEFAULT="python3"
OLLAMA_BIN_DEFAULT="/dcs/pg25/u5728153/ollama/bin/ollama"
OLLAMA_MODELS_DEFAULT="/dcs/large/u5728153/ollama/models"

PROJECT_ROOT="${PROJECT_ROOT_OVERRIDE:-$PROJECT_ROOT_DEFAULT}"
PYTHON_BIN="${PYTHON_BIN_OVERRIDE:-$PYTHON_BIN_DEFAULT}"
OLLAMA_BIN="${OLLAMA_BIN_OVERRIDE:-$OLLAMA_BIN_DEFAULT}"
OLLAMA_MODELS="${OLLAMA_MODELS_OVERRIDE:-$OLLAMA_MODELS_DEFAULT}"

INPUT_JSONL="${INPUT_JSONL_OVERRIDE:-$PROJECT_ROOT/data/normalized/articles.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR_OVERRIDE:-$PROJECT_ROOT/data/extractions}"
CORPUS_DIR="${CORPUS_DIR_OVERRIDE:-$PROJECT_ROOT/corpus}"
NORMALIZED_OUTPUT_DIR="${NORMALIZED_OUTPUT_DIR_OVERRIDE:-$PROJECT_ROOT/data/normalized}"
RUN_INGESTION="${RUN_INGESTION_OVERRIDE:-0}"

OLLAMA_PORT="${OLLAMA_PORT_OVERRIDE:-11434}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL_OVERRIDE:-http://127.0.0.1:${OLLAMA_PORT}}"
OLLAMA_MODEL="${OLLAMA_MODEL_OVERRIDE:-gpt-oss-120b}"
OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL_OVERRIDE:-1}"
OLLAMA_MAX_QUEUE="${OLLAMA_MAX_QUEUE_OVERRIDE:-1024}"
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE_OVERRIDE:-30m}"
OLLAMA_LOAD_TIMEOUT="${OLLAMA_LOAD_TIMEOUT_OVERRIDE:-20m}"

EXTRACT_RESUME="${EXTRACT_RESUME_OVERRIDE:-1}"
EXTRACT_LIMIT="${EXTRACT_LIMIT_OVERRIDE:-}"
EXTRACT_MAX_RETRIES="${EXTRACT_MAX_RETRIES_OVERRIDE:-2}"
EXTRACT_TIMEOUT_SECONDS="${EXTRACT_TIMEOUT_SECONDS_OVERRIDE:-1800}"
EXTRACT_TEMPERATURE="${EXTRACT_TEMPERATURE_OVERRIDE:-0}"
EXTRACT_NUM_CTX="${EXTRACT_NUM_CTX_OVERRIDE:-16384}"

LOG_DIR="${LOG_DIR_OVERRIDE:-$PROJECT_ROOT/logs_runner}"
RUN_ID="${SLURM_JOB_ID:-$$}"
OLLAMA_LOG="${OLLAMA_LOG_OVERRIDE:-$LOG_DIR/ollama_geokg_${RUN_ID}.log}"

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

if [[ "$RUN_INGESTION" == "1" && ! -d "$CORPUS_DIR" ]]; then
  echo "Corpus directory not found: $CORPUS_DIR" >&2
  exit 1
fi

if [[ ! -x "$OLLAMA_BIN" ]]; then
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_BIN="$(command -v ollama)"
  else
    echo "ERROR: OLLAMA_BIN not found/executable at '$OLLAMA_BIN' and 'ollama' not in PATH." >&2
    exit 1
  fi
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"
export OLLAMA_MODELS
export OLLAMA_MAX_QUEUE
export OLLAMA_KEEP_ALIVE
export OLLAMA_LOAD_TIMEOUT
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"

OLLAMA_PID=""

cleanup() {
  if [[ -n "$OLLAMA_PID" ]]; then
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
    OLLAMA_PID=""
  fi
}
trap cleanup EXIT

wait_for_http() {
  local url="$1"
  local timeout_sec="$2"
  local start_ts now
  start_ts="$(date +%s)"
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    now="$(date +%s)"
    if (( now - start_ts >= timeout_sec )); then
      echo "ERROR: timeout waiting for $url" >&2
      return 1
    fi
    sleep 2
  done
}

start_ollama_server() {
  local version_url="${OLLAMA_BASE_URL%/}/api/version"
  if curl -fsS "$version_url" >/dev/null 2>&1; then
    echo "[geokg-leanbabel] Ollama already reachable at $OLLAMA_BASE_URL"
    return 0
  fi

  local host="${OLLAMA_BASE_URL#http://}"
  host="${host#https://}"
  host="${host%%/*}"
  if [[ -z "$host" ]]; then
    echo "ERROR: Invalid OLLAMA_BASE_URL=$OLLAMA_BASE_URL" >&2
    return 1
  fi

  echo "[geokg-leanbabel] Starting Ollama server on $host"
  OLLAMA_HOST="$host" OLLAMA_NUM_PARALLEL="$OLLAMA_NUM_PARALLEL" \
    "$OLLAMA_BIN" serve >"$OLLAMA_LOG" 2>&1 &
  OLLAMA_PID="$!"

  local ready=0
  for _i in {1..180}; do
    if curl -fsS "$version_url" >/dev/null 2>&1; then
      ready=1
      break
    fi
    if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
      echo "ERROR: Ollama died during startup. Last 200 log lines:" >&2
      tail -n 200 "$OLLAMA_LOG" || true
      return 1
    fi
    sleep 1
  done
  if [[ "$ready" != "1" ]]; then
    echo "ERROR: Ollama start timed out at $OLLAMA_BASE_URL. Last 200 log lines:" >&2
    tail -n 200 "$OLLAMA_LOG" || true
    return 1
  fi

  echo "[geokg-leanbabel] Ollama is ready."
}

check_ollama_model_available() {
  local host="${OLLAMA_BASE_URL#http://}"
  host="${host#https://}"
  host="${host%%/*}"
  if [[ -z "$host" ]]; then
    echo "ERROR: Invalid OLLAMA_BASE_URL=$OLLAMA_BASE_URL" >&2
    return 1
  fi

  echo "[geokg-leanbabel] Checking Ollama model availability via 'ollama list' ..."
  local models_output
  if ! models_output="$(OLLAMA_HOST="$host" "$OLLAMA_BIN" list 2>&1)"; then
    echo "ERROR: failed to run 'ollama list' against $host" >&2
    echo "$models_output" >&2
    return 1
  fi
  echo "$models_output"

  if ! echo "$models_output" | awk 'NR>1 {print $1}' | grep -Fxq "$OLLAMA_MODEL"; then
    echo "ERROR: required Ollama model '$OLLAMA_MODEL' is not available on $host." >&2
    echo "If the installed tag differs, rerun with OLLAMA_MODEL_OVERRIDE=<exact ollama list name>." >&2
    return 1
  fi
}

run_ingestion_if_requested() {
  if [[ "$RUN_INGESTION" != "1" ]]; then
    return 0
  fi
  echo "[geokg-leanbabel] Running corpus ingestion ..."
  "$PYTHON_BIN" -m geokg.ingest_corpus \
    --input-dir "$CORPUS_DIR" \
    --output-dir "$NORMALIZED_OUTPUT_DIR"
}

run_extraction() {
  if [[ ! -f "$INPUT_JSONL" ]]; then
    echo "Normalized input not found: $INPUT_JSONL" >&2
    exit 1
  fi

  local cmd=(
    "$PYTHON_BIN" -m geokg.extract_relations
    --input "$INPUT_JSONL"
    --output-dir "$OUTPUT_DIR"
    --base-url "$OLLAMA_BASE_URL"
    --model "$OLLAMA_MODEL"
    --max-retries "$EXTRACT_MAX_RETRIES"
    --timeout-seconds "$EXTRACT_TIMEOUT_SECONDS"
    --temperature "$EXTRACT_TEMPERATURE"
    --num-ctx "$EXTRACT_NUM_CTX"
  )

  if [[ "$EXTRACT_RESUME" == "1" ]]; then
    cmd+=(--resume)
  fi
  if [[ -n "$EXTRACT_LIMIT" ]]; then
    cmd+=(--limit "$EXTRACT_LIMIT")
  fi

  echo "[geokg-leanbabel] Running extraction command:"
  printf ' %q' "${cmd[@]}"
  echo
  "${cmd[@]}"
}

echo "[geokg-leanbabel] project_root=$PROJECT_ROOT"
echo "[geokg-leanbabel] input_jsonl=$INPUT_JSONL"
echo "[geokg-leanbabel] output_dir=$OUTPUT_DIR"
echo "[geokg-leanbabel] ollama_base_url=$OLLAMA_BASE_URL"
echo "[geokg-leanbabel] ollama_model=$OLLAMA_MODEL"
echo "[geokg-leanbabel] cuda_visible_devices=${CUDA_VISIBLE_DEVICES:-<unset>}"
echo "[geokg-leanbabel] ollama_models=$OLLAMA_MODELS"
echo "[geokg-leanbabel] run_ingestion=$RUN_INGESTION"
echo "[geokg-leanbabel] extract_resume=$EXTRACT_RESUME"
echo "[geokg-leanbabel] extract_limit=${EXTRACT_LIMIT:-<unset>}"

echo "[geokg-leanbabel] GPU status:"
nvidia-smi || true

run_ingestion_if_requested
start_ollama_server
check_ollama_model_available
run_extraction

echo "[geokg-leanbabel] Completed successfully."
