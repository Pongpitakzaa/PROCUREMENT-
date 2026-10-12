"""สร้างรายงาน HTML จาก $AUDIT_OUT/results.json → $AUDIT_OUT/report.html (ไฟล์เดียว เปิดได้ทุกเบราว์เซอร์)."""
import html
import json
import os
import subprocess
from datetime import datetime

from _guard import OUT_DIR

CATS = ["A. ตรวจข้อมูล (backend)", "B. ฐานข้อมูล (ด่านสุดท้าย)", "C. ความปลอดภัย / สิทธิ์", "D. หน้าเว็บ (เบราว์เซอร์จริง)"]


def main() -> None:
    data = json.load(open(os.path.join(OUT_DIR, "results.json"), encoding="utf-8"))
    rs = data["results"]
    by_cat = {c: [r for r in rs if r["cat"] == c] for c in CATS}
    ok = sum(r["ok"] for r in rs)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = "-"
    e = html.escape
    tiles = "".join(f'<div class="tile"><b>{sum(i["ok"] for i in items)}/{len(items)}</b>{e(c[3:])}</div>'
                    for c, items in by_cat.items() if items)
    sections = ""
    for c, items in by_cat.items():
        if not items:
            continue
        rows = "".join(
            f'<tr><td class="{"pass" if i["ok"] else "fail"}">{"✓" if i["ok"] else "✗"}</td><td>{e(i["name"])}</td>'
            f'<td>{e(i["expected"])}</td><td class="act">{e(str(i["actual"]))}</td></tr>' for i in items)
        sections += (f'<h2>{e(c)} <span class="n">{sum(i["ok"] for i in items)}/{len(items)}</span></h2>'
                     f'<table><thead><tr><th></th><th>กรณีทดสอบ</th><th>ผลที่คาดหวัง</th><th>ผลจริง</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table>')
    doc = f"""<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>รายงานทดสอบการตรวจสอบ</title><style>
:root{{--bg:#f3f6fb;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--ok:#16a34a;--err:#dc2626}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 Sarabun,system-ui,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:24px 16px 48px}}h1{{margin:0;font-size:22px}}p{{color:var(--muted)}}
.sum{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0 8px}}.tile{{background:var(--card);border-radius:14px;padding:14px 18px;box-shadow:0 1px 3px #0f172a14}}
.tile b{{display:block;font-size:24px}}.tile.total b{{color:{'var(--ok)' if ok == len(rs) else 'var(--err)'}}}
h2{{font-size:16px;margin:24px 0 8px}}.n{{color:var(--muted);font-weight:400}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden;box-shadow:0 1px 3px #0f172a14}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:12px}}
td.pass{{color:var(--ok);font-weight:700}}td.fail{{color:var(--err);font-weight:700}}td.act{{color:var(--muted);font-size:12px;overflow-wrap:anywhere}}
@media(max-width:700px){{td.act{{display:none}}}}</style></head><body><main>
<h1>รายงานทดสอบการตรวจสอบข้อมูลและความปลอดภัย</h1>
<p>{e(data.get("api", ""))} · {datetime.now():%Y-%m-%d %H:%M} · commit {e(commit)}</p>
<div class="sum"><div class="tile total"><b>{ok}/{len(rs)}</b>ผ่าน</div>{tiles}</div>
<p>A และ C ยิงตรงไปที่ API โดยไม่ผ่านหน้าเว็บ · B แก้ข้อมูลตรงในฐานข้อมูลภายใน transaction แล้ว rollback · D ใช้เบราว์เซอร์จริง</p>
{sections}</main></body></html>"""
    out = os.path.join(OUT_DIR, "report.html")
    open(out, "w", encoding="utf-8").write(doc)
    print(f"รายงาน: {out} ({ok}/{len(rs)} ผ่าน)")


if __name__ == "__main__":
    main()
