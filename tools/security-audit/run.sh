#!/usr/bin/env bash
# รันการตรวจทั้งหมด: A/B/C (API+DB) → D (เบราว์เซอร์) → รายงาน HTML
# ใช้: AUDIT_PASSWORD=... ./run.sh [--no-browser]
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

"$PY" api_db_audit.py; api_rc=$?
browser_rc=0
if [[ "${1:-}" != "--no-browser" ]]; then
  [[ -d node_modules/playwright ]] || npm install --silent --no-audit --no-fund
  node browser_audit.mjs; browser_rc=$?
fi
"$PY" build_report.py
exit $(( api_rc || browser_rc ))
