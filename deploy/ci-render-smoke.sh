#!/usr/bin/env bash
# ทดสอบ image แบบเดียวกับที่ Render รัน (render.yaml) — ใช้ใน GitHub Actions และรันเองได้
#   ต้องมี image procurement-api:latest
#   ./ci-render-smoke.sh
#
# จำลอง Render: ฐานข้อมูลว่างที่เจ้าของไม่ใช่ superuser, URL แบบ postgresql://, กุญแจเดี่ยว (PROC_DATA_KEY),
# API เสิร์ฟหน้าเว็บเอง (PROC_STATIC_DIR), ไม่มี volume (ระบบไฟล์ถูกล้างทุกครั้งที่เริ่มใหม่)
set -euo pipefail

NET=render-smoke-net
DB=render-smoke-db
APP=render-smoke-app
PORT=18030
cleanup() { docker rm -f "$APP" "$DB" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
step() { echo; echo "== $*"; }
key() { openssl rand -base64 32; }

step "PostgreSQL 16 (บัญชีแอปไม่ใช่ superuser เหมือน Render)"
docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" -e POSTGRES_PASSWORD=ci-superuser postgres:16-bookworm >/dev/null
for _ in $(seq 1 60); do docker exec "$DB" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
sleep 2
docker exec "$DB" psql -U postgres -qc "CREATE ROLE proc_app LOGIN PASSWORD 'ci-app' NOSUPERUSER" \
  -c "CREATE DATABASE procurement OWNER proc_app"

ENVFILE="$(mktemp)"
cat > "$ENVFILE" <<ENV
PROC_DATABASE_URL=postgresql://proc_app:ci-app@$DB:5432/procurement
PROC_JWT_SECRET=$(key)
PROC_BLIND_INDEX_KEY=$(key)
PROC_DATA_KEY=$(key)
PROC_BACKUP_KEY=$(key)
PROC_STATIC_DIR=/app/static
UVICORN_WORKERS=1
PORT=8000
RENDER_EXTERNAL_URL=http://localhost:$PORT
PROC_BOOTSTRAP_ADMIN_USERNAME=renderadmin
PROC_BOOTSTRAP_ADMIN_PASSWORD=Ci-Render-Smoke-2570
PROC_BOOTSTRAP_ADMIN_NAME=นายทดสอบ เรนเดอร์
PROC_BOOTSTRAP_ADMIN_CITIZEN_ID=1100000000016
PROC_BOOTSTRAP_DEPARTMENT_NAME=หน่วยงานทดสอบ Render
ENV

start_app() {
  docker rm -f "$APP" >/dev/null 2>&1 || true
  docker run -d --name "$APP" --network "$NET" -p "$PORT:8000" --env-file "$ENVFILE" procurement-api:latest >/dev/null
  for _ in $(seq 1 90); do curl -sf "http://localhost:$PORT/healthz" >/dev/null && return 0; sleep 1; done
  docker logs "$APP" | tail -40; echo "::error::API ไม่พร้อมภายใน 90 วินาที"; exit 1
}
login() {
  curl -sS --fail-with-body -H 'Content-Type: application/json' \
    -d '{"username":"renderadmin","password":"Ci-Render-Smoke-2570"}' "http://localhost:$PORT/api/auth/login" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

step "เริ่มครั้งแรก: init-db สร้าง schema + ผู้ดูแลคนแรก"
start_app
logs="$(docker logs "$APP" 2>&1)"   # อ่านเก็บก่อน: grep -q ปิดท่อก่อน → docker logs โดน SIGPIPE → pipefail
grep "init-db" <<<"$logs"
grep -q "สร้างผู้ดูแลระบบ renderadmin แล้ว" <<<"$logs" || { echo "::error::ไม่ได้สร้างผู้ดูแลคนแรก"; exit 1; }

step "หน้าเว็บจาก API + header"
headers="$(curl -sS -D - -o /tmp/render-home.html "http://localhost:$PORT/")"
grep -q '<div id="root">' /tmp/render-home.html || { echo "::error::หน้าแรกไม่ใช่หน้าเว็บ React"; exit 1; }
grep -qi "content-security-policy: default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com" <<<"$headers" \
  || { echo "::error::CSP ของหน้าเว็บไม่ถูกต้อง"; exit 1; }
[[ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/api/auth/me")" == 401 ]] || { echo "::error::API ไม่ต้องเข้าสู่ระบบ"; exit 1; }
[[ "$(curl -s "http://localhost:$PORT/api/does-not-exist" | python3 -c 'import json,sys; print(json.load(sys.stdin)["message"])')" == "ไม่พบ endpoint" ]] \
  || { echo "::error::/api ที่ไม่มีอยู่ต้องตอบ JSON 404"; exit 1; }
echo "  ✔ หน้าเว็บ · CSP · API 401 · JSON 404"

step "เข้าสู่ระบบด้วยผู้ดูแลคนแรก"
token="$(login)"
curl -sS --fail-with-body -H "Authorization: Bearer $token" "http://localhost:$PORT/api/auth/me" \
  | python3 -c 'import json,sys; m=json.load(sys.stdin); assert m["roles"]==["ADMIN"], m; print("  ✔", m["full_name_th"], m["roles"])'

step "เริ่มใหม่ (ระบบไฟล์ใหม่ทั้งหมด): ไม่สร้าง schema/ผู้ดูแลซ้ำ ข้อมูลยังอยู่"
start_app
logs="$(docker logs "$APP" 2>&1)"
grep "init-db" <<<"$logs"
grep -q "มีผู้ใช้แล้ว" <<<"$logs" || { echo "::error::init-db ไม่ข้ามผู้ใช้ที่มีอยู่"; exit 1; }
login >/dev/null && echo "  ✔ เข้าสู่ระบบได้หลังเริ่มใหม่"

echo
echo "ผ่านทุกขั้นตอน (โหมด Render)"
