#!/usr/bin/env bash
# ตรวจระบบหลังติดตั้ง/อัปเดต: HTTPS, security headers, API, เครื่องมือสำรองข้อมูล/สร้าง PDF, ฟอนต์ไทย
#   ./check.sh            ตรวจผ่านโดเมนจริง
#   ./check.sh --local    ตรวจที่เครื่องนี้ (ก่อนตั้ง DNS / ใบรับรอง internal)
set -uo pipefail
cd "$(dirname "$0")" || exit 1
DOMAIN="$(grep '^DOMAIN=' .env | cut -d= -f2)"
CURL=(curl -sS --max-time 15)
[[ "${1:-}" == "--local" ]] && CURL+=(--noproxy '*' --resolve "$DOMAIN:443:127.0.0.1" --resolve "$DOMAIN:80:127.0.0.1" -k)
BASE="https://$DOMAIN"
fails=0
ok() { printf '  ✔ %s\n' "$1"; }
bad() { printf '  ✘ %s\n' "$1"; fails=$((fails + 1)); }
t() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "== เว็บ ($BASE)"
# shellcheck disable=SC2034  # ใช้ในเงื่อนไขของ t() ผ่าน eval
headers="$("${CURL[@]}" -D - -o /dev/null "$BASE/")"
t "หน้าเว็บตอบ 200"                   '[[ "$headers" == *" 200"* ]]'
t "HSTS"                               '[[ "${headers,,}" == *"strict-transport-security"* ]]'
t "Content-Security-Policy"            '[[ "${headers,,}" == *"content-security-policy"* ]]'
t "X-Frame-Options DENY"               '[[ "${headers,,}" == *"x-frame-options: deny"* ]]'
t "http:// ถูกส่งต่อไป https://"       '[[ "$("${CURL[@]}" -o /dev/null -w "%{redirect_url}" "http://$DOMAIN/")" == https://* ]]'
t "sw.js ไม่ถูก cache"                  '[[ "$("${CURL[@]}" -D - -o /dev/null "$BASE/sw.js" | tr A-Z a-z)" == *"cache-control: no-cache"* ]]'
t "API ต้องเข้าสู่ระบบก่อน (401)"       '[[ "$("${CURL[@]}" -o /dev/null -w "%{http_code}" "$BASE/api/auth/me")" == 401 ]]'
t "ไม่เปิดเอกสาร API (/api/docs)"      '[[ "$("${CURL[@]}" -o /dev/null -w "%{http_code}" "$BASE/api/docs")" == 404 ]]'

echo "== บริการภายใน"
t "API healthy"                        '[[ "$(docker inspect -f "{{.State.Health.Status}}" "$(docker compose ps -q api)")" == healthy ]]'
t "PostgreSQL ไม่เปิดพอร์ตออกนอก"      '[[ "$(docker inspect -f "{{json .HostConfig.PortBindings}}" "$(docker compose ps -q db)")" == "{}" ]]'
t "pg_dump รุ่น 16 (สำรองข้อมูล)"       'docker compose exec -T api /usr/lib/postgresql/16/bin/pg_dump --version | grep -q " 16\."'
t "LibreOffice (สร้าง PDF)"            'docker compose exec -T api soffice --version >/dev/null 2>&1'
t "ฟอนต์ไทยสำหรับเอกสาร"               'docker compose exec -T api fc-match "TH SarabunPSK" | grep -Eqi "sarabun|laksaman"'
t "ห้องเก็บไฟล์สำรองเขียนได้"           'docker compose exec -T api test -w /app/storage/backups'

echo
if (( fails )); then echo "ไม่ผ่าน $fails ข้อ"; exit 1; else echo "ผ่านทุกข้อ"; fi
