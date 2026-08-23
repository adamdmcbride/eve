#!/bin/zsh

set -euo pipefail

PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

SCRIPT_DIR="${0:A:h}"
EVE_MODEL_TOPOLOGY_MODULE_ROOT="${SCRIPT_DIR:h}"
export EVE_MODEL_TOPOLOGY_MODULE_ROOT
SOURCE_CONFIG_PATH="${EVE_MODEL_TOPOLOGY_MODULE_ROOT}/.eve/config.json"
RUNTIME_CONFIG_PATH="${HOME}/.eve_runtime/.eve/config.json"
CONFIG_PATH="${RUNTIME_CONFIG_PATH}"
if [[ ! -r "${CONFIG_PATH}" ]]; then
  CONFIG_PATH="${SOURCE_CONFIG_PATH}"
fi
export EVE_LLAMA_CPP_CONFIG_PATH="${CONFIG_PATH}"
PROFILE="${1:-fast}"
case "${PROFILE}" in
  fast|deep|observer|planner|relationship) ;;
  *)
  echo "Unknown llama.cpp profile: ${PROFILE}. Use 'fast', 'deep', 'observer', 'planner', or 'relationship'." >&2
  exit 1
  ;;
esac

if [[ $# -gt 0 ]]; then
  shift
fi

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

export LLAMA_CPP_PROFILE="${PROFILE}"

eval "$(
python3 - <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.environ["EVE_MODEL_TOPOLOGY_MODULE_ROOT"])
import eve_model_topology

config_path = Path(os.environ["EVE_LLAMA_CPP_CONFIG_PATH"])
payload = json.loads(config_path.read_text()) if config_path.exists() else {}
profile = (os.environ.get("LLAMA_CPP_PROFILE") or "fast").strip().lower()
topology_mode = eve_model_topology.configured_topology_mode(payload)
profile_active = profile in eve_model_topology.active_substrate_profiles(payload)

defaults = {
    "fast": {
        "host": "http://127.0.0.1:8080",
        "alias": "eve-fast",
        "ctx_size": 16384,
        "threads": 8,
        "threads_batch": 8,
        "ubatch_size": 1024,
        "flash_attn": "on",
        "metrics": True,
        "cache_prompt": True,
        "cache_reuse": 256,
        "slot_prompt_similarity": 0.20,
        "parallel": 3,
        "route_fields": ("fast_model", "model"),
    },
    "deep": {
        "host": "http://127.0.0.1:8081",
        "alias": "eve-deep",
        "ctx_size": 24576,
        "threads": 8,
        "threads_batch": 8,
        "ubatch_size": 1024,
        "flash_attn": "on",
        "metrics": True,
        "cache_prompt": True,
        "cache_reuse": 512,
        "slot_prompt_similarity": 0.20,
        "parallel": 1,
        "route_fields": ("deep_model", "model"),
    },
    "observer": {
        "host": "http://127.0.0.1:8082",
        "alias": "eve-observer",
        "ctx_size": 16384,
        "threads": 6,
        "threads_batch": 6,
        "ubatch_size": 512,
        "flash_attn": "on",
        "metrics": True,
        "cache_prompt": True,
        "cache_reuse": 128,
        "slot_prompt_similarity": 0.20,
        "parallel": 1,
        "route_fields": ("mind_stream_observer_model",),
    },
    "planner": {
        "host": "http://127.0.0.1:8083",
        "alias": "eve-planner",
        "ctx_size": 16384,
        "threads": 6,
        "threads_batch": 6,
        "ubatch_size": 512,
        "flash_attn": "on",
        "metrics": True,
        "cache_prompt": True,
        "cache_reuse": 128,
        "slot_prompt_similarity": 0.20,
        "parallel": 1,
        "route_fields": ("mind_stream_planner_model",),
    },
    "relationship": {
        "host": "http://127.0.0.1:8084",
        "alias": "eve-relationship",
        "ctx_size": 16384,
        "threads": 8,
        "threads_batch": 8,
        "ubatch_size": 512,
        "flash_attn": "on",
        "metrics": True,
        "cache_prompt": True,
        "cache_reuse": 128,
        "slot_prompt_similarity": 0.20,
        "parallel": 1,
        "route_fields": ("mind_stream_relationship_model", "reply_stream_listener_model"),
    },
}

prefix = "" if profile == "fast" else f"{profile}_"
default = defaults[profile]

def config_value(name, fallback="", allow_global=False):
    if profile != "fast":
        candidate = payload.get(f"{prefix}llama_cpp_{name}")
        if candidate not in (None, ""):
            return candidate
        candidate = payload.get(f"{prefix}{name}")
        if candidate not in (None, ""):
            return candidate
        if not allow_global:
            return fallback
    candidate = payload.get(f"llama_cpp_{name}")
    if candidate not in (None, ""):
        return candidate
    return fallback

def config_bool(name, fallback=False):
    value = config_value(name, fallback)
    text = " ".join(str(value or "").strip().lower().split())
    if not text:
        return bool(fallback)
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(fallback)

host_url = str(payload.get(f"{prefix}llama_cpp_host") or default["host"]).strip()
model_path = str(payload.get(f"{prefix}llama_cpp_model_path") or "").strip()
hf_repo = str(payload.get(f"{prefix}llama_cpp_hf_repo") or "").strip()
alias_candidates = [str(payload.get(f"{prefix}llama_cpp_model_alias") or "").strip()]
for field in default["route_fields"]:
    alias_candidates.append(str(payload.get(field) or "").strip())
alias_candidates.append(default["alias"])
alias = next((candidate for candidate in alias_candidates if candidate), default["alias"])
ctx_size = int(payload.get(f"{prefix}llama_cpp_ctx_size") or default["ctx_size"])
threads = int(payload.get(f"{prefix}llama_cpp_threads") or payload.get("llama_cpp_threads") or default["threads"])
threads_batch = int(config_value("threads_batch", default.get("threads_batch", threads)) or threads)
ubatch_size = int(config_value("ubatch_size", default.get("ubatch_size", 512)) or 512)
flash_attn = str(config_value("flash_attn", default.get("flash_attn", "auto")) or "auto").strip().lower()
metrics = config_bool("metrics", default.get("metrics", False))
cache_prompt = config_bool("cache_prompt", default.get("cache_prompt", True))
cache_reuse = int(config_value("cache_reuse", default.get("cache_reuse", 0)) or 0)
slot_prompt_similarity = float(config_value("slot_prompt_similarity", default.get("slot_prompt_similarity", 0.20)) or 0.20)
slot_save_path = str(config_value("slot_save_path", (config_path.parent / "llama_cpp_slots" / profile).resolve()) or "").strip()
parallel = int(payload.get(f"{prefix}llama_cpp_parallel_slots") or default["parallel"])
gpu_layers_raw = payload.get(f"{prefix}llama_cpp_gpu_layers")
draft_model_path = str(config_value("draft_model_path", "") or "").strip()
draft_hf_repo = str(config_value("draft_hf_repo", "") or "").strip()
draft_tokens = int(config_value("draft_tokens", 0) or 0)
draft_min_tokens = int(config_value("draft_min_tokens", 0) or 0)
draft_min_prob = float(config_value("draft_min_prob", 0.75) or 0.75)
draft_ctx_size = int(config_value("draft_ctx_size", 0) or 0)
draft_gpu_layers_raw = config_value("draft_gpu_layers", "")
draft_threads = int(config_value("threads_draft", threads) or threads)
draft_threads_batch = int(config_value("threads_batch_draft", threads_batch) or threads_batch)
spec_type = str(config_value("spec_type", "") or "").strip().lower()
reasoning = str(config_value("reasoning", "") or "").strip().lower()
server_bin = str(config_value("binary_path", payload.get("llama_cpp_binary_path", ""), allow_global=True) or "").strip()

parsed = urlparse(host_url if "://" in host_url else f"http://{host_url}")
hostname = parsed.hostname or "127.0.0.1"
port = parsed.port or 8080
api_key = str(payload.get("llama_cpp_api_key") or "").strip()
gpu_layers = str(gpu_layers_raw).strip() if gpu_layers_raw not in (None, "") else "all"
if gpu_layers == "-1":
    gpu_layers = "all"
draft_gpu_layers = str(draft_gpu_layers_raw).strip() if draft_gpu_layers_raw not in (None, "") else "all"
if draft_gpu_layers == "-1":
    draft_gpu_layers = "all"
if flash_attn not in {"on", "off", "auto"}:
    flash_attn = str(default.get("flash_attn", "auto"))
if reasoning not in {"", "on", "off", "auto"}:
    reasoning = ""

def cached_hf_gguf_path(spec: str) -> str:
    repo_spec = str(spec or "").strip()
    if not repo_spec:
        return ""
    repo_id, _, selector = repo_spec.partition(":")
    repo_id = repo_id.strip()
    selector = selector.strip().lower()
    if "/" not in repo_id:
        return ""
    cache_root = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo_id.replace("/", "--")) / "snapshots"
    if not cache_root.exists():
        return ""
    candidates = []
    for path in cache_root.glob("*/*.gguf"):
        name = path.name.lower()
        if "mmproj" in name:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        selector_match = not selector or selector in name
        if selector and not selector_match:
            continue
        candidates.append((stat.st_mtime, stat.st_size, str(path)))
    if not candidates and selector:
        for path in cache_root.glob("*/*.gguf"):
            name = path.name.lower()
            if "mmproj" in name:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            candidates.append((stat.st_mtime, stat.st_size, str(path)))
    if not candidates:
        return ""
    return sorted(candidates)[-1][2]

if not model_path and hf_repo:
    cached_model_path = cached_hf_gguf_path(hf_repo)
    if cached_model_path:
        model_path = cached_model_path
        hf_repo = ""

values = {
    "EVE_MODEL_TOPOLOGY_MODE": topology_mode,
    "LLAMA_CPP_PROFILE_ACTIVE": "1" if profile_active else "0",
    "LLAMA_CPP_HOSTNAME": hostname,
    "LLAMA_CPP_PORT": str(port),
    "LLAMA_CPP_MODEL_PATH": model_path,
    "LLAMA_CPP_HF_REPO": hf_repo,
    "LLAMA_CPP_ALIAS": alias,
    "LLAMA_CPP_API_KEY": api_key,
    "LLAMA_CPP_CTX_SIZE": str(max(ctx_size, 1024)),
    "LLAMA_CPP_THREADS": str(max(threads, 1)),
    "LLAMA_CPP_THREADS_BATCH": str(max(threads_batch, 1)),
    "LLAMA_CPP_UBATCH_SIZE": str(max(ubatch_size, 32)),
    "LLAMA_CPP_FLASH_ATTN": flash_attn,
    "LLAMA_CPP_METRICS": "1" if metrics else "0",
    "LLAMA_CPP_CACHE_PROMPT": "1" if cache_prompt else "0",
    "LLAMA_CPP_CACHE_REUSE": str(max(cache_reuse, 0)),
    "LLAMA_CPP_SLOT_PROMPT_SIMILARITY": str(max(slot_prompt_similarity, 0.0)),
    "LLAMA_CPP_SLOT_SAVE_PATH": slot_save_path,
    "LLAMA_CPP_PARALLEL": str(max(parallel, 1)),
    "LLAMA_CPP_GPU_LAYERS": gpu_layers or "all",
    "LLAMA_CPP_DRAFT_MODEL_PATH": draft_model_path,
    "LLAMA_CPP_DRAFT_HF_REPO": draft_hf_repo,
    "LLAMA_CPP_DRAFT_TOKENS": str(max(draft_tokens, 0)),
    "LLAMA_CPP_DRAFT_MIN_TOKENS": str(max(draft_min_tokens, 0)),
    "LLAMA_CPP_DRAFT_MIN_PROB": str(max(draft_min_prob, 0.0)),
    "LLAMA_CPP_DRAFT_CTX_SIZE": str(max(draft_ctx_size, 0)),
    "LLAMA_CPP_DRAFT_GPU_LAYERS": draft_gpu_layers or "all",
    "LLAMA_CPP_THREADS_DRAFT": str(max(draft_threads, 1)),
    "LLAMA_CPP_THREADS_BATCH_DRAFT": str(max(draft_threads_batch, 1)),
    "LLAMA_CPP_SPEC_TYPE": spec_type,
    "LLAMA_CPP_REASONING": reasoning,
    "LLAMA_CPP_SERVER_BIN": server_bin or "llama-server",
}

for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
PY
)"

if [[ "${LLAMA_CPP_PROFILE_ACTIVE}" != "1" ]]; then
  echo "llama.cpp profile ${PROFILE} is inactive under ${EVE_MODEL_TOPOLOGY_MODE}; its logical lane is served by an active shared substrate."
  exit 0
fi

if [[ -z "${LLAMA_CPP_MODEL_PATH}" && -z "${LLAMA_CPP_HF_REPO}" ]]; then
  if [[ "${PROFILE}" == "deep" ]]; then
    echo "No deep llama.cpp model source is configured. Set deep_llama_cpp_model_path or deep_llama_cpp_hf_repo in ${CONFIG_PATH}." >&2
  elif [[ "${PROFILE}" == "fast" ]]; then
    echo "No llama.cpp model source is configured. Set llama_cpp_model_path or llama_cpp_hf_repo in ${CONFIG_PATH}." >&2
  else
    echo "No ${PROFILE} llama.cpp model source is configured. Set ${PROFILE}_llama_cpp_model_path or ${PROFILE}_llama_cpp_hf_repo in ${CONFIG_PATH}." >&2
  fi
  exit 1
fi

if [[ -n "${LLAMA_CPP_SLOT_SAVE_PATH}" ]]; then
  mkdir -p "${LLAMA_CPP_SLOT_SAVE_PATH}"
fi

if [[ "${LLAMA_CPP_SERVER_BIN}" == */* ]]; then
  if [[ ! -x "${LLAMA_CPP_SERVER_BIN}" ]]; then
    echo "Configured llama-server binary is not executable: ${LLAMA_CPP_SERVER_BIN}" >&2
    exit 1
  fi
elif ! command -v "${LLAMA_CPP_SERVER_BIN}" >/dev/null 2>&1; then
  echo "llama-server is not installed. Run ${SCRIPT_DIR}/install_llama_cpp.sh first or set llama_cpp_binary_path in ${CONFIG_PATH}." >&2
  exit 1
fi

cmd=(
  "${LLAMA_CPP_SERVER_BIN}"
  --host "${LLAMA_CPP_HOSTNAME}"
  --port "${LLAMA_CPP_PORT}"
  --ctx-size "${LLAMA_CPP_CTX_SIZE}"
  --threads "${LLAMA_CPP_THREADS}"
  --threads-batch "${LLAMA_CPP_THREADS_BATCH}"
  --ubatch-size "${LLAMA_CPP_UBATCH_SIZE}"
  --flash-attn "${LLAMA_CPP_FLASH_ATTN}"
  --parallel "${LLAMA_CPP_PARALLEL}"
  --gpu-layers "${LLAMA_CPP_GPU_LAYERS}"
  --slot-prompt-similarity "${LLAMA_CPP_SLOT_PROMPT_SIMILARITY}"
  --slots
)

if [[ "${LLAMA_CPP_METRICS}" == "1" ]]; then
  cmd+=(--metrics)
fi

if [[ "${LLAMA_CPP_CACHE_PROMPT}" == "1" ]]; then
  cmd+=(--cache-prompt)
else
  cmd+=(--no-cache-prompt)
fi

if [[ "${LLAMA_CPP_CACHE_REUSE}" -gt 0 ]]; then
  cmd+=(--cache-reuse "${LLAMA_CPP_CACHE_REUSE}")
fi

if [[ -n "${LLAMA_CPP_SLOT_SAVE_PATH}" ]]; then
  cmd+=(--slot-save-path "${LLAMA_CPP_SLOT_SAVE_PATH}")
fi

if [[ -n "${LLAMA_CPP_ALIAS}" ]]; then
  cmd+=(--alias "${LLAMA_CPP_ALIAS}")
fi

if [[ -n "${LLAMA_CPP_REASONING}" ]]; then
  cmd+=(--reasoning "${LLAMA_CPP_REASONING}")
fi

if [[ -n "${LLAMA_CPP_API_KEY}" ]]; then
  cmd+=(--api-key "${LLAMA_CPP_API_KEY}")
fi

if [[ -n "${LLAMA_CPP_MODEL_PATH}" ]]; then
  cmd+=(--model "${LLAMA_CPP_MODEL_PATH}")
else
  cmd+=(--hf-repo "${LLAMA_CPP_HF_REPO}")
fi

if [[ -n "${LLAMA_CPP_DRAFT_MODEL_PATH}" ]]; then
  cmd+=(--model-draft "${LLAMA_CPP_DRAFT_MODEL_PATH}")
elif [[ -n "${LLAMA_CPP_DRAFT_HF_REPO}" ]]; then
  cmd+=(--hf-repo-draft "${LLAMA_CPP_DRAFT_HF_REPO}")
fi

if [[ -n "${LLAMA_CPP_DRAFT_MODEL_PATH}" || -n "${LLAMA_CPP_DRAFT_HF_REPO}" ]]; then
  if [[ "${LLAMA_CPP_DRAFT_TOKENS}" -gt 0 ]]; then
    cmd+=(--draft "${LLAMA_CPP_DRAFT_TOKENS}")
  fi
  if [[ "${LLAMA_CPP_DRAFT_MIN_TOKENS}" -gt 0 ]]; then
    cmd+=(--draft-min "${LLAMA_CPP_DRAFT_MIN_TOKENS}")
  fi
  cmd+=(--draft-p-min "${LLAMA_CPP_DRAFT_MIN_PROB}")
  if [[ "${LLAMA_CPP_DRAFT_CTX_SIZE}" -gt 0 ]]; then
    cmd+=(--ctx-size-draft "${LLAMA_CPP_DRAFT_CTX_SIZE}")
  fi
  cmd+=(--gpu-layers-draft "${LLAMA_CPP_DRAFT_GPU_LAYERS}")
  cmd+=(--threads-draft "${LLAMA_CPP_THREADS_DRAFT}")
  cmd+=(--threads-batch-draft "${LLAMA_CPP_THREADS_BATCH_DRAFT}")
elif [[ -n "${LLAMA_CPP_SPEC_TYPE}" ]]; then
  cmd+=(--spec-type "${LLAMA_CPP_SPEC_TYPE}")
fi

echo "Starting llama.cpp ${PROFILE} server on ${LLAMA_CPP_HOSTNAME}:${LLAMA_CPP_PORT}"
if [[ "${DRY_RUN}" == "1" ]]; then
  printf '%q ' "${cmd[@]}" "$@"
  printf '\n'
  exit 0
fi
exec "${cmd[@]}" "$@"
