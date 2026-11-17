#!/usr/bin/env bash
# Nightly claimbase compile, cron-safe.
#
# GPU etiquette lives in the CLI itself (cmd_compile → _teacher_busy): if a
# pipeline long run (tagging, dossiers) owns the llama.cpp slot, extraction is
# skipped and prose defers to the next compile — this wrapper only provides a
# sane environment, a timestamp, and a log line either way.
#
# Installed as:  35 5 * * *  (see `crontab -l`)

set -u
export PATH="/usr/local/bin:/usr/bin:/bin"

REPO=/home/ivy/Work/claimbase
LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"

{
  echo "=== cron compile $(date -Is) ==="
  cd "$REPO" || exit 1
  PYTHONPATH=src timeout 3600 .venv/bin/python -m claimbase.cli compile
  rc=$?
  echo "=== done $(date -Is) rc=$rc ==="
} >> "$LOG_DIR/cron-compile.log" 2>&1
