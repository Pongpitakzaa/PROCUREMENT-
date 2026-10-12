/* Service worker ของแอป — ถูก build เป็น /sw.js โดย plugin ใน vite.config.ts (ใส่ build id และรายการไฟล์ที่ต้องแคชล่วงหน้า)
 *
 * นโยบายแคช (สอดคล้อง Cache-Control: no-store ของ API และ พ.ร.บ.คุ้มครองข้อมูลส่วนบุคคล):
 *   - แคชเฉพาะ "เปลือกแอป" (HTML/JS/CSS/ไอคอน/ฟอนต์) เพื่อให้เปิดแอปได้เร็วและเปิดได้แม้สัญญาณขาด
 *   - ไม่แตะ /api/* เด็ดขาด — ข้อมูลโครงการ ผู้ประกอบการ บุคลากร และไฟล์เอกสาร ไม่ถูกเก็บลงเครื่อง
 *     (มือถือหาย/ใช้เครื่องร่วมกัน → ไม่มีข้อมูลราชการค้างในแคช)
 */
const BUILD_ID = "__BUILD_ID__";
const SHELL = `shell-${BUILD_ID}`;
const FONTS = "fonts-v1";
const PRECACHE = __PRECACHE__;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)));
  // ไม่ skipWaiting อัตโนมัติ: รอให้ผู้ใช้กด "อัปเดต" — ไม่สลับเวอร์ชันกลางคันขณะกรอกฟอร์ม
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== FONTS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/api/")) return;          // ปล่อยผ่านเครือข่ายตรง ไม่แคช
    if (req.mode === "navigate") {
      // network-first: ออนไลน์ได้หน้าล่าสุดเสมอ, ออฟไลน์ใช้เปลือกแอปที่แคชไว้
      event.respondWith(fetch(req).catch(() => caches.match("/index.html", { cacheName: SHELL })));
      return;
    }
    // ไฟล์ใน /assets/ มี hash ในชื่อ (ไม่เปลี่ยนเนื้อหา) → cache-first ปลอดภัย
    event.respondWith(caches.match(req, { cacheName: SHELL }).then((hit) => hit ?? fetch(req)));
    return;
  }

  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    // ฟอนต์ Sarabun: stale-while-revalidate
    event.respondWith(
      caches.open(FONTS).then(async (cache) => {
        const hit = await cache.match(req);
        const refresh = fetch(req).then((res) => {
          if (res.ok || res.type === "opaque") cache.put(req, res.clone());
          return res;
        });
        if (hit) {
          event.waitUntil(refresh.catch(() => undefined));
          return hit;
        }
        return refresh;
      }),
    );
  }
});
