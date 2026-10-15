import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError, InternalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, auth, dashboard, documents, line, projects, registry, users, vendors
from app.core.config import get_settings
from app.services.export_service import ExportError
from app.services.workflow_service import ValidationFailed

log = logging.getLogger("procurement")
settings = get_settings()
is_prod = settings.environment == "production"

app = FastAPI(
    title=settings.app_name,
    # ปิดหน้าเอกสาร API บน production ลดข้อมูลที่ผู้โจมตีใช้สำรวจระบบได้
    docs_url=None if is_prod else "/docs",
    redoc_url=None,
    openapi_url=None if is_prod else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,   # whitelist เท่านั้น ห้ามใช้ "*"
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# CSP ของหน้าเว็บ React (ตรงกับ deploy/Caddyfile)
SPA_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
           "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self'; "
           "manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
STATIC_DIR = settings.static_dir.resolve() if settings.static_dir and settings.static_dir.is_dir() else None


def _is_web_page(path: str) -> bool:
    return STATIC_DIR is not None and not path.startswith("/api/") and path != "/healthz"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.request_id = uuid.uuid4()
    response = await call_next(request)
    h = response.headers
    h["X-Request-ID"] = str(request.state.request_id)
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    if _is_web_page(request.url.path):
        # หน้าเว็บ (เมื่อ API เสิร์ฟหน้าเว็บเอง): CSP เดียวกับ deploy/Caddyfile + cache ตามชนิดไฟล์
        h["Content-Security-Policy"] = SPA_CSP
        h["Cache-Control"] = ("public, max-age=31536000, immutable" if request.url.path.startswith("/assets/")
                              else "no-cache")
    else:
        h["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"
        h["Cache-Control"] = "no-store"   # เอกสารราชการ/ข้อมูลส่วนบุคคล ห้าม cache
    if is_prod:
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


def _problem(status: int, message: str, violations: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message, "violations": violations or []})


@app.exception_handler(StarletteHTTPException)
async def on_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # รูปแบบ error เดียวกันทั้งระบบ {message, violations} → frontend จัดการได้ที่เดียว
    resp = _problem(exc.status_code, str(exc.detail))
    if exc.headers:
        resp.headers.update(exc.headers)
    return resp


@app.exception_handler(ValidationFailed)
async def on_rule_violation(_: Request, exc: ValidationFailed) -> JSONResponse:
    return _problem(422, "ข้อมูลไม่ผ่านการตรวจสอบตามระเบียบ", [
        {"code": v.code, "message": v.message, "field": v.field, "legal_ref": v.legal_ref,
         "severity": str(v.severity)} for v in exc.violations])


@app.exception_handler(RequestValidationError)
async def on_schema_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # ส่งเฉพาะตำแหน่งฟิลด์ + ข้อความ ไม่สะท้อนค่า input กลับ (ลดความเสี่ยง reflected XSS / ข้อมูลรั่ว)
    return _problem(422, "รูปแบบข้อมูลไม่ถูกต้อง", [
        {"code": e["type"], "message": e["msg"], "field": ".".join(str(p) for p in e["loc"][1:]),
         "legal_ref": None, "severity": "ERROR"} for e in exc.errors()])


@app.exception_handler(IntegrityError)
@app.exception_handler(InternalError)
async def on_db_constraint(_: Request, exc: IntegrityError | InternalError) -> JSONResponse:
    # ข้อความจาก DB trigger (RAISE EXCEPTION ภาษาไทย) ปลอดภัยที่จะแสดง; constraint อื่นแสดงข้อความกลาง
    diag = getattr(exc.orig, "diag", None)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23514" and diag and diag.message_primary and not diag.constraint_name:
        return _problem(422, diag.message_primary)
    if sqlstate == "23505":
        return _problem(409, "ข้อมูลซ้ำกับที่มีอยู่แล้ว")
    log.warning("db constraint error: %s", exc.orig)
    return _problem(422, "ข้อมูลขัดกับข้อกำหนดของฐานข้อมูล")


@app.exception_handler(StaleDataError)
async def on_stale(_: Request, __: StaleDataError) -> JSONResponse:
    return _problem(409, "ข้อมูลถูกแก้ไขโดยผู้อื่นระหว่างนี้ กรุณาโหลดใหม่")


@app.exception_handler(ExportError)
async def on_export_error(_: Request, exc: ExportError) -> JSONResponse:
    return _problem(422, str(exc))


@app.exception_handler(Exception)
async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    # ไม่ส่ง stack trace ให้ client; อ้างอิง request id เพื่อตามใน log
    log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", "-"))
    return _problem(500, f"เกิดข้อผิดพลาดภายในระบบ (อ้างอิง {getattr(request.state, 'request_id', '-')})")


for r in (auth.router, projects.router, vendors.router, users.router, registry.router, documents.router, dashboard.router, admin.router, line.router):
    app.include_router(r)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


if STATIC_DIR is not None:
    # เสิร์ฟหน้าเว็บ React จากโปรเซสเดียวกับ API (PROC_STATIC_DIR) — ใช้บนแพลตฟอร์มที่มี service เดียว เช่น Render
    # ลงทะเบียนหลัง router ของ API ทั้งหมด จึงไม่ทับ /api/*
    @app.get("/{path:path}", include_in_schema=False)
    def web_page(path: str):
        if path.startswith("api/"):
            return _problem(404, "ไม่พบ endpoint")
        target = (STATIC_DIR / path).resolve()
        if path and target.is_file() and STATIC_DIR in target.parents:   # กัน path traversal
            return FileResponse(target)
        return FileResponse(STATIC_DIR / "index.html")   # หน้าเว็บเป็น SPA
