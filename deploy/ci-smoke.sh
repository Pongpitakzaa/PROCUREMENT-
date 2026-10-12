#!/usr/bin/env bash
# ทดสอบชุดติดตั้ง Docker แบบครบวงจร — ใช้ใน GitHub Actions และรันเองบนเครื่องทดสอบได้
#   ต้องมี image procurement-api:latest / procurement-web:latest (docker compose build) และสิทธิ์ root
#   sudo ./ci-smoke.sh
#
# ขั้นตอน: install.sh (ใบรับรองชั่วคราว) → check.sh 14 ข้อ → สร้างผู้ดูแลด้วย CLI → เข้าสู่ระบบผ่าน HTTPS
#          → สำรองข้อมูลด้วย CLI → API เห็นไฟล์สำรอง
# ห้ามรันบนเซิร์ฟเวอร์จริง: สคริปต์หยุดทันทีถ้ามี .env หรือข้อมูลอยู่แล้ว
set -euo pipefail
cd "$(dirname "$0")"

if [[ -e .env || -n "$(ls -A data/postgres 2>/dev/null)" ]]; then
  echo "::error::พบ .env หรือฐานข้อมูลเดิม — ci-smoke.sh ใช้กับเครื่องทดสอบที่ยังไม่ได้ติดตั้งเท่านั้น"
  exit 1
fi
DOMAIN=procurement.ci.local
step() { echo; echo "== $*"; }

step "ติดตั้ง (install.sh --no-build)"
DOMAIN=$DOMAIN CADDY_TLS=internal ./install.sh --no-build

step "ตรวจระบบ (check.sh)"
for _ in $(seq 1 15); do   # Caddy ออกใบรับรอง internal ครั้งแรกใช้เวลาไม่กี่วินาที
  curl -sk --noproxy '*' --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null "https://$DOMAIN/" && break
  sleep 2
done
./check.sh --local

step "สร้างผู้ดูแลระบบด้วย CLI"
cli() { docker compose exec -T api python -m app.cli "$@"; }
cli add-department CI "หน่วยงานทดสอบ CI"
out="$(cli create-admin --username ciadmin --department CI --title นาย --first-name ทดสอบ --last-name ซีไอ \
       --position ผู้ดูแลระบบ --citizen-id 1100000000016)"
password="$(awk '/รหัสผ่าน  :/ {print $3}' <<<"$out")"
[[ -n "$password" ]] || { echo "::error::create-admin ไม่แสดงรหัสผ่าน"; exit 1; }
[[ -n "${GITHUB_ACTIONS:-}" ]] && echo "::add-mask::$password"

step "เข้าสู่ระบบผ่าน HTTPS"
CURL=(curl -sS --fail-with-body --noproxy '*' -k --resolve "$DOMAIN:443:127.0.0.1")
token="$("${CURL[@]}" -H 'Content-Type: application/json' \
         -d "$(python3 -c 'import json,sys; print(json.dumps({"username": "ciadmin", "password": sys.argv[1]}))' "$password")" \
         "https://$DOMAIN/api/auth/login" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
[[ -n "${GITHUB_ACTIONS:-}" ]] && echo "::add-mask::$token"
me="$("${CURL[@]}" -H "Authorization: Bearer $token" "https://$DOMAIN/api/auth/me")"
python3 -c 'import json,sys; m=json.loads(sys.argv[1]); assert m["username"]=="ciadmin" and "ADMIN" in m["roles"], m' "$me"
echo "  ✔ ciadmin เข้าสู่ระบบได้ บทบาท ADMIN"

step "สำรองข้อมูลด้วย CLI (pg_dump 16 + เข้ารหัส)"
cli backup --keep-days 30
backups="$("${CURL[@]}" -H "Authorization: Bearer $token" "https://$DOMAIN/api/admin/backups")"
python3 -c 'import json,sys; b=json.loads(sys.argv[1]); assert any(x["file_name"].endswith("-auto.dump.enc") for x in b), b' "$backups"
echo "  ✔ API เห็นไฟล์สำรองอัตโนมัติ"

echo
echo "ผ่านทุกขั้นตอน"
