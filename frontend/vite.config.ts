import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // dev proxy → FastAPI (production ให้ reverse proxy เสิร์ฟ /api ใต้ origin เดียวกัน)
    proxy: { "/api": "http://localhost:8000" },
  },
});
