import base64
import os
import tempfile
from pathlib import Path

# ตั้งค่า environment ก่อน import app (Settings ถูกสร้างครั้งแรกตอน import)
_TMP = Path(tempfile.mkdtemp(prefix="proc-test-"))
os.environ.setdefault("PROC_DATABASE_URL",
                      os.environ.get("TEST_DATABASE_URL",
                                     "postgresql+psycopg://proc:proc@localhost:5432/procurement_test"))
os.environ.setdefault("PROC_JWT_SECRET", "test-jwt-secret-" + "x" * 32)
os.environ.setdefault("PROC_BLIND_INDEX_KEY", "test-blind-index-" + "y" * 32)
os.environ.setdefault("PROC_DATA_KEYS", '{"k1": "%s"}' % base64.b64encode(b"k" * 32).decode())
os.environ.setdefault("PROC_BACKUP_KEY", base64.b64encode(b"b" * 32).decode())
os.environ.setdefault("PROC_LINE_CHANNEL_ACCESS_TOKEN", "test-line-token")
os.environ["PROC_TEMPLATE_DIR"] = str(_TMP / "templates")
os.environ["PROC_OUTPUT_DIR"] = str(_TMP / "outputs")
os.environ["PROC_BACKUP_DIR"] = str(_TMP / "backups")
