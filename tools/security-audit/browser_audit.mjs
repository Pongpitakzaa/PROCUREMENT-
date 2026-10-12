/**
 * กลุ่ม D: ตรวจในเบราว์เซอร์จริง — XSS, การเก็บ token, การตรวจฝั่ง client ก่อนส่ง
 * ต้องเปิด frontend (AUDIT_WEB_URL) และ API (AUDIT_API_URL) ไว้ · รวมผลเข้า $AUDIT_OUT/results.json
 * ใช้ Chromium ของเครื่องได้ด้วย CHROMIUM_PATH (ไม่งั้นใช้ของ Playwright: npx playwright install chromium)
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const API = (process.env.AUDIT_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const WEB = (process.env.AUDIT_WEB_URL ?? "http://localhost:5173").replace(/\/$/, "");
const OUT = process.env.AUDIT_OUT ?? path.join(path.dirname(new URL(import.meta.url).pathname), "out");
const PW = process.env.AUDIT_PASSWORD;
if (!PW) { console.error("ต้องตั้ง AUDIT_PASSWORD"); process.exit(2); }
if (process.env.AUDIT_ALLOW_UNSAFE_TARGET !== "1") {
  for (const u of [API, WEB]) {
    if (!["localhost", "127.0.0.1", "[::1]"].includes(new URL(u).hostname)) {
      console.error(`หยุด: ${u} ไม่ใช่ localhost (ตั้ง AUDIT_ALLOW_UNSAFE_TARGET=1 ถ้าแน่ใจว่าเป็นระบบทดสอบ)`); process.exit(2);
    }
  }
}

const CAT = "D. หน้าเว็บ (เบราว์เซอร์จริง)";
const res = [];
const check = (name, expected, ok, actual) => {
  res.push({ cat: CAT, name, expected, ok: !!ok, actual });
  console.log(`${ok ? "PASS" : "FAIL"}  [D] ${name} → ${actual}`);
};
const api = async (p, token, body) => {
  const r = await fetch(`${API}${p}`, { method: body ? "POST" : "GET",
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  return r.json();
};
const tax = (b) => { let s = 0; for (let i = 0; i < 12; i++) s += +b[i] * (13 - i); return b + ((11 - (s % 11)) % 10); };
const stamp = String(Date.now()).slice(-6);

// ข้อมูลอันตรายใส่ผ่าน API โดยตรง (ข้ามการตรวจของหน้าเว็บ)
const t = (await api("/api/auth/login", null, { username: "officer", password: PW })).access_token;
const dept = (await api("/api/departments", t))[0].department_id;
await api("/api/vendors", t, { tax_id: tax("01055" + stamp + "7"), vendor_type: "JURISTIC",
  name_th: `[ทดสอบXSS] <img src=x onerror="window.__xss='vendor'"><script>window.__xss='script'</script>`,
  address_th: `<svg onload="window.__xss='addr'">` });
const methods = await api("/api/methods", t);
const j = methods.find((m) => m.code === "SPECIFIC").justifications.find((x) => x.clause_ref === "มาตรา 56(2)(ข)").id;
await api("/api/projects", t, { project_code: `XSS-${stamp}`, fiscal_year_be: 2570,
  title_th: `[ทดสอบXSS] <img src=x onerror="window.__xss='project'">`, reason_th: "x", department_id: dept,
  method_code: "SPECIFIC", justification_id: j, procurement_type: "GOODS", budget_amount: "1000.00", delivery_days: 1,
  items: [{ description: "x", quantity: "1", unit_th: "x", unit_price: "1000" }] });

const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(exe
  ? { executablePath: exe, headless: false, args: ["--no-sandbox", "--headless=new"] }
  : { args: ["--no-sandbox"] });
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
let dialogs = 0;
page.on("dialog", (d) => { dialogs++; d.dismiss(); });
const sent = [];
page.on("request", (r) => r.method() !== "GET" && sent.push(`${r.method()} ${new URL(r.url()).pathname}`));
const xss = () => page.evaluate(() => window.__xss);

await page.goto(WEB);
await page.fill("#username", "officer");
await page.fill("#password", PW);
await page.click("button[type=submit]");
await page.waitForSelector(".project-row");

await page.fill('input[aria-label="ค้นหา"]', "ทดสอบXSS");
await page.waitForTimeout(800);
const listText = await page.locator(".project-row").first().innerText();
check("XSS ในชื่อโครงการ (หน้ารายการ)", "แสดงเป็นข้อความ ไม่รันสคริปต์", listText.includes("<img src=x") && !(await xss()), `__xss=${await xss()}`);
await page.click(".project-row >> nth=0");
await page.waitForSelector(".project-head h2");
const imgs = await page.locator(".project-head img").count();
check("XSS ในชื่อโครงการ (หน้ารายละเอียด)", "ไม่มี element ถูกฉีด", imgs === 0 && !(await xss()), `img=${imgs}, __xss=${await xss()}`);

await page.click('.nav button:has-text("ผู้ประกอบการ")');
await page.fill('input[aria-label="ค้นหา"]', "ทดสอบXSS");
await page.waitForTimeout(800);
await page.click(".vendor-row >> nth=0");
await page.waitForSelector(".vendor-detail .info-list");
const injected = await page.evaluate(() =>
  document.querySelectorAll(".vendor-list img, .vendor-detail img, .vendor-detail svg, script:not([type=module])").length);
check("XSS ในชื่อ/ที่อยู่ผู้ประกอบการ", "ไม่มี element ถูกฉีด ไม่มี alert", injected === 0 && dialogs === 0 && !(await xss()),
      `injected=${injected}, dialogs=${dialogs}`);

const storage = await page.evaluate(() => JSON.stringify({ ls: { ...localStorage }, ss: { ...sessionStorage }, cookie: document.cookie }));
check("Access token ไม่เก็บใน localStorage/sessionStorage/cookie", "ว่าง", !/eyJ/.test(storage), storage);

sent.length = 0;
await page.click('.nav button:has-text("สร้างโครงการ")');
await page.waitForSelector("#p-project_code");
await page.fill("#p-project_code", `CLI-${stamp}`);
await page.fill("#p-title_th", "ทดสอบฝั่ง client");
await page.fill("#p-reason_th", "x");
await page.click('.method-card:has-text("วิธีเฉพาะเจาะจง")');
const opts = await page.$$eval("#p-justification_id option", (o) => o.map((x) => [x.value, x.textContent]));
await page.selectOption("#p-justification_id", opts.find(([, tx]) => tx.includes("56(2)(ข)"))[0]);
await page.fill("#p-budget_amount", "600000");
await page.fill('[aria-label="รายละเอียด รายการที่ 1"]', "x");
await page.fill('[aria-label="จำนวน รายการที่ 1"]', "1");
await page.fill('[aria-label="หน่วย รายการที่ 1"]', "ชุด");
await page.fill('[aria-label="ราคาต่อหน่วย รายการที่ 1"]', "600000");
await page.click("button.submit");
const budgetErr = await page.locator(".field.has-error .error").first().innerText().catch(() => "");
check("ฟอร์มโครงการ: วงเงิน 600,000 ตาม 56(2)(ข)", "แจ้งทันที ไม่ส่งไปเซิร์ฟเวอร์",
      !sent.some((p) => p.includes("/api/projects")) && budgetErr.includes("เกินเพดาน"), `"${budgetErr}" · requests: ${sent.join(", ") || "ไม่มี"}`);

sent.length = 0;
await page.click('.nav button:has-text("ผู้ประกอบการ")');
await page.click("text=+ ลงทะเบียนผู้ประกอบการ");
await page.fill("#v-tax_id", "0105536092642");
await page.fill("#v-name_th", "x");
await page.fill("#v-address_th", "x");
await page.click(".vendor-form button[type=submit]");
const taxErr = await page.locator(".vendor-form .error").first().innerText();
check("ฟอร์มผู้ประกอบการ: เลขผู้เสียภาษี checksum ผิด", "แจ้งผิด ไม่ส่งไปเซิร์ฟเวอร์",
      !sent.some((p) => p.includes("/api/vendors")) && taxErr.includes("checksum"), `"${taxErr}"`);

fs.mkdirSync(OUT, { recursive: true });
await page.screenshot({ path: path.join(OUT, "client-validation.png"), fullPage: true });
await browser.close();

const file = path.join(OUT, "results.json");
const all = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { results: [] };
all.results = all.results.filter((r) => r.cat !== CAT).concat(res);
fs.writeFileSync(file, JSON.stringify(all, null, 1));
const failed = res.filter((r) => !r.ok).length;
console.log(`\nD: ${res.length - failed}/${res.length} ผ่าน`);
process.exit(failed ? 1 : 0);
