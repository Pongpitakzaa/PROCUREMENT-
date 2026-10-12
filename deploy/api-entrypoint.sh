#!/bin/sh
# ฟอนต์ที่หน่วยงานติดตั้งเพิ่ม (เช่น TH Sarabun New จาก deploy/fonts/) ต้องเข้า cache ก่อน LibreOffice ใช้งาน
set -e
if [ -n "$(ls -A /usr/local/share/fonts/agency 2>/dev/null)" ]; then
  fc-cache -f /usr/local/share/fonts/agency >/dev/null 2>&1 || true
fi
exec "$@"
