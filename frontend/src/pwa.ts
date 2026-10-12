/** ใช้งานแบบแอปบน iOS / Android (Progressive Web App)
 *
 * - ลงทะเบียน service worker (เฉพาะ production build — ตอน dev ปล่อยให้ Vite HMR ทำงานปกติ)
 * - ปุ่ม "ติดตั้งแอป": Android/Chrome ใช้ beforeinstallprompt, iOS Safari ไม่มี API นี้ → แสดงวิธี "เพิ่มไปยังหน้าจอโฮม"
 * - แจ้งเมื่อออฟไลน์ และเมื่อมีเวอร์ชันใหม่ (ผู้ใช้เป็นคนกดอัปเดต ไม่สลับเวอร์ชันกลางคันขณะกรอกฟอร์ม)
 */
import { useSyncExternalStore } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export type InstallMode = "prompt" | "ios" | "none";

interface PwaState {
  install: InstallMode;
  online: boolean;
  updateReady: boolean;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let waitingWorker: ServiceWorker | null = null;
let updateRequested = false;
let state: PwaState = { install: "none", online: true, updateReady: false };
const listeners = new Set<() => void>();

function set(patch: Partial<PwaState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

/** เปิดจากไอคอนบนหน้าจอโฮมแล้ว (ไม่ต้องเสนอให้ติดตั้งซ้ำ) */
export function isStandalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

/** iPhone/iPad (รวม iPadOS ที่รายงานตัวเป็น Mac) — ทุกเบราว์เซอร์บน iOS ใช้ WebKit และติดตั้งผ่านเมนูแชร์เท่านั้น */
export function isIos(ua = navigator.userAgent, platform = navigator.platform, touchPoints = navigator.maxTouchPoints): boolean {
  return /iPad|iPhone|iPod/.test(ua) || (platform === "MacIntel" && touchPoints > 1);
}

export function initPwa(): void {
  set({
    online: navigator.onLine,
    install: isStandalone() ? "none" : isIos() ? "ios" : "none",
  });
  window.addEventListener("online", () => set({ online: true }));
  window.addEventListener("offline", () => set({ online: false }));
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();               // ไม่ให้เบราว์เซอร์เด้งแถบติดตั้งเอง — แสดงในเมนูผู้ใช้แทน
    deferredPrompt = e as BeforeInstallPromptEvent;
    set({ install: "prompt" });
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    set({ install: "none" });
  });

  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").then((reg) => {
      const watch = (w: ServiceWorker | null) => {
        if (!w) return;
        w.addEventListener("statechange", () => {
          // installed + มี controller เดิม = เวอร์ชันใหม่รออยู่ (ครั้งแรกที่ติดตั้งไม่ต้องแจ้ง)
          if (w.state === "installed" && navigator.serviceWorker.controller) {
            waitingWorker = w;
            set({ updateReady: true });
          }
        });
      };
      if (reg.waiting && navigator.serviceWorker.controller) {
        waitingWorker = reg.waiting;
        set({ updateReady: true });
      }
      reg.addEventListener("updatefound", () => watch(reg.installing));
    }).catch(() => undefined);   // ไม่มี service worker แอปก็ยังใช้งานได้ตามปกติ
    // โหลดใหม่เฉพาะเมื่อผู้ใช้กด "อัปเดต" — ตอนติดตั้งครั้งแรก clients.claim() ก็ทำให้เกิด controllerchange
    // ถ้าโหลดใหม่ทุกครั้ง ฟอร์มที่กำลังกรอก (เช่น หน้าเข้าสู่ระบบ) จะหายไปเอง
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (updateRequested) {
        updateRequested = false;
        window.location.reload();
      }
    });
  });
}

/** Android/Chrome: เปิดหน้าต่างติดตั้งของระบบ · คืน false ถ้าเรียกไม่ได้ (เช่น iOS) */
export async function promptInstall(): Promise<boolean> {
  if (!deferredPrompt) return false;
  const e = deferredPrompt;
  deferredPrompt = null;
  await e.prompt();
  const { outcome } = await e.userChoice;
  set({ install: "none" });
  return outcome === "accepted";
}

/** ใช้เวอร์ชันใหม่ (โหลดหน้าใหม่หลัง service worker ใหม่เข้าควบคุม) */
export function applyUpdate(): void {
  if (!waitingWorker) return;
  updateRequested = true;
  waitingWorker.postMessage("SKIP_WAITING");
}

export function usePwa(): PwaState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
  );
}
