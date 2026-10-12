import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initPwa } from "./pwa";
import "./styles.css";

async function start() {
  // เวอร์ชันสาธิตบนเว็บ: ใช้เซิร์ฟเวอร์จำลองในเบราว์เซอร์ (build ปกติตัดโค้ดส่วนนี้ทิ้งทั้งหมด)
  if (import.meta.env.VITE_DEMO === "1") (await import("./demo/mockServer")).installMockServer();
  else initPwa();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
void start();
