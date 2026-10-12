import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// dev proxy → FastAPI (production ให้ reverse proxy เสิร์ฟ /api ใต้ origin เดียวกัน)
// API_PROXY_TARGET ใช้เมื่อ API ไม่ได้อยู่ที่พอร์ต 8000 (เช่น CI / tools/security-audit/ci.sh)
const apiProxy = { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000" };

// ไฟล์ใน public/ ไม่อยู่ใน bundle จึงต้องระบุเอง
const PUBLIC_SHELL = ["/manifest.webmanifest", "/icons/icon-192.png", "/icons/apple-touch-icon.png", "/icons/favicon-32.png"];

/** สร้าง /sw.js ตอน build: ใส่รายการไฟล์เปลือกแอปที่ต้องแคชล่วงหน้า + build id (เปลี่ยนทุก build → มือถือได้รับอัปเดต) */
function serviceWorker(): Plugin {
  return {
    name: "app-service-worker",
    apply: "build",
    generateBundle(_options, bundle) {
      const built = Object.keys(bundle).filter((f) => /\.(js|css|png|svg|woff2?)$/.test(f)).map((f) => `/${f}`);
      const precache = ["/index.html", ...PUBLIC_SHELL, ...built.sort()];
      const buildId = createHash("sha256").update(precache.join("\n")).digest("hex").slice(0, 12);
      const source = readFileSync(new URL("./src/sw.js", import.meta.url), "utf8")
        .replaceAll("__BUILD_ID__", buildId)
        .replaceAll("__PRECACHE__", JSON.stringify(precache));
      if (/__[A-Z]+__/.test(source)) this.error("sw.js: ยังมี placeholder ที่ไม่ถูกแทนค่า");
      this.emitFile({ type: "asset", fileName: "sw.js", source });
    },
  };
}

export default defineConfig(({ mode }) => mode === "demo"
  // เวอร์ชันสาธิตบนเว็บ (npm run build:demo): ไฟล์ JS ไฟล์เดียว + เซิร์ฟเวอร์จำลอง ไม่มี service worker
  ? {
      plugins: [react()],
      build: { outDir: "dist-demo", assetsInlineLimit: 1e7, rollupOptions: { output: { inlineDynamicImports: true } } },
    }
  : {
      plugins: [react(), serviceWorker()],
      server: { proxy: apiProxy },
      preview: { proxy: apiProxy },   // `vite preview` = ทดสอบแบบ production (มี service worker) บนมือถือ/เครื่องจำลอง
    });
