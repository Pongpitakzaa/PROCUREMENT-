#!/usr/bin/env bash
# รันชุดทดสอบความปลอดภัยแบบครบวงจรบนฐานข้อมูลว่าง — ใช้ทั้งใน GitHub Actions และรันเองในเครื่อง
#
#   ต้องมี: PostgreSQL ที่เชื่อมต่อได้ด้วยตัวแปร libpq (PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE)
#           โดย PGDATABASE เป็นฐานข้อมูล "ว่าง" ชื่อมีคำว่า test · Python ที่ติดตั้ง backend/requirements.txt แล้ว
#           · Node 20+ (ติดตั้ง frontend/node_modules และ tools/security-audit/node_modules แล้ว)
#   ทางเลือก: API_PORT (8000) WEB_PORT (5173) PYTHON (python3) CHROMIUM_PATH
#
# ขั้นตอน: สร้าง schema → สุ่ม secret ทั้งหมดใหม่ทุกรอบ → สร้างบัญชีทดสอบ → เปิด API + หน้าเว็บ → run.sh → สรุปผล
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AUDIT_DIR="$ROOT/tools/security-audit"
PY="${PYTHON:-python3}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
export AUDIT_OUT="${AUDIT_OUT:-$AUDIT_DIR/out}"
mkdir -p "$AUDIT_OUT"
: "${PGDATABASE:?ต้องตั้ง PGDATABASE (ฐานข้อมูลว่างสำหรับทดสอบ)}"

pids=()
# แต่ละ server รันใน process group ของตัวเอง (setsid) → ปิดได้ทั้งกลุ่ม รวมโปรเซสลูก (เช่น vite ที่ npx สร้าง)
cleanup() { for p in "${pids[@]}"; do kill -- "-$p" 2>/dev/null || kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_for() {  # url ชื่อ log
  for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 1; done
  echo "::error::$2 ไม่พร้อมภายใน 60 วินาที"; tail -50 "$3" || true; exit 1
}

echo "== 1) schema + ข้อมูลอ้างอิง → $PGDATABASE"
if [[ "$(psql -tAc "SELECT to_regclass('public.projects') IS NOT NULL")" == "t" ]]; then
  echo "::error::ฐานข้อมูล $PGDATABASE มีตารางอยู่แล้ว — ci.sh ต้องใช้ฐานข้อมูลว่าง"; exit 1
fi
psql -v ON_ERROR_STOP=1 -q -f "$ROOT/database/schema.sql" -f "$ROOT/database/seed.sql"

echo "== 2) สุ่ม secret ใหม่ทั้งหมด (ไม่มี secret ถาวรใน repo/CI)"
rand() { "$PY" -c "import secrets,sys;print(secrets.token_urlsafe(int(sys.argv[1])))" "$1"; }
key32() { "$PY" -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"; }
export PROC_ENVIRONMENT=ci
export PROC_DATABASE_URL="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST:-localhost}:${PGPORT:-5432}/${PGDATABASE}"
export PROC_JWT_SECRET="$(rand 48)"
export PROC_BLIND_INDEX_KEY="$(rand 48)"
export PROC_DATA_KEYS="{\"k1\": \"$(key32)\"}"
export PROC_BACKUP_KEY="$(key32)"
export PROC_ALLOWED_ORIGINS="[\"http://localhost:${WEB_PORT}\"]"
STORAGE="$(mktemp -d)"
export PROC_TEMPLATE_DIR="$STORAGE/templates" PROC_OUTPUT_DIR="$STORAGE/outputs" PROC_BACKUP_DIR="$STORAGE/backups"
export AUDIT_PASSWORD="Ci-$(rand 18)-1"
if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
  for s in "$PROC_JWT_SECRET" "$PROC_BLIND_INDEX_KEY" "$PROC_BACKUP_KEY" "$AUDIT_PASSWORD" "$PGPASSWORD"; do echo "::add-mask::$s"; done
fi
export AUDIT_DB_DSN="host=${PGHOST:-localhost} port=${PGPORT:-5432} user=${PGUSER} password=${PGPASSWORD} dbname=${PGDATABASE}"
export AUDIT_API_URL="http://localhost:${API_PORT}" AUDIT_WEB_URL="http://localhost:${WEB_PORT}"

echo "== 3) บัญชีทดสอบ"
(cd "$ROOT/backend" && "$PY" "$AUDIT_DIR/seed_demo.py")

echo "== 4) เปิด API :$API_PORT และหน้าเว็บ :$WEB_PORT"
(cd "$ROOT/backend" && exec setsid "$PY" -m uvicorn app.main:app --port "$API_PORT") > "$AUDIT_OUT/api.log" 2>&1 &
pids+=($!)
(cd "$ROOT/frontend" && API_PROXY_TARGET="http://localhost:${API_PORT}" exec setsid npx vite --port "$WEB_PORT" --strictPort) \
  > "$AUDIT_OUT/web.log" 2>&1 &
pids+=($!)
wait_for "http://localhost:${API_PORT}/healthz" "API" "$AUDIT_OUT/api.log"
wait_for "http://localhost:${WEB_PORT}/" "หน้าเว็บ" "$AUDIT_OUT/web.log"

echo "== 5) ชุดทดสอบ"
set +e
PYTHON="$PY" "$AUDIT_DIR/run.sh"
rc=$?
set -e

echo "== 6) สรุปผล"
"$PY" - "$AUDIT_OUT/results.json" <<'EOF'
import json, os, sys
rs = json.load(open(sys.argv[1], encoding="utf-8"))["results"]
cats = {}
for r in rs:
    cats.setdefault(r["cat"], []).append(r)
failed = [r for r in rs if not r["ok"]]
lines = [f"## {'✅' if not failed else '❌'} Security & Validation Audit: {len(rs) - len(failed)}/{len(rs)} ผ่าน", "",
         "| กลุ่ม | ผล |", "|---|---|"]
lines += [f"| {c} | {sum(i['ok'] for i in items)}/{len(items)} |" for c, items in sorted(cats.items())]
if failed:
    lines += ["", "### ข้อที่ไม่ผ่าน", "", "| กลุ่ม | กรณีทดสอบ | คาดหวัง | ผลจริง |", "|---|---|---|---|"]
    lines += [f"| {r['cat'][:1]} | {r['name']} | {r['expected']} | {str(r['actual'])[:200].replace('|', '/')} |" for r in failed]
lines += ["", "รายงานฉบับเต็มอยู่ใน artifact **security-audit-report** (report.html)"]
text = "\n".join(lines)
print(text)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text + "\n")
for r in failed:   # annotation บนหน้า PR
    print(f"::error title=Security audit ({r['cat'][:1]})::{r['name']} — คาดหวัง {r['expected']}, ได้ {str(r['actual'])[:300]}")
EOF
exit "$rc"
