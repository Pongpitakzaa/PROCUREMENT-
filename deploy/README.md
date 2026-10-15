# การติดตั้งบนเซิร์ฟเวอร์จริง (Docker)

ระบบประกอบด้วย 3 คอนเทนเนอร์ ติดตั้งด้วยคำสั่งเดียว `./install.sh`

```
ผู้ใช้ (เว็บ/มือถือ) ──HTTPS 443──▶ web (Caddy) ──/api──▶ api (FastAPI) ──▶ db (PostgreSQL 16)
                                   │ หน้าเว็บ + ใบรับรอง    │ LibreOffice → PDF      │ เครือข่ายภายในเท่านั้น
                                   │ security headers      │ pg_dump สำรองข้อมูล     │ ไม่เปิดพอร์ตออกนอก
                                                           └──▶ LINE Messaging API (ถ้าใช้)
```

| ส่วน | รายละเอียด |
|---|---|
| `web` | Caddy: ขอ/ต่ออายุใบรับรอง HTTPS อัตโนมัติ, ส่ง http→https, HSTS/CSP, เสิร์ฟหน้าเว็บ (PWA) |
| `api` | FastAPI บน Ubuntu 24.04 + LibreOffice + ฟอนต์ไทย + PostgreSQL 16 client · รันด้วยผู้ใช้ที่ไม่ใช่ root, ระบบไฟล์อ่านอย่างเดียว |
| `db` | PostgreSQL 16 · แอปเชื่อมต่อด้วยบัญชี `proc_app` ที่ไม่ใช่ superuser |

## 1. สิ่งที่ต้องเตรียม

| รายการ | ข้อกำหนด |
|---|---|
| เซิร์ฟเวอร์ | Ubuntu Server 22.04/24.04 (หรือ Linux ที่รัน Docker ได้) · 2 vCPU · RAM 4 GB · ดิสก์ 40 GB ขึ้นไป |
| ซอฟต์แวร์ | Docker Engine 24+ พร้อม Docker Compose v2 (`docker compose version`), git, openssl |
| ชื่อโดเมน | เช่น `procurement.agency.go.th` ตั้ง DNS (A record) ชี้มาที่ IP เซิร์ฟเวอร์ |
| Firewall | เปิดขาเข้าเฉพาะ **80** และ **443** (TCP, และ UDP 443 สำหรับ HTTP/3) · SSH จำกัดเฉพาะเครือข่ายผู้ดูแล |
| ใบรับรอง HTTPS | เลือกอย่างใดอย่างหนึ่ง: **Let's Encrypt อัตโนมัติ** (โดเมนต้องเข้าถึงได้จากอินเทอร์เน็ตทางพอร์ต 80/443) หรือ **ใบรับรองของหน่วยงาน** (ไฟล์ `fullchain.pem` + `privkey.pem`) |

ติดตั้ง Docker บน Ubuntu (ตามเอกสารทางการ https://docs.docker.com/engine/install/ubuntu/):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # ออกจากระบบแล้วเข้าใหม่ 1 ครั้ง
```

## 2. ติดตั้ง

```bash
sudo mkdir -p /opt/procurement && sudo chown $USER /opt/procurement
git clone <URL ของ repository> /opt/procurement
cd /opt/procurement/deploy

# ถ้าใช้ใบรับรองของหน่วยงาน: วางไฟล์ก่อนติดตั้ง
#   cp fullchain.pem privkey.pem certs/ && chmod 600 certs/privkey.pem

sudo ./install.sh
```

สคริปต์จะถามชื่อโดเมนและวิธีออกใบรับรอง แล้วทำให้ทั้งหมด:

1. สร้าง `deploy/.env` พร้อม **ค่าลับสุ่มใหม่** (รหัสผ่านฐานข้อมูล, JWT, กุญแจเข้ารหัสข้อมูล, กุญแจไฟล์สำรอง) สิทธิ์ 600
2. สร้างโฟลเดอร์ข้อมูล `deploy/data/` (ฐานข้อมูล, แบบฟอร์ม, เอกสาร, ไฟล์สำรอง, ใบรับรอง)
3. build image และเปิดระบบ — ครั้งแรก PostgreSQL สร้าง schema และข้อมูลอ้างอิง (วิธีจัดหา, มาตรา 56, ขั้นตอน workflow) ให้อัตโนมัติ
4. รอจน API พร้อมใช้งาน

> ⚠️ **สำรองไฟล์ `deploy/.env` ไว้นอกเครื่องทันที** (เช่น ตู้เซฟดิจิทัล/USB เข้ารหัสที่ผู้บริหารเก็บ)
> ถ้ากุญแจ `PROC_DATA_KEYS` หรือ `PROC_BACKUP_KEY` สูญหาย จะถอดรหัสเลขประจำตัวประชาชน/บัญชีธนาคารในระบบ
> และไฟล์สำรองทั้งหมด**ไม่ได้อีกเลย**

ตรวจระบบหลังติดตั้ง:

```bash
./check.sh            # ผ่านโดเมนจริง (หลังตั้ง DNS แล้ว)
./check.sh --local    # ทดสอบที่เครื่องนี้ก่อนตั้ง DNS
```

ตรวจ 14 ข้อ: HTTPS, http→https, HSTS/CSP/X-Frame-Options, การ cache ของ service worker, API ต้องเข้าสู่ระบบ,
ไม่เปิดเอกสาร API, PostgreSQL ไม่เปิดพอร์ต, pg_dump รุ่น 16, LibreOffice, ฟอนต์ไทย, สิทธิ์เขียนโฟลเดอร์สำรอง

## 3. ตั้งค่าครั้งแรก

หน้าเว็บยังสร้างผู้ดูแลระบบคนแรกไม่ได้ (ต้องเข้าสู่ระบบก่อน) จึงใช้คำสั่งบนเซิร์ฟเวอร์:

```bash
cd /opt/procurement/deploy

# 1) หน่วยงาน (เพิ่มได้หลายหน่วยงาน)
docker compose exec api python -m app.cli add-department PSD "กองพัสดุ สำนักงาน..."

# 2) ผู้ดูแลระบบคนแรก — รหัสผ่านสุ่มแสดงบนจอครั้งเดียว
docker compose exec api python -m app.cli create-admin --username itadmin --department PSD \
    --title นาย --first-name สมชาย --last-name ใจดี --position "นักวิชาการคอมพิวเตอร์" --citizen-id 1234567890123
```

จากนั้นที่หน้าเว็บ `https://<โดเมน>`:

1. เข้าสู่ระบบด้วยบัญชีผู้ดูแล → เมนูชื่อผู้ใช้ → **เปลี่ยนรหัสผ่าน**
2. **ผู้ดูแลระบบ → ผู้ใช้งาน**: สร้างบัญชีเจ้าหน้าที่พัสดุ หัวหน้าเจ้าหน้าที่ ผู้บริหาร (ระบบสุ่มรหัสผ่านชั่วคราวให้)
   — ผู้ดูแลระบบควรเป็นคนละคนกับผู้ปฏิบัติงานจัดซื้อ (ระบบบังคับแยกบทบาท)
3. **ผู้ดูแลระบบ → แบบฟอร์มกรมบัญชีกลาง**: อัปโหลดแบบฟอร์มจาก gprocurement.go.th ตาม [docs/04-cgd-templates.md](../docs/04-cgd-templates.md)
   แล้วให้หัวหน้าเจ้าหน้าที่ (คนละคนกับผู้อัปโหลด) กดรับรอง
4. (ถ้าใช้ LINE) ใส่ `PROC_LINE_CHANNEL_ACCESS_TOKEN` และ `PROC_LINE_CHANNEL_SECRET` ใน `.env` → `./install.sh --no-build` → ตั้ง webhook และเชิญบอทเข้ากลุ่มตาม [LINE.md](LINE.md)

### ฟอนต์ TH Sarabun (แนะนำ)

แบบฟอร์มกรมบัญชีกลางใช้ฟอนต์ TH SarabunPSK / TH Sarabun New ระบบมีฟอนต์ **Laksaman** ซึ่งขนาดตัวอักษรเท่ากันไว้แทนแล้ว
ถ้าต้องการฟอนต์ตัวจริงในไฟล์ PDF ให้ดาวน์โหลด TH Sarabun New (ฟอนต์แห่งชาติ แจกฟรี) แล้ว:

```bash
cp THSarabunNew*.ttf /opt/procurement/deploy/fonts/
docker compose restart api
```

## 4. สำรองข้อมูล

### สำรองอัตโนมัติทุกวัน (ต้องตั้ง)

ไฟล์สำรองเข้ารหัส AES-256-GCM เก็บใน `deploy/data/storage/backups/` และกู้คืนได้จากหน้า **ผู้ดูแลระบบ → สำรอง/กู้คืนข้อมูล**

```bash
sudo crontab -e
# ทุกวัน 01:30 น. เก็บไฟล์อัตโนมัติ 30 วัน (ไฟล์ที่ผู้ดูแลสั่งสำรองเองจากหน้าเว็บไม่ถูกลบ)
30 1 * * * cd /opt/procurement/deploy && docker compose exec -T api python -m app.cli backup --keep-days 30 >> /var/log/procurement-backup.log 2>&1
```

### เก็บสำเนานอกเครื่อง (กฎ 3-2-1)

ไฟล์สำรองในเครื่องเดียวกันไม่ช่วยถ้าดิสก์เสียหรือเครื่องถูกโจมตี — คัดลอกไปเครื่องอื่นทุกวัน เช่น NAS ของหน่วยงาน:

```bash
45 1 * * * rsync -a /opt/procurement/deploy/data/storage/backups/ backup@nas.agency.local:/backup/procurement/
```

ไฟล์สำรองเข้ารหัสแล้ว เก็บนอกเครื่องได้ปลอดภัย — **แต่ต้องเก็บ `.env` แยกที่จากไฟล์สำรองเสมอ**

### กู้คืนบนเครื่องใหม่ (กรณีเครื่องเดิมเสีย)

1. ติดตั้งเครื่องใหม่ตามข้อ 1–2 **โดยวางไฟล์ `.env` เดิมไว้ใน `deploy/` ก่อนรัน `./install.sh`** (ใช้กุญแจชุดเดิม)
2. คัดลอกไฟล์สำรอง (`*.dump.enc` และ `*.dump.enc.json` คู่กัน) ไปไว้ที่ `deploy/data/storage/backups/`
   แล้ว `sudo chown 10001:10001 deploy/data/storage/backups/*`
3. สร้างผู้ดูแลชั่วคราวด้วย `create-admin` → เข้าเว็บ → **ผู้ดูแลระบบ → สำรอง/กู้คืนข้อมูล** → เลือกไฟล์ → กู้คืน
4. ข้อมูลผู้ใช้กลับเป็นชุดเดิมทั้งหมด (บัญชีผู้ดูแลชั่วคราวหายไปพร้อมการกู้คืน)

ควร**ซ้อมกู้คืน**บนเครื่องทดสอบอย่างน้อยปีละ 2 ครั้ง

## 5. อัปเดตระบบ

```bash
cd /opt/procurement
git pull
cd deploy
docker compose exec -T api python -m app.cli backup     # สำรองก่อนอัปเดตทุกครั้ง
sudo ./install.sh                                       # build ใหม่และเปิดระบบ (ไม่ทับ .env และข้อมูล)
./check.sh
```

ผู้ใช้มือถือ/แอป PWA จะเห็นแถบ "มีระบบเวอร์ชันใหม่" ให้กดอัปเดตเอง

> **ข้อจำกัดปัจจุบัน:** `database/schema.sql` ใช้ตอนสร้างฐานข้อมูลครั้งแรกเท่านั้น
> หากเวอร์ชันใหม่เปลี่ยนโครงสร้างฐานข้อมูล ต้องมีสคริปต์ migration แยก (ยังไม่มีเครื่องมือ migration ในโครงการ)

## 6. เซิร์ฟเวอร์ที่ไม่มีอินเทอร์เน็ต / ผ่าน proxy ของหน่วยงาน

| สถานการณ์ | วิธี |
|---|---|
| ออกอินเทอร์เน็ตผ่าน SSL inspection proxy | วางใบรับรอง CA ขององค์กร (`*.crt`) ใน `deploy/extra-ca/` ก่อน `./install.sh` |
| ต้องใช้ Ubuntu mirror ภายใน | ตั้ง `UBUNTU_MIRROR=https://mirror.agency.go.th/ubuntu` ใน `.env` |
| ไม่มีอินเทอร์เน็ตเลย (air-gapped) | build บนเครื่องที่มีอินเทอร์เน็ต แล้วย้าย image: |

```bash
# เครื่องที่มีอินเทอร์เน็ต (โฟลเดอร์ deploy เดียวกัน)
docker compose build
docker save procurement-api:latest procurement-web:latest postgres:16-bookworm -o procurement-images.tar

# เซิร์ฟเวอร์ปลายทาง
docker load -i procurement-images.tar
sudo ./install.sh --no-build
```

กรณีไม่มีอินเทอร์เน็ตต้องใช้ใบรับรองของหน่วยงาน (Let's Encrypt ใช้ไม่ได้) และฟังก์ชันส่ง LINE จะใช้ไม่ได้

## 7. คำสั่งดูแลประจำ

| งาน | คำสั่ง (ใน `/opt/procurement/deploy`) |
|---|---|
| สถานะ | `docker compose ps` |
| ดู log | `docker compose logs -f api` (log หมุนเวียนอัตโนมัติ 10 ไฟล์ × 20 MB ต่อบริการ) |
| ผู้ดูแลลืมรหัสผ่าน / ถูกล็อก | `docker compose exec api python -m app.cli reset-password itadmin` |
| เพิ่มหน่วยงาน | `docker compose exec api python -m app.cli add-department CODE "ชื่อ"` |
| รีสตาร์ต | `docker compose restart` (ใช้ค่าเดิมของคอนเทนเนอร์ ปลอดภัย) |
| หยุดระบบ | `docker compose down` (ข้อมูลอยู่ใน `data/` ไม่หาย) |
| ตรวจความถูกต้อง audit log | หน้า **ผู้ดูแลระบบ → Audit Log → ตรวจสอบความถูกต้อง** |

> **เปิด/สร้างคอนเทนเนอร์ใหม่ด้วย `./install.sh --no-build` เสมอ** (แทน `docker compose up`):
> Docker Compose ให้ตัวแปรที่ export ไว้ใน shell (เช่น `PROC_BACKUP_KEY`) ทับค่าใน `.env`
> ถ้าเผลอมีค่าค้างอยู่ API จะได้กุญแจผิดชุดและถอดรหัสข้อมูล/ไฟล์สำรองเดิมไม่ได้ — `install.sh` ล้างตัวแปรเหล่านี้ให้ก่อน

## 8. รายการตรวจความปลอดภัยก่อนเปิดใช้งาน

- [ ] `./check.sh` ผ่านทุกข้อผ่านโดเมนจริง
- [ ] เปิด firewall เฉพาะ 80/443 · SSH ใช้ key และจำกัด IP
- [ ] สำรอง `.env` ไว้นอกเครื่องแล้ว และ**ไม่ได้**เก็บไว้ที่เดียวกับไฟล์สำรอง
- [ ] ตั้ง cron สำรองรายวัน + คัดลอกนอกเครื่อง และทดลองกู้คืนบนเครื่องทดสอบแล้ว
- [ ] ผู้ดูแลคนแรกเปลี่ยนรหัสผ่านแล้ว · ผู้ดูแลระบบไม่ได้ถือบทบาทจัดซื้อ
- [ ] แบบฟอร์มทุกฉบับมาจาก gprocurement.go.th และรับรองโดยผู้ที่ไม่ใช่ผู้อัปโหลด
- [ ] อัปเดต OS (`unattended-upgrades`) และอัปเดต image ตามรอบ (`./install.sh` ดึง base image ล่าสุดทุกครั้ง)
- [ ] แจ้งเจ้าหน้าที่คุ้มครองข้อมูลส่วนบุคคล (DPO) ถึงที่ตั้งเซิร์ฟเวอร์และระยะเวลาเก็บไฟล์สำรอง

## CI: ตรวจชุดติดตั้งทุก Pull Request

`.github/workflows/docker-build.yml` build image ทั้งสอง (มี layer cache) แล้วรัน `ci-smoke.sh` บน runner:
`install.sh` (ใบรับรองชั่วคราว) → `check.sh` 14 ข้อ → สร้างผู้ดูแลด้วย CLI → เข้าสู่ระบบผ่าน HTTPS → สำรองข้อมูลด้วย CLI
ถ้าไม่ผ่าน job จะแสดง log ของคอนเทนเนอร์ให้ดูต่อท้าย

รันเองบนเครื่องทดสอบ (ห้ามรันบนเซิร์ฟเวอร์จริง — สคริปต์จะหยุดถ้าพบ `.env` หรือฐานข้อมูลเดิม):

```bash
cd deploy && docker compose build && sudo ./ci-smoke.sh
```

## ไฟล์ในโฟลเดอร์นี้

| ไฟล์ | หน้าที่ |
|---|---|
| `install.sh` | ติดตั้ง/อัปเดต (สร้าง `.env`, โฟลเดอร์ข้อมูล, build, เปิดระบบ) |
| `check.sh` | ตรวจระบบหลังติดตั้ง |
| `ci-smoke.sh` | ทดสอบชุดติดตั้งครบวงจร (ใช้ใน GitHub Actions) |
| `docker-compose.yml` | นิยามบริการ เครือข่าย และสิทธิ์ของคอนเทนเนอร์ |
| `../Dockerfile` (รากของ repo) / `web.Dockerfile` | image ของ API (+หน้าเว็บสำหรับ Render) และหน้าเว็บ (Caddy) |
| `Caddyfile` | HTTPS, reverse proxy, security headers, cache |
| `db-init/00-create-app-db.sh` | สร้างบัญชี `proc_app` + schema ครั้งแรก |
| `.env.example` | ตัวอย่างค่าตั้ง (ใช้ `install.sh` สร้าง `.env` จริง) |
| `extra-ca/` `fonts/` `certs/` | CA องค์กร · ฟอนต์เพิ่มเติม · ใบรับรองของหน่วยงาน |
