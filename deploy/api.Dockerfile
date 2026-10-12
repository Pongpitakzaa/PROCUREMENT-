# API (FastAPI) — Ubuntu 24.04: มี PostgreSQL 16 client (pg_dump/pg_restore รุ่นเดียวกับฐานข้อมูล),
# LibreOffice (แปลง DOCX → PDF) และฟอนต์ไทยใน repository มาตรฐาน
FROM ubuntu:24.04

# เครือข่ายราชการที่ต้องใช้ mirror ภายใน: --build-arg UBUNTU_MIRROR=https://mirror.example.go.th/ubuntu
ARG UBUNTU_MIRROR=""
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 TZ=Asia/Bangkok \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# CA ขององค์กร (กรณีเครือข่ายมี SSL inspection) — วางไฟล์ *.crt ใน deploy/extra-ca/ (ปกติว่าง)
COPY deploy/extra-ca/ /usr/local/share/ca-certificates/extra/
RUN set -eux; \
    if ls /usr/local/share/ca-certificates/extra/*.crt >/dev/null 2>&1; then \
        mkdir -p /etc/ssl/certs; cat /usr/local/share/ca-certificates/extra/*.crt > /etc/ssl/certs/ca-certificates.crt; fi; \
    if [ -n "$UBUNTU_MIRROR" ]; then \
        sed -i "s|http://archive.ubuntu.com/ubuntu/\?|$UBUNTU_MIRROR/|g; s|http://security.ubuntu.com/ubuntu/\?|$UBUNTU_MIRROR/|g" \
            /etc/apt/sources.list.d/ubuntu.sources; fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates tzdata \
        python3 python3-venv \
        postgresql-client-16 \
        libreoffice-writer-nogui libreoffice-calc-nogui fonts-thai-tlwg fontconfig; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# แบบฟอร์มกรมบัญชีกลางใช้ฟอนต์ TH Sarabun — ถ้าไม่ได้ติดตั้งฟอนต์จริง (deploy/fonts/) ให้ใช้ Laksaman
# ซึ่งออกแบบให้ขนาดตัวอักษรเท่ากัน เอกสาร PDF จึงจัดหน้าไม่เพี้ยน
COPY deploy/fontconfig-th-sarabun.conf /etc/fonts/conf.d/60-th-sarabun-fallback.conf

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY deploy/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod 0755 /usr/local/bin/api-entrypoint \
    && mkdir -p /app/storage/templates /app/storage/outputs /app/storage/backups \
    && chown -R app:app /app/storage

USER app
ENV PROC_ENVIRONMENT=production \
    PROC_TEMPLATE_DIR=/app/storage/templates PROC_OUTPUT_DIR=/app/storage/outputs PROC_BACKUP_DIR=/app/storage/backups \
    PROC_LIBREOFFICE_BIN=soffice PROC_PG_BIN_DIR=/usr/lib/postgresql/16/bin
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status != 200)"
ENTRYPOINT ["api-entrypoint"]
# --proxy-headers: IP ผู้ใช้จริงจาก Caddy ลง audit log (API ไม่เปิดพอร์ตออกนอก จึงเชื่อ header จาก proxy ได้)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
