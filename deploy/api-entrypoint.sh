#!/bin/sh
# ฟอนต์ที่หน่วยงานติดตั้งเพิ่ม (เช่น TH Sarabun New จาก deploy/fonts/) ต้องเข้า cache ก่อน LibreOffice ใช้งาน
set -e
if [ -n "$(ls -A /usr/local/share/fonts/agency 2>/dev/null)" ]; then
  fc-cache -f /usr/local/share/fonts/agency >/dev/null 2>&1 || true
fi
# สร้าง/ปรับฐานข้อมูลอัตโนมัติ (รันซ้ำได้): schema เมื่อฐานข้อมูลว่าง + migration + ผู้ดูแลคนแรกจาก PROC_BOOTSTRAP_*
# ปิดได้ด้วย PROC_AUTO_INIT_DB=0
if [ "${PROC_AUTO_INIT_DB:-1}" = "1" ]; then
  python -m app.cli init-db
fi
exec "$@"
