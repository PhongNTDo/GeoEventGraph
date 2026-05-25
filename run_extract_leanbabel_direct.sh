#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./run_extract_leanbabel_direct.sh [options]

Description:
  Run the GeoKG extraction pipeline directly on the leanbabel server without Slurm.
  This starts a local Ollama server on 127.0.0.1, checks model availability,
  and runs the extraction pipeline over the normalized article JSONL.

Options:
  --project-root <path>     Optional. Defaults to the directory containing this script.
  --input <path>            Optional. Normalized article JSONL input.
  --output-dir <path>       Optional. Extraction output directory.
  --model <value>           Optional. Ollama model tag. Default: gpt-oss-120b.
  --ollama-port <value>     Optional. Local Ollama port. Default: 11434.
  --gpus <value>            Optional. Number of GPUs to use. Default: 2.
  --cuda-visible <value>    Optional. Explicit CUDA_VISIBLE_DEVICES, e.g. 0 or 0,1.
  --limit <value>           Optional. Limit number of processed articles.
  --run-ingestion           Optional. Rebuild normalized JSONL from corpus first.
  --no-resume               Optional. Do not skip already extracted article IDs.
  --dry-run                 Optional. Print env + command without executing.
  -h, --help                Show this help.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
INPUT_JSONL=""
OUTPUT_DIR=""
OLLAMA_MODEL="gpt-oss-120b"
OLLAMA_PORT="11434"
GPU_COUNT="2"
CUDA_VISIBLE_VALUE="${CUDA_VISIBLE_DEVICES_OVERRIDE:-}"
EXTRACT_LIMIT=""
RUN_INGESTION="0"
EXTRACT_RESUME="1"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="${2:-}"
      shift 2
      ;;
    --input)
      INPUT_JSONL="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --model)
      OLLAMA_MODEL="${2:-}"
      shift 2
      ;;
    --ollama-port)
      OLLAMA_PORT="${2:-}"
      shift 2
      ;;
    --gpus)
      GPU_COUNT="${2:-}"
      shift 2
      ;;
    --cuda-visible)
      CUDA_VISIBLE_VALUE="${2:-}"
      shift 2
      ;;
    --limit)
      EXTRACT_LIMIT="${2:-}"
      shift 2
      ;;
    --run-ingestion)
      RUN_INGESTION="1"
      shift
      ;;
    --no-resume)
      EXTRACT_RESUME="0"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

if [[ -z "$INPUT_JSONL" ]]; then
  INPUT_JSONL="$PROJECT_ROOT/data/normalized/articles.jsonl"
fi
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$PROJECT_ROOT/data/extractions"
fi

if [[ -z "$CUDA_VISIBLE_VALUE" ]]; then
  if [[ "$GPU_COUNT" == "2" ]]; then
    CUDA_VISIBLE_VALUE="0,1"
  else
    CUDA_VISIBLE_VALUE="0"
  fi
fi

RUNNER_SCRIPT="$PROJECT_ROOT/run_extract_leanbabel_ollama.sh"
if [[ ! -f "$RUNNER_SCRIPT" ]]; then
  echo "Runner script not found: $RUNNER_SCRIPT" >&2
  exit 1
fi

echo "[run-leanbabel-geokg] project_root=$PROJECT_ROOT"
echo "[run-leanbabel-geokg] input_jsonl=$INPUT_JSONL"
echo "[run-leanbabel-geokg] output_dir=$OUTPUT_DIR"
echo "[run-leanbabel-geokg] ollama_model=$OLLAMA_MODEL"
echo "[run-leanbabel-geokg] ollama_port=$OLLAMA_PORT"
echo "[run-leanbabel-geokg] gpu_count=$GPU_COUNT"
echo "[run-leanbabel-geokg] cuda_visible_devices=$CUDA_VISIBLE_VALUE"
echo "[run-leanbabel-geokg] run_ingestion=$RUN_INGESTION"
echo "[run-leanbabel-geokg] extract_resume=$EXTRACT_RESUME"
echo "[run-leanbabel-geokg] extract_limit=${EXTRACT_LIMIT:-<unset>}"
echo "[run-leanbabel-geokg] dry_run=$DRY_RUN"

cmd=(bash "$RUNNER_SCRIPT")

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s' "[run-leanbabel-geokg] DRY RUN env:"
  printf ' %q' \
    "PROJECT_ROOT_OVERRIDE=$PROJECT_ROOT" \
    "INPUT_JSONL_OVERRIDE=$INPUT_JSONL" \
    "OUTPUT_DIR_OVERRIDE=$OUTPUT_DIR" \
    "OLLAMA_MODEL_OVERRIDE=$OLLAMA_MODEL" \
    "OLLAMA_PORT_OVERRIDE=$OLLAMA_PORT" \
    "RUN_INGESTION_OVERRIDE=$RUN_INGESTION" \
    "EXTRACT_RESUME_OVERRIDE=$EXTRACT_RESUME" \
    "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_VALUE"
  if [[ -n "$EXTRACT_LIMIT" ]]; then
    printf ' %q' "EXTRACT_LIMIT_OVERRIDE=$EXTRACT_LIMIT"
  fi
  printf ' ;'
  printf ' %q' "${cmd[@]}"
  echo
  exit 0
fi

export PROJECT_ROOT_OVERRIDE="$PROJECT_ROOT"
export INPUT_JSONL_OVERRIDE="$INPUT_JSONL"
export OUTPUT_DIR_OVERRIDE="$OUTPUT_DIR"
export OLLAMA_MODEL_OVERRIDE="$OLLAMA_MODEL"
export OLLAMA_PORT_OVERRIDE="$OLLAMA_PORT"
export RUN_INGESTION_OVERRIDE="$RUN_INGESTION"
export EXTRACT_RESUME_OVERRIDE="$EXTRACT_RESUME"
export CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_VALUE"
if [[ -n "$EXTRACT_LIMIT" ]]; then
  export EXTRACT_LIMIT_OVERRIDE="$EXTRACT_LIMIT"
fi

"${cmd[@]}"
