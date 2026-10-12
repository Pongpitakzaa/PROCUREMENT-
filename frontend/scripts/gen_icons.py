"""สร้างไอคอนแอป (PWA / หน้าจอโฮม iOS-Android) จากโลโก้ ◆ — รันซ้ำได้: python scripts/gen_icons.py

any       : พื้นน้ำเงินมุมโค้ง (Android ใช้ตามรูปทรงไฟล์)
maskable  : พื้นเต็มกรอบ โลโก้อยู่ใน safe zone 80% (Android ตัดเป็นวงกลม/สี่เหลี่ยมโค้งเอง)
apple     : พื้นเต็มกรอบ ไม่โปร่งใส (iOS ใส่มุมโค้งเองและแสดงสีดำแทนส่วนโปร่งใส)
"""
from pathlib import Path

from PIL import Image, ImageDraw

BLUE = (37, 99, 235, 255)      # --accent ของธีม B
WHITE = (255, 255, 255, 255)
OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
SS = 4  # วาดใหญ่ 4 เท่าแล้วย่อ → ขอบเรียบ


def icon(size: int, *, rounded: bool, logo_ratio: float) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=BLUE)
    else:
        d.rectangle((0, 0, big, big), fill=BLUE)
    c, r = big / 2, big * logo_ratio / 2
    d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=WHITE)
    # เส้นเอกสารจาง ๆ ในข้าวหลามตัด สื่อถึง "เอกสารจัดซื้อจัดจ้าง"
    w = r * 0.62
    for dy in (-0.28, 0, 0.28):
        y = c + r * dy
        half = w * (1 - abs(dy) * 1.2)
        d.rounded_rectangle((c - half, y - r * 0.05, c + half, y + r * 0.05), radius=int(r * 0.05), fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in (192, 512):
        icon(s, rounded=True, logo_ratio=0.62).save(OUT / f"icon-{s}.png", optimize=True)
    icon(512, rounded=False, logo_ratio=0.5).save(OUT / "icon-maskable-512.png", optimize=True)
    icon(180, rounded=False, logo_ratio=0.6).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    icon(32, rounded=True, logo_ratio=0.7).save(OUT / "favicon-32.png", optimize=True)


if __name__ == "__main__":
    main()
