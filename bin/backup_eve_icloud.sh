#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="${EVE_BACKUP_DIR:-$ROOT/EveBackups}"
RUN_DIR="$BACKUP_ROOT/$STAMP"
RUNTIME_EVE_DIR="${EVE_RUNTIME_STATE_DIR:-$HOME/.eve_runtime/.eve}"

mkdir -p "$RUN_DIR"

echo "Creating Eve local iCloud backup at $RUN_DIR"

git -C "$ROOT" rev-parse HEAD > "$RUN_DIR/git-head.txt" 2>/dev/null || true
git -C "$ROOT" branch --show-current > "$RUN_DIR/git-branch.txt" 2>/dev/null || true
git -C "$ROOT" status --short > "$RUN_DIR/git-status.txt" 2>/dev/null || true
git -C "$ROOT" remote -v > "$RUN_DIR/git-remotes.txt" 2>/dev/null || true

if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$ROOT" bundle create "$RUN_DIR/eve-git-$STAMP.bundle" --all
fi

COPYFILE_DISABLE=1 tar -czf "$RUN_DIR/eve-source-working-tree-$STAMP.tar.gz" \
  -C "$ROOT" \
  --exclude "./.git" \
  --exclude "./.eve" \
  --exclude "./.eve.backup-*" \
  --exclude "./EveBackups" \
  --exclude "./.venv" \
  --exclude "./.venv-techlab" \
  --exclude "./.pytest_cache" \
  --exclude "./__pycache__" \
  --exclude "./build" \
  --exclude "./models" \
  --exclude "./operation_not_permitted.txt" \
  --exclude "./vendor/upstreams" \
  --exclude "./openclaw/.openclaw" \
  --exclude "./openclaw/context" \
  --exclude "./openclaw/memory" \
  --exclude "./openclaw/state" \
  .

if [ -d "$ROOT/.eve" ]; then
  COPYFILE_DISABLE=1 tar -czf "$RUN_DIR/eve-source-state-core-$STAMP.tar.gz" \
    -C "$ROOT" \
    --exclude ".eve/locks" \
    --exclude ".eve/logs" \
    --exclude ".eve/code_sessions" \
    --exclude ".eve/capability_tests" \
    --exclude ".eve/model_temp_servers" \
    --exclude ".eve/llama_cpp_slots" \
    .eve
fi

if [ -d "$RUNTIME_EVE_DIR" ]; then
  COPYFILE_DISABLE=1 tar -czf "$RUN_DIR/eve-runtime-state-core-$STAMP.tar.gz" \
    -C "$(dirname "$RUNTIME_EVE_DIR")" \
    --exclude ".eve/locks" \
    --exclude ".eve/logs" \
    --exclude ".eve/code_sessions" \
    --exclude ".eve/capability_tests" \
    --exclude ".eve/model_temp_servers" \
    --exclude ".eve/llama_cpp_slots" \
    .eve
fi

cat > "$RUN_DIR/RESTORE.md" <<EOF
# Eve Backup $STAMP

This backup was created from:

- Project: $ROOT
- Runtime state: $RUNTIME_EVE_DIR

Files:

- eve-git-$STAMP.bundle: committed Git history.
- eve-source-working-tree-$STAMP.tar.gz: current source/docs/scripts working tree, including untracked source files, excluding caches/state/models.
- eve-source-state-core-$STAMP.tar.gz: project-local .eve core state, if present.
- eve-runtime-state-core-$STAMP.tar.gz: runtime .eve state without bulky logs/code_sessions/locks, if present.
- git-status.txt: dirty/untracked file list at backup time.

Quick restore sketch:

1. Clone committed history:
   git clone eve-git-$STAMP.bundle Eve-restored
2. Overlay the source working tree if needed:
   tar -xzf eve-source-working-tree-$STAMP.tar.gz -C Eve-restored
3. Restore project state:
   tar -xzf eve-source-state-core-$STAMP.tar.gz -C Eve-restored
4. Restore runtime state only when you intentionally want to replace the live runtime:
   tar -xzf eve-runtime-state-core-$STAMP.tar.gz -C ~/.eve_runtime
EOF

find "$RUN_DIR" -maxdepth 1 -type f -print | sort
echo "Eve local iCloud backup complete: $RUN_DIR"
