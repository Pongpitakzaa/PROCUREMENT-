"""การตั้งค่าทั้งหมดอ่านจาก Environment Variables / Secret Manager — ห้าม hard-code secret ในโค้ด."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PROC_", extra="ignore")

    app_name: str = "ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ"
    environment: str = "development"
    allowed_origins: list[str] = ["http://localhost:5173"]

    database_url: PostgresDsn = "postgresql+psycopg://proc:proc@localhost:5432/procurement"

    # JWT: access token อายุสั้น ลดผลกระทบหาก token รั่ว
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15

    # กุญแจเข้ารหัสข้อมูลสำคัญ (AES-256-GCM) — base64 ของ 32 bytes, รองรับหมุนเวียนกุญแจด้วย key id
    data_keys: dict[str, SecretStr] = Field(default_factory=dict, description='{"k1": "<base64 32 bytes>"}')
    # ทางเลือก: กุญแจเดียว (PROC_DATA_KEY) ใช้เป็น key id = active_data_key_id — สำหรับแพลตฟอร์มที่สร้างค่าลับให้
    # ทีละค่า เช่น Render (generateValue = base64 ของ 256 bit) ตั้งเป็น JSON ไม่ได้
    data_key: SecretStr | None = None
    active_data_key_id: str = "k1"
    blind_index_key: SecretStr = Field(min_length=32)   # HMAC key สำหรับค้นหาเลขบัตรที่เข้ารหัสแล้ว

    # Login brute-force protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # LINE Messaging API (LINE Notify ยุติบริการแล้วเมื่อ 31 มี.ค. 2568 จึงไม่ใช้)
    line_channel_access_token: SecretStr | None = None
    line_channel_secret: SecretStr | None = None   # ใช้ตรวจลายเซ็น webhook (X-Line-Signature)
    line_auto_notify: bool = True                  # แจ้งเตือนอัตโนมัติเมื่อส่งพิจารณา/อนุมัติ/ส่งกลับ
    line_api_base: str = "https://api.line.me"
    # แจ้งเตือนใกล้ครบกำหนดส่งมอบ (ส่งเข้ากลุ่ม LINE ที่เปิดใช้ วันละครั้งต่อ milestone)
    delivery_reminder_enabled: bool = True
    delivery_reminder_days: list[int] = [7, 3, 1, 0]   # ล่วงหน้ากี่วัน (0 = วันครบกำหนด) · เลยกำหนดแจ้งอีกครั้งเสมอ
    delivery_reminder_hour: int = Field(8, ge=0, le=23)  # เริ่มส่งได้ตั้งแต่กี่โมง (เวลาไทย) ไม่ส่งกลางดึก
    delivery_reminder_scheduler: bool = True             # ตัวตั้งเวลาในโปรเซส API (ปิดเมื่อใช้ cron: python -m app.cli remind-deliveries)
    public_base_url: str = "https://procurement.example.go.th"
    download_link_minutes: int = 60

    # ไฟล์
    template_dir: Path = Path("storage/templates")
    output_dir: Path = Path("storage/outputs")
    backup_dir: Path = Path("storage/backups")
    backup_key: SecretStr = Field(description="base64 32 bytes — แยกจาก data_keys")
    libreoffice_bin: str = "soffice"
    pg_bin_dir: Path = Path("/usr/bin")

    # หน้าเว็บ (React build) — ตั้งเมื่อ API เสิร์ฟหน้าเว็บเอง (เช่น Render) · ไม่ตั้ง = ใช้ reverse proxy (Caddy)
    static_dir: Path | None = None

    # ผู้ดูแลระบบคนแรก (สร้างตอนเริ่มระบบครั้งแรกเมื่อยังไม่มีผู้ใช้เลย — ดู app.cli init-db)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    bootstrap_admin_name: str | None = None
    bootstrap_admin_citizen_id: str | None = None
    bootstrap_department_name: str | None = None
    # รีเซ็ตรหัสผ่านผ่าน Environment (สำหรับแพลตฟอร์มที่ไม่มี shell เช่น Render แผนฟรี): ระบบตั้งรหัสใหม่ตอนเริ่มทำงาน
    # แล้วพิมพ์ลง Logs — ใช้ครั้งเดียวแล้วลบค่าออก ไม่อย่างนั้นจะรีเซ็ตซ้ำทุกครั้งที่ deploy
    reset_password_for: str | None = None
    reset_password_to: SecretStr | None = None   # ไม่ตั้ง = สุ่มให้

    @field_validator("line_channel_access_token", "line_channel_secret", mode="before")
    @classmethod
    def _clean_line_secret(cls, v: object) -> object:
        """ตัดช่องว่าง/ขึ้นบรรทัดใหม่ และเครื่องหมายคำพูดที่ติดมาตอนวางค่า (LINE ตอบ 401 ถ้ามีอักขระเกิน) · ค่าว่าง = ไม่ตั้ง."""
        if isinstance(v, SecretStr):
            v = v.get_secret_value()
        if isinstance(v, str):
            v = v.strip().strip("\"'").strip()
            return v or None
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, v: object) -> object:
        """รับ URL รูปแบบ postgresql:// / postgres:// (เช่นจาก Render) แล้วใช้ไดรเวอร์ psycopg 3."""
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @model_validator(mode="after")
    def _derived(self) -> "Settings":
        if not self.data_keys:
            if self.data_key is None:
                raise ValueError("ต้องตั้ง PROC_DATA_KEYS (JSON) หรือ PROC_DATA_KEY (กุญแจเดียว)")
            self.data_keys = {self.active_data_key_id: self.data_key}
        if self.active_data_key_id not in self.data_keys:
            raise ValueError(f"ไม่พบกุญแจ {self.active_data_key_id} ใน PROC_DATA_KEYS")
        # Render ตั้ง RENDER_EXTERNAL_URL ให้อัตโนมัติ → ลิงก์ดาวน์โหลดเอกสารที่ส่งทาง LINE ใช้โดเมนจริง
        render_url = os.environ.get("RENDER_EXTERNAL_URL")
        if render_url and "public_base_url" not in self.model_fields_set:
            self.public_base_url = render_url.rstrip("/")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
