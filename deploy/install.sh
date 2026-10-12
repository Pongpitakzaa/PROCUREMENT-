#!/usr/bin/env bash
# ติดตั้ง/อัปเดตระบบบนเซิร์ฟเวอร์ — รันซ้ำได้ (ไม่สร้างค่าลับใหม่ทับของเดิม ไม่ลบข้อมูล)
#   ./install.sh                                         ถามโดเมนและวิธีออกใบรับรอง
#   DOMAIN=proc.agency.go.th CADDY_TLS=it@agency.go.th ./install.sh   ไม่ถาม (ใช้ในสคริปต์อัตโนมัติ)
#   ./install.sh --no-build                              ใช้ image ที่ build/โหลดไว้แล้ว (เซิร์ฟเวอร์ไม่มีอินเทอร์เน็ต:
#                                                        docker load -i procurement-images.tar ก่อน)
set -euo pipefail
BUILD=1
[[ "${1:-}" == "--no-build" ]] && BUILD=0
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null || { echo "ต้องติดตั้ง $1 ก่อน ($2)"; exit 1; }; }
need docker "https://docs.docker.com/engine/install/ubuntu/"
need openssl "sudo apt install openssl"
docker compose version >/dev/null 2>&1 || { echo "ต้องมี Docker Compose v2 (docker compose)"; exit 1; }

rand_url() { openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-"$1"; }   # ใช้ใน URL ได้ (ไม่มีอักขระพิเศษ)
key32() { openssl rand -base64 32 | tr -d '\n'; }

if [[ ! -f .env ]]; then
  echo "== สร้างไฟล์ตั้งค่า .env (ค่าลับสุ่มใหม่)"
  DOMAIN="${DOMAIN:-}"; CADDY_TLS="${CADDY_TLS:-}"
  [[ -n "$DOMAIN" ]] || read -rp "ชื่อโดเมนของระบบ (เช่น procurement.agency.go.th): " DOMAIN
  if [[ -z "$CADDY_TLS" ]]; then
    echo "ใบรับรอง HTTPS:  1) Let's Encrypt อัตโนมัติ (โดเมนเข้าถึงได้จากอินเทอร์เน็ต)"
    echo "                 2) ใบรับรองของหน่วยงาน (วาง fullchain.pem และ privkey.pem ใน deploy/certs/)"
    read -rp "เลือก [1/2]: " choice
    if [[ "$choice" == "2" ]]; then CADDY_TLS="/certs/fullchain.pem /certs/privkey.pem"
    else read -rp "อีเมลผู้ดูแล (ใช้รับแจ้งเตือนใบรับรองหมดอายุ): " CADDY_TLS; fi
  fi
  [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "โดเมนไม่ถูกต้อง: $DOMAIN"; exit 1; }
  umask 077
  cat > .env <<ENV
DOMAIN=$DOMAIN
CADDY_TLS=$CADDY_TLS
DB_SUPERUSER_PASSWORD=$(rand_url 40)
DB_APP_PASSWORD=$(rand_url 40)
PROC_JWT_SECRET=$(rand_url 64)
PROC_BLIND_INDEX_KEY=$(rand_url 64)
PROC_DATA_KEYS={"k1": "$(key32)"}
PROC_ACTIVE_DATA_KEY_ID=k1
PROC_BACKUP_KEY=$(key32)
PROC_LINE_CHANNEL_ACCESS_TOKEN=
UBUNTU_MIRROR=${UBUNTU_MIRROR:-}
ENV
  echo "   สร้าง deploy/.env แล้ว (สิทธิ์ 600) — สำรองไฟล์นี้ไว้ในที่ปลอดภัยนอกเครื่องทันที"
fi

# Docker Compose ให้ตัวแปรใน shell "ทับ" ค่าใน .env — ถ้าเผลอ export PROC_* ไว้ (เช่นจากการทดสอบ)
# API จะเปิดด้วยกุญแจคนละชุดและถอดรหัสข้อมูล/ไฟล์สำรองเดิมไม่ได้ จึงล้างทิ้งก่อนเสมอ
leaked=$(compgen -e | grep -E '^(PROC_|DB_SUPERUSER_PASSWORD$|DB_APP_PASSWORD$|DOMAIN$|CADDY_TLS$|UBUNTU_MIRROR$)' || true)
if [[ -n "$leaked" ]]; then
  echo "   คำเตือน: ล้างตัวแปรใน shell ที่จะทับค่าใน .env: $(echo $leaked)"
  unset $leaked
fi

echo "== เตรียมโฟลเดอร์ข้อมูล"
install -d -m 700 data
install -d data/postgres data/caddy
# API รันด้วย uid 10001 (ไม่ใช่ root) จึงต้องเป็นเจ้าของโฟลเดอร์ไฟล์แบบฟอร์ม/เอกสาร/ไฟล์สำรอง
for d in templates outputs backups; do install -d -o 10001 -g 10001 -m 750 "data/storage/$d"; done

echo "== build และเปิดระบบ"
if (( BUILD )); then docker compose build --pull; fi
docker compose up -d --no-build

echo "== รอให้ระบบพร้อม"
for _ in $(seq 1 90); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q api)" 2>/dev/null || true)"
  [[ "$status" == "healthy" ]] && break
  sleep 2
done
if [[ "$status" != "healthy" ]]; then
  echo "API ยังไม่พร้อม — ดูสาเหตุ: docker compose logs api db"; exit 1
fi
docker compose ps

DOMAIN_NOW="$(grep '^DOMAIN=' .env | cut -d= -f2)"
cat <<MSG

ติดตั้งเรียบร้อย: https://$DOMAIN_NOW

ขั้นต่อไป (ครั้งแรกเท่านั้น):
  docker compose exec api python -m app.cli add-department PSD "กองพัสดุ ..."
  docker compose exec api python -m app.cli create-admin --username itadmin --department PSD \\
      --title นาย --first-name ... --last-name ... --position "นักวิชาการคอมพิวเตอร์" --citizen-id 1234567890123
ตรวจระบบ: ./check.sh
MSG
