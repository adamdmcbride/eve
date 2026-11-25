#!/bin/bash
# Eve test receipt (Rearchitecture Program task 0.4).
#
# Runs, in order:
#   1. the Python 3.9 parse gate      /usr/bin/python3 bin/eve_py39_parse_check.py --json
#   2. the seven daemon suites        /usr/bin/python3 -m unittest <suites>
#   3. the full pytest run            .venv/bin/python -m pytest tests -q -p no:cacheprovider -rfE
#      inside a scratch `git worktree add --detach <scratch>/tree HEAD` with
#      EVE_RUNTIME_DIR (eve_platform.py runtime_dir()) pointed at a temp dir, so
#      nothing the suite does can reach ~/.eve_runtime or this checkout's .eve/.
#      Skipped when .venv/bin/python is missing or has no pytest, or --skip-pytest.
# and writes a JSON receipt to ${EVE_TEST_RECEIPT_DIR:-.eve/test_receipts}/<utc>.json
# (bin/eve_test_receipt.py does the parsing) plus an optional Markdown summary (--md).
#
# The scratch worktree is always removed on exit (trap), including on Ctrl-C.
# DRY_RUN=1 (or --dry-run) prints the plan and runs/writes nothing.
#
# Usage: bin/eve_test_receipt.sh [--md PATH] [--receipt-dir DIR] [--suites "a b c"]
#                                [--skip-pytest] [--dry-run]
# Env:   EVE_TEST_RECEIPT_DIR, EVE_PY39 (default /usr/bin/python3),
#        EVE_TEST_VENV_PYTHON (default .venv/bin/python), DRY_RUN
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY39="${EVE_PY39:-/usr/bin/python3}"
VENV_PY="${EVE_TEST_VENV_PYTHON:-$ROOT/.venv/bin/python}"
RECEIPT_DIR="${EVE_TEST_RECEIPT_DIR:-$ROOT/.eve/test_receipts}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_PYTEST="${EVE_TEST_RECEIPT_SKIP_PYTEST:-0}"
MD=""
SUITES="tests.test_eve_core_contract tests.test_self_authority tests.test_cognition_budget tests.test_daemon_runtime tests.test_mind_tick tests.test_llama_transport tests.test_cli_parser"
PYTEST_ARGS="tests -q -p no:cacheprovider -rfE"

usage() {
  sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

need_value() {
  # $1 = option name, $2 = number of remaining args. bash's `shift 2` does not
  # shift at all when only one arg is left, which would spin the parser forever.
  if [ "$2" -lt 2 ]; then
    printf 'eve_test_receipt: %s requires a value\n' "$1" >&2
    usage >&2
    exit 64
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --md) need_value "$1" "$#"; MD="$2"; shift 2 ;;
    --md=*) MD="${1#--md=}"; shift ;;
    --receipt-dir) need_value "$1" "$#"; RECEIPT_DIR="$2"; shift 2 ;;
    --receipt-dir=*) RECEIPT_DIR="${1#--receipt-dir=}"; shift ;;
    --suites) need_value "$1" "$#"; SUITES="$2"; shift 2 ;;
    --suites=*) SUITES="${1#--suites=}"; shift ;;
    --skip-pytest) SKIP_PYTEST=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'eve_test_receipt: unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
  esac
done

if [ -z "$MD" ]; then MD_DISPLAY="(none)"; else MD_DISPLAY="$MD"; fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RECEIPT_PATH="$RECEIPT_DIR/$STAMP.json"

# Read-only git facts (safe under DRY_RUN).
GIT_HEAD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then DIRTY=1; else DIRTY=0; fi

# Decide whether the full pytest stage can run.
PYTEST_SKIP_REASON=""
if [ "$SKIP_PYTEST" = "1" ]; then
  PYTEST_SKIP_REASON="--skip-pytest requested"
elif [ ! -x "$VENV_PY" ]; then
  PYTEST_SKIP_REASON="no venv interpreter at $VENV_PY"
elif ! "$VENV_PY" -c 'import pytest' >/dev/null 2>&1; then
  PYTEST_SKIP_REASON="pytest not importable by $VENV_PY"
elif ! git -C "$ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
  PYTEST_SKIP_REASON="not a git checkout; cannot add a scratch worktree"
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "eve_test_receipt plan (DRY_RUN=1: nothing runs, nothing is written)"
  echo "  root:         $ROOT"
  echo "  git:          $GIT_HEAD ($GIT_BRANCH, dirty=$DIRTY)"
  echo "  step 1 parse gate:      $PY39 $ROOT/bin/eve_py39_parse_check.py --json"
  echo "  step 2 unittest (3.9):  $PY39 -m unittest $SUITES"
  if [ -n "$PYTEST_SKIP_REASON" ]; then
    echo "  step 3 pytest (full):   SKIPPED ($PYTEST_SKIP_REASON)"
  else
    echo "  step 3 pytest (full):   git worktree add --detach <scratch>/tree HEAD; cd <scratch>/tree;"
    echo "                          EVE_RUNTIME_DIR=<scratch>/runtime $VENV_PY -m pytest $PYTEST_ARGS"
    echo "                          (worktree removed on exit)"
  fi
  echo "  receipt:      $RECEIPT_PATH"
  echo "  markdown:     $MD_DISPLAY"
  echo "  writer:       $PY39 $ROOT/bin/eve_test_receipt.py"
  exit 0
fi

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/eve_test_receipt.XXXXXX")"
WORKTREE="$SCRATCH/tree"
RUNTIME_TMP="$SCRATCH/runtime"
LOG_DIR="$RECEIPT_DIR/$STAMP.logs"
mkdir -p "$LOG_DIR" "$RUNTIME_TMP"

cleanup() {
  if [ -d "$WORKTREE" ]; then
    git -C "$ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || rm -rf "$WORKTREE"
    git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  fi
  rm -rf "$SCRATCH"
}
trap cleanup EXIT
trap 'cleanup; trap - EXIT; exit 130' INT TERM

echo "eve_test_receipt $STAMP: $GIT_HEAD ($GIT_BRANCH, dirty=$DIRTY)"

# Step 1: parse gate.
PARSE_JSON="$LOG_DIR/parse_gate.json"
echo "[1/3] parse gate: $PY39 bin/eve_py39_parse_check.py --json"
(cd "$ROOT" && "$PY39" "$ROOT/bin/eve_py39_parse_check.py" --json --root "$ROOT") > "$PARSE_JSON" 2> "$LOG_DIR/parse_gate.stderr"
PARSE_EXIT=$?
echo "      exit $PARSE_EXIT"

# Step 2: the seven suites under 3.9 unittest.
UNITTEST_LOG="$LOG_DIR/unittest_py39.log"
echo "[2/3] unittest (3.9): $PY39 -m unittest $SUITES"
# shellcheck disable=SC2086
(cd "$ROOT" && "$PY39" -m unittest $SUITES) > "$UNITTEST_LOG" 2>&1
UNITTEST_EXIT=$?
echo "      exit $UNITTEST_EXIT ($(grep -E '^Ran [0-9]+ tests?' "$UNITTEST_LOG" | tail -1))"

# Step 3: full pytest inside a scratch worktree of HEAD.
PYTEST_LOG="$LOG_DIR/pytest_full.log"
PYTEST_EXIT=1
PYTEST_HEAD=""
if [ -n "$PYTEST_SKIP_REASON" ]; then
  echo "[3/3] pytest (full): skipped ($PYTEST_SKIP_REASON)"
else
  echo "[3/3] pytest (full): git worktree add --detach $WORKTREE HEAD"
  if git -C "$ROOT" worktree add --detach "$WORKTREE" HEAD > "$LOG_DIR/worktree.log" 2>&1; then
    PYTEST_HEAD="$(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "      EVE_RUNTIME_DIR=$RUNTIME_TMP $VENV_PY -m pytest $PYTEST_ARGS"
    # shellcheck disable=SC2086
    (cd "$WORKTREE" && EVE_RUNTIME_DIR="$RUNTIME_TMP" PYTHONDONTWRITEBYTECODE=1 "$VENV_PY" -m pytest $PYTEST_ARGS) > "$PYTEST_LOG" 2>&1
    PYTEST_EXIT=$?
    echo "      exit $PYTEST_EXIT ($(tail -1 "$PYTEST_LOG"))"
  else
    PYTEST_SKIP_REASON="git worktree add failed: $(tail -1 "$LOG_DIR/worktree.log")"
    echo "      $PYTEST_SKIP_REASON"
  fi
fi

# Write the receipt.
mkdir -p "$RECEIPT_DIR"
if [ -n "$PYTEST_SKIP_REASON" ]; then
  # shellcheck disable=SC2086
  "$PY39" "$ROOT/bin/eve_test_receipt.py" \
    --receipt-dir "$RECEIPT_DIR" ${MD:+--md "$MD"} --stamp "$STAMP" --started-at "$STARTED_AT" \
    --root "$ROOT" --git-head "$GIT_HEAD" --git-branch "$GIT_BRANCH" --dirty "$DIRTY" --interpreter "$PY39" \
    --parse-json "$PARSE_JSON" --parse-exit "$PARSE_EXIT" \
    --unittest-log "$UNITTEST_LOG" --unittest-exit "$UNITTEST_EXIT" --suites $SUITES \
    --pytest-skipped "$PYTEST_SKIP_REASON"
else
  # shellcheck disable=SC2086
  "$PY39" "$ROOT/bin/eve_test_receipt.py" \
    --receipt-dir "$RECEIPT_DIR" ${MD:+--md "$MD"} --stamp "$STAMP" --started-at "$STARTED_AT" \
    --root "$ROOT" --git-head "$GIT_HEAD" --git-branch "$GIT_BRANCH" --dirty "$DIRTY" --interpreter "$PY39" \
    --parse-json "$PARSE_JSON" --parse-exit "$PARSE_EXIT" \
    --unittest-log "$UNITTEST_LOG" --unittest-exit "$UNITTEST_EXIT" --suites $SUITES \
    --pytest-log "$PYTEST_LOG" --pytest-exit "$PYTEST_EXIT" --pytest-python "$VENV_PY" \
    --pytest-worktree "$WORKTREE" --pytest-head "$PYTEST_HEAD" --pytest-runtime-dir "$RUNTIME_TMP"
fi
exit $?
