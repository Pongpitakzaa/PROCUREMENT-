# หน้าเว็บ (React build) + Caddy: HTTPS อัตโนมัติ, reverse proxy /api → API, security headers
FROM node:22-bookworm-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
# CA ขององค์กร (กรณีเครือข่ายมี SSL inspection) — ใช้ไฟล์ *.crt ชุดเดียวกับ API ใน deploy/extra-ca/
COPY deploy/extra-ca/ /extra-ca/
RUN if ls /extra-ca/*.crt >/dev/null 2>&1; then cat /extra-ca/*.crt > /tmp/extra-ca.pem; \
        export NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
