// รวม dist-demo/ เป็นหน้า HTML ไฟล์เดียว (CSS + JS inline) สำหรับเผยแพร่เป็นเว็บสาธิต
// ใช้: npm run build:demo  → dist-demo/procurement-demo.html
import { readFileSync, writeFileSync } from "node:fs";
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
