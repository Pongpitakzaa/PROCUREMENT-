"""ตัวตรวจสอบข้อมูลพื้นฐาน (pure functions — ไม่มี I/O จึงทดสอบง่ายและใช้ซ้ำได้ทั้ง API/Export)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_DIGITS_13 = re.compile(r"^\d{13}$")
# อนุญาตอักษรไทย อังกฤษ ตัวเลข เว้นวรรค และเครื่องหมายที่ใช้ในเอกสารราชการ
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def is_valid_thai_tax_id(value: str) -> bool:
    """ตรวจเลขประจำตัวผู้เสียภาษี/เลขประจำตัวประชาชน 13 หลัก ด้วย checksum mod 11.

    หลักที่ 13 = (11 - (Σ d[i] × (13 - i)  สำหรับ i = 0..11) mod 11) mod 10
    ใช้ได้ทั้งเลขนิติบุคคล (กรมพัฒนาธุรกิจการค้า) และเลขบัตรประชาชน (กรมการปกครอง)
    """
    if not isinstance(value, str) or not _DIGITS_13.match(value):
        return False
    total = sum(int(value[i]) * (13 - i) for i in range(12))
    return (11 - total % 11) % 10 == int(value[12])


def fiscal_year_be(d: date) -> int:
    """ปีงบประมาณ (พ.ศ.) ของวันที่: 1 ต.ค. – 30 ก.ย. ถัดไป."""
    year_be = d.year + 543
    return year_be + 1 if d.month >= 10 else year_be


def money(value: Decimal | int | float | str) -> Decimal:
    """ปัดเศษเงินเป็นทศนิยม 2 ตำแหน่งแบบราชการ (ปัดครึ่งขึ้น) — ห้ามใช้ float กับเงิน."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clean_text(value: str) -> str:
    """Normalize ข้อความก่อนบันทึก: NFC + ตัด control chars + trim.

    ไม่ "strip HTML" ที่นี่ เพราะการกัน XSS ที่ถูกต้องคือ escape ตอนแสดงผล (React/Jinja autoescape)
    การลบ < > ตอนรับข้อมูลจะทำให้ข้อความราชการที่ถูกต้องเสียหาย (เช่น "วงเงิน < 100,000")
    """
    value = unicodedata.normalize("NFC", value)
    return _CONTROL_CHARS.sub("", value).strip()


# ---------------------------------------------------------------------------
# ตัวเลขเป็นข้อความภาษาไทย (บาทถ้วน) — แบบฟอร์มกรมบัญชีกลางต้องระบุจำนวนเงินเป็นตัวอักษร
# ---------------------------------------------------------------------------
_TH_DIGITS = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_TH_PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]


def _read_under_million(n: int) -> str:
    text = []
    digits = str(n)
    length = len(digits)
    for idx, ch in enumerate(digits):
        d = int(ch)
        place = length - idx - 1
        if d == 0:
            continue
        if place == 1 and d == 1:
            text.append("สิบ")
        elif place == 1 and d == 2:
            text.append("ยี่สิบ")
        elif place == 0 and d == 1 and length > 1:
            text.append("เอ็ด")
        else:
            text.append(_TH_DIGITS[d] + _TH_PLACES[place])
    return "".join(text)


def _read_integer(n: int) -> str:
    if n == 0:
        return "ศูนย์"
    parts = []
    while n > 0:
        parts.append(n % 1_000_000)
        n //= 1_000_000
    out = ""
    for i, chunk in enumerate(reversed(parts)):
        is_last = i == len(parts) - 1
        if chunk:
            # "เอ็ด" ใช้เมื่อมีหลักอื่นนำหน้าในกลุ่มเดียวกันหรือกลุ่มก่อนหน้า เช่น 1,000,001 = หนึ่งล้านเอ็ด
            word = _read_under_million(chunk)
            if out and chunk == 1:
                word = "เอ็ด"
            out += word
        if not is_last:
            out += "ล้าน"
    return out


def baht_text(amount: Decimal | int | float | str) -> str:
    """แปลงจำนวนเงินเป็นข้อความ เช่น 1,250.50 → 'หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์'."""
    value = money(amount)
    if value < 0:
        raise ValueError("จำนวนเงินต้องไม่ติดลบ")
    baht = int(value)
    satang = int((value - baht) * 100)
    text = _read_integer(baht) + "บาท"
    return text + ("ถ้วน" if satang == 0 else _read_integer(satang) + "สตางค์")


_TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
              "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def thai_date(d: date) -> str:
    """วันที่รูปแบบหนังสือราชการ เช่น 12 ตุลาคม 2569."""
    return f"{d.day} {_TH_MONTHS[d.month - 1]} {d.year + 543}"
