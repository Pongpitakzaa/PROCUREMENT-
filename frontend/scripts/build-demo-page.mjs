// รวม dist-demo/ เป็นหน้า HTML ไฟล์เดียว (CSS + JS inline) สำหรับเผยแพร่เป็นเว็บทดลอง
// ใช้: npm run build:demo
//   → dist-demo/procurement-demo.html   ส่วนเนื้อหา (ไม่มี <html>/<head>) สำหรับ Claude Artifact
//   → ../docs/app/index.html            หน้าเว็บเต็มสำหรับ GitHub Pages (https://<owner>.github.io/<repo>/app/)
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dir = new URL("../dist-demo/", import.meta.url).pathname;
const html = readFileSync(join(dir, "index.html"), "utf8");
const asset = (re) => {
  const m = re.exec(html);
  if (!m) throw new Error(`ไม่พบ ${re}`);
  return readFileSync(join(dir, m[1]), "utf8");
};
const css = asset(/<link rel="stylesheet"[^>]*href="\/([^"]+\.css)"/);
const js = asset(/<script type="module"[^>]*src="\/([^"]+\.js)"/);

const script = js.replaceAll("</script", "<\\/script");
const fonts = `<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700&display=swap" />`;

const page = `<title>ระบบจัดซื้อจัดจ้างภาครัฐ</title>
<meta name="description" content="เวอร์ชันสาธิต ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700&display=swap" />
<style>${css}</style>
<div id="root"></div>
<script type="module">${js.replaceAll("</script", "<\\/script")}</script>
`;
writeFileSync(join(dir, "procurement-demo.html"), page);
console.log(`dist-demo/procurement-demo.html ${(page.length / 1024).toFixed(0)} KB`);

const pagesHtml = `<!doctype html>
<html lang="th">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="theme-color" content="#ffffff" />
<title>ระบบจัดซื้อจัดจ้างภาครัฐ (ทดลองใช้งาน)</title>
<meta name="description" content="ทดลองใช้งานระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ ด้วยข้อมูลตัวอย่าง" />
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M8 1l7 7-7 7-7-7z' fill='%232563eb'/%3E%3C/svg%3E" />
${fonts}
<style>${css}</style>
</head>
<body>
<div id="root"></div>
<script type="module">${script}</script>
</body>
</html>
`;
const pagesDir = new URL("../../docs/app/", import.meta.url).pathname;
mkdirSync(pagesDir, { recursive: true });
writeFileSync(join(pagesDir, "index.html"), pagesHtml);
console.log(`docs/app/index.html ${(pagesHtml.length / 1024).toFixed(0)} KB`);
