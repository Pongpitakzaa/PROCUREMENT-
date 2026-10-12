# 5. การใช้งานบน iOS และ Android

ระบบเปิดใช้บนมือถือ/แท็บเล็ตได้ 2 แบบ โดยใช้โค้ดชุดเดียวกับเว็บ (ไม่ต้องดูแลแอปแยก)

| แบบ | วิธี | เหมาะกับ |
|---|---|---|
| เว็บบนมือถือ | เปิด URL ของระบบใน Safari / Chrome | ใช้ชั่วคราว |
| **ติดตั้งเป็นแอป (PWA)** | เพิ่มไอคอน "จัดซื้อจัดจ้าง" ลงหน้าจอโฮม → เปิดเต็มจอเหมือนแอป | ผู้ใช้ประจำ (ผู้บริหารอนุมัติ, เจ้าหน้าที่ตรวจสถานะ) |

แบบ PWA ไม่ต้องผ่าน App Store / Google Play และอัปเดตทันทีเมื่อเผยแพร่เวอร์ชันใหม่บนเซิร์ฟเวอร์

## วิธีติดตั้ง

- **Android (Chrome / Edge / Samsung Internet)**: เข้าสู่ระบบแล้วกดชื่อผู้ใช้ → **📲 ติดตั้งแอปบนมือถือ** (หรือกดปุ่มเดียวกันที่หน้าเข้าสู่ระบบ) → **ติดตั้ง**
- **iPhone / iPad (Safari)**: iOS ไม่มีปุ่มติดตั้งอัตโนมัติ ระบบจึงแสดงขั้นตอนให้: ปุ่ม **แชร์** → **เพิ่มไปยังหน้าจอโฮม** → **เพิ่ม**

## สิ่งที่ปรับให้เหมาะกับมือถือ

| เรื่อง | การทำงาน | ไฟล์ |
|---|---|---|
| Web App Manifest | ชื่อแอปภาษาไทย, เปิดแบบ standalone, ไอคอน 192/512 + maskable (Android) + apple-touch-icon (iOS) | `frontend/public/manifest.webmanifest`, `frontend/scripts/gen_icons.py` |
| Service worker | แคชเฉพาะ **เปลือกแอป** (HTML/JS/CSS/ไอคอน/ฟอนต์) → เปิดเร็วและเปิดได้แม้สัญญาณขาด | `frontend/src/sw.js` (สร้างเป็น `/sw.js` ตอน build โดย plugin ใน `vite.config.ts`) |
| อัปเดตเวอร์ชัน | แจ้ง "มีระบบเวอร์ชันใหม่" ให้ผู้ใช้กดเอง — **ไม่สลับเวอร์ชันกลางคัน**ขณะกรอกฟอร์ม | `frontend/src/pwa.ts` |
| ออฟไลน์ | แถบแจ้งออฟไลน์ และข้อความภาษาไทย "ข้อมูลยังไม่ถูกบันทึก" แทน `Failed to fetch` | `frontend/src/api.ts`, `components/MobileApp.tsx` |
| รอยบาก / Dynamic Island / แถบ Home | `viewport-fit=cover` + `env(safe-area-inset-*)` | `styles.css` |
| จอสัมผัส | ปุ่ม/ช่องกรอกสูง ≥ 44px (Apple HIG, WCAG 2.5.5) · ตัวอักษรในช่องกรอก 16px (กัน iOS ซูมเองเมื่อแตะช่อง) | `styles.css` (`@media (pointer: coarse)`) |
| ดาวน์โหลดเอกสาร | ไม่ revoke blob ทันที (iOS Safari อ่านไฟล์แบบ async) → เปิดหน้าตัวอย่าง/บันทึกลง Files ได้ | `frontend/src/api.ts` |

## ความปลอดภัยและ PDPA บนมือถือ

- service worker **ไม่แตะ `/api/*`** — ข้อมูลโครงการ ผู้ประกอบการ บุคลากร และไฟล์เอกสาร **ไม่ถูกแคชลงเครื่อง**
  (สอดคล้อง `Cache-Control: no-store` ของ API) มือถือหายหรือใช้เครื่องร่วมกันก็ไม่มีข้อมูลราชการค้างอยู่
- token เก็บในหน่วยความจำเท่านั้น (ไม่ใช้ localStorage) — iOS/Android ปิดแอปที่อยู่เบื้องหลังเมื่อหน่วยความจำไม่พอ
  ผู้ใช้จึงต้องเข้าสู่ระบบใหม่เมื่อเปิดแอปอีกครั้ง **เป็นความตั้งใจ** ไม่ใช่ข้อผิดพลาด
- โหมดออฟไลน์เปิดได้เฉพาะหน้าจอแอป **ไม่รองรับการบันทึกข้อมูลออฟไลน์** — ข้อมูลจัดซื้อจัดจ้างต้องผ่านการตรวจของเซิร์ฟเวอร์และบันทึก audit log ทันที

## ข้อกำหนดการติดตั้งเซิร์ฟเวอร์ (production)

1. **ต้องเป็น HTTPS** — iOS/Android ติดตั้ง PWA และเปิด service worker ได้เฉพาะ HTTPS (ยกเว้น `localhost`)
2. เสิร์ฟ `/sw.js` และ `/manifest.webmanifest` ด้วย `Cache-Control: no-cache` (ให้มือถือเห็นเวอร์ชันใหม่ทันที)
   และ `/assets/*` ด้วย `Cache-Control: public, max-age=31536000, immutable` (ชื่อไฟล์มี hash)
3. CSP ของหน้าเว็บ: `default-src 'self'` ครอบคลุม service worker/manifest แล้ว — ถ้าใช้ฟอนต์ Google
   เพิ่ม `style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com`

ตัวอย่าง nginx:

```nginx
location = /sw.js                { add_header Cache-Control "no-cache"; try_files $uri =404; }
location = /manifest.webmanifest { add_header Cache-Control "no-cache"; try_files $uri =404; }
location /assets/                { add_header Cache-Control "public, max-age=31536000, immutable"; }
location /api/                   { proxy_pass http://127.0.0.1:8000; }
location /                       { try_files $uri /index.html; }
```

## ทดสอบบนเครื่องจำลอง

service worker ทำงานเฉพาะ production build (ตอน `npm run dev` ปิดไว้เพื่อไม่ให้รบกวน HMR):

```bash
cd frontend && npm run build && npx vite preview --host   # proxy /api → :8000 เหมือน dev
```

เปิด `http://<IP เครื่อง>:4173` จากมือถือในวง LAN ได้เพื่อดูหน้าตา (การติดตั้งเป็นแอปต้องใช้ HTTPS ตามข้อ 1)

ผลทดสอบด้วย Playwright (จำลอง iPhone 13, iPhone SE, Pixel 7) ผ่านทุกข้อ ได้แก่
manifest และไอคอนครบ, service worker ติดตั้งและควบคุมหน้า, ติดตั้งครั้งแรกไม่ทำให้ฟอร์มที่กรอกหาย, ขนาดเป้าหมายแตะ ≥ 44px / ตัวอักษร 16px,
ปุ่มติดตั้ง (Android prompt / วิธีติดตั้งบน iOS), ทุกหน้าไม่ล้นจอแนวนอน, แคชไม่มีข้อมูล `/api`,
เปิดได้ขณะออฟไลน์ และอัปเดตเวอร์ชันใหม่แล้วลบแคชเก่า

## ทางเลือก: แอปใน App Store / Google Play

ถ้าหน่วยงานต้องการแจกจ่ายผ่าน store (เช่น MDM ของหน่วยงาน) ใช้ [Capacitor](https://capacitorjs.com/) ห่อ `frontend/dist`
เป็นแอป native ได้โดยไม่ต้องแก้โค้ด — ต้องมีบัญชี Apple Developer / Google Play Console และเครื่อง macOS + Xcode สำหรับ build iOS
