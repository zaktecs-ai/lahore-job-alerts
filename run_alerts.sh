#!/bin/bash
# Lahore Job Alerts - cron wrapper
# Project ke andar rehta hai; apni hi location se chalta hai
# (path-independent — DEPLOYMENT.md ke layout ke sath consistent).
cd "$(dirname "$0")" || exit 1
mkdir -p logs
echo "=== run $(date -Is) ===" >> logs/cron.log
exec /usr/bin/flock -n /tmp/jobalerts.lock \
  "$PWD/.venv/bin/python" -m src.main scrape \
  >> logs/cron.log 2>&1
