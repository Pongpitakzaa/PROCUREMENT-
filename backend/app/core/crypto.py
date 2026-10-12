"""Field-level encryption สำหรับข้อมูลส่วนบุคคล/ข้อมูลสำคัญ (PDPA).

รูปแบบ ciphertext: b"<key_id>:" + nonce(12) + AES-256-GCM(ciphertext||tag)
- key_id นำหน้า ทำให้หมุนเวียนกุญแจได้ (ถอดรหัสของเก่าด้วยกุญแจเก่า เข้ารหัสใหม่ด้วยกุญแจ active)
- AAD = ชื่อตาราง.คอลัมน์ กันการสลับ ciphertext ข้ามคอลัมน์ (เช่น เอาเลขบัญชีไปใส่ช่องเบอร์โทร)
- Blind index (HMAC-SHA256) ใช้ค้นหา/กันซ้ำ โดยไม่ต้องถอดรหัสทั้งตาราง
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


@lru_cache
def _keys() -> dict[str, AESGCM]:
    out = {}
    for kid, secret in get_settings().data_keys.items():
        raw = base64.b64decode(secret.get_secret_value())
        if len(raw) != 32:
            raise ValueError(f"data key {kid} ต้องยาว 32 bytes (AES-256)")
        out[kid] = AESGCM(raw)
    return out


def encrypt_field(plaintext: str, context: str) -> bytes:
    kid = get_settings().active_data_key_id
    nonce = os.urandom(12)
    ct = _keys()[kid].encrypt(nonce, plaintext.encode(), context.encode())
    return kid.encode() + b":" + nonce + ct


def decrypt_field(blob: bytes, context: str) -> str:
    kid, _, rest = bytes(blob).partition(b":")
    return _keys()[kid.decode()].decrypt(rest[:12], rest[12:], context.encode()).decode()


def blind_index(value: str) -> str:
    key = get_settings().blind_index_key.get_secret_value().encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def mask_citizen_id(value: str) -> str:
    """แสดงผลแบบปิดบัง x-xxxx-xxxxx-12-3 (สิทธิ์ดูเต็มเฉพาะ ADMIN และถูก audit)."""
    return "x-xxxx-xxxxx-" + value[10:12] + "-" + value[12]
