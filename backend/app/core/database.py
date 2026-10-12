from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    # ทุกคอลัมน์เวลาเป็น TIMESTAMPTZ → ใช้ datetime แบบมี timezone เสมอ (ไม่ปน naive/aware)
    type_annotation_map = {datetime: DateTime(timezone=True)}


engine = create_engine(
    str(get_settings().database_url),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # statement_timeout กัน query ค้างนาน (เช่นจากการโจมตีด้วย input หนัก ๆ)
    connect_args={"options": "-c statement_timeout=30000"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """1 request = 1 transaction: commit เมื่อสำเร็จ, rollback ทั้งหมดเมื่อ error (รวม audit log)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
