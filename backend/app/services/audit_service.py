"""บันทึก Audit Log — เรียกใน transaction เดียวกับการเปลี่ยนแปลงข้อมูล (ถ้า rollback ก็ไม่มี log ปลอม)."""
from __future__ import annotations

import ipaddress
import json
from decimal import Decimal
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

# ห้ามบันทึกค่าเหล่านี้ลง log แม้จะอยู่ใน payload
_REDACT = {"password", "password_hash", "citizen_id", "bank_account", "phone", "line_to", "token"}


def _jsonable(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None

    def default(o: Any) -> Any:
        if isinstance(o, (Decimal, UUID)):
            return str(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError(type(o))

    redacted = {k: ("***" if k in _REDACT else v) for k, v in values.items()}
    return json.loads(json.dumps(redacted, default=default, ensure_ascii=False))


def _client_ip(request: Request | None) -> str | None:
    # หลัง reverse proxy ให้ตั้ง uvicorn --proxy-headers + forwarded-allow-ips เพื่อให้ได้ IP จริง
    host = request.client.host if request and request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def write_audit(db: Session, *, action: str, user_id: int | None, request: Request | None = None,
                entity_table: str | None = None, entity_id: Any = None,
                old: dict[str, Any] | None = None, new: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        entity_table=entity_table,
        entity_id=None if entity_id is None else str(entity_id),
        old_values=_jsonable(old),
        new_values=_jsonable(new),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
        request_id=getattr(request.state, "request_id", None) if request else None,
    ))
