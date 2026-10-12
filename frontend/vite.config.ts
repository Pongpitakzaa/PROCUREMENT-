import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // dev proxy → FastAPI (production ให้ reverse proxy เสิร์ฟ /api ใต้ origin เดียวกัน)
    // API_PROXY_TARGET ใช้เมื่อ API ไม่ได้อยู่ที่พอร์ต 8000 (เช่น CI / tools/security-audit/ci.sh)
    proxy: { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000" },
  },
});
