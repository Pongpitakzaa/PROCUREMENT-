#!/bin/bash
# รันโดย image postgres ครั้งแรกครั้งเดียว (เมื่อ data/postgres ว่าง)
#   - บัญชี proc_app: ไม่ใช่ superuser · เป็นเจ้าของฐานข้อมูล procurement (จำเป็นสำหรับ pg_restore --clean ของระบบกู้คืน)
#   - สร้าง schema + ข้อมูลอ้างอิง (วิธีจัดหา มาตรา 56 ขั้นตอน workflow) ในนามของ proc_app
set -euo pipefail
psql -v ON_ERROR_STOP=1 -v app_pw="$DB_APP_PASSWORD" --username "$POSTGRES_USER" --dbname postgres <<'SQL'
CREATE ROLE proc_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
CREATE DATABASE procurement OWNER proc_app ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE procurement FROM PUBLIC;
SQL
PGOPTIONS="-c role=proc_app" psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname procurement \
  -f /schema/schema.sql -f /schema/seed.sql
echo "procurement: สร้าง schema และข้อมูลอ้างอิงเรียบร้อย"
