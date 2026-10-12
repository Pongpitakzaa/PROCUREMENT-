"""การตั้งค่าทั้งหมดอ่านจาก Environment Variables / Secret Manager — ห้าม hard-code secret ในโค้ด."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, SecretStr
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
    data_keys: dict[str, SecretStr] = Field(description='{"k1": "<base64 32 bytes>"}')
    active_data_key_id: str = "k1"
    blind_index_key: SecretStr = Field(min_length=32)   # HMAC key สำหรับค้นหาเลขบัตรที่เข้ารหัสแล้ว

    # Login brute-force protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # LINE Messaging API (LINE Notify ยุติบริการแล้วเมื่อ 31 มี.ค. 2568 จึงไม่ใช้)
    line_channel_access_token: SecretStr | None = None
    line_api_base: str = "https://api.line.me"
    public_base_url: str = "https://procurement.example.go.th"
    download_link_minutes: int = 60

    # ไฟล์
    template_dir: Path = Path("storage/templates")
    output_dir: Path = Path("storage/outputs")
    backup_dir: Path = Path("storage/backups")
    backup_key: SecretStr = Field(description="base64 32 bytes — แยกจาก data_keys")
    libreoffice_bin: str = "soffice"
    pg_bin_dir: Path = Path("/usr/bin")


@lru_cache
def get_settings() -> Settings:
    return Settings()
