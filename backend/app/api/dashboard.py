from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Perm, require
from app.models import User
from app.services.audit_service import write_audit
from app.services.export_service import MEDIA_TYPES, build_summary_workbook

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
DB = Annotated[Session, Depends(get_db)]
FiscalYear = Annotated[int, Query(ge=2560, le=2700)]

# ใช้ text() + bind parameter (:fy) เท่านั้น — ห้ามต่อ string SQL กับค่าจากผู้ใช้
_MONTHLY_SQL = text("""
    SELECT to_char(award_month, 'YYYY-MM') AS month, method_code, method_name_th,
           count(*) AS project_count,
           sum(budget_amount) AS budget_total,
           sum(award_amount) AS award_total,
           sum(savings_amount) AS savings_total
      FROM v_award_summary
     WHERE fiscal_year_be = :fy AND award_month IS NOT NULL
     GROUP BY 1, 2, 3
     ORDER BY 1, 2
""")

_BY_STATUS_SQL = text("""
    SELECT m.code AS method_code, m.name_th AS method_name_th, p.status,
           count(*) AS project_count, sum(p.budget_amount) AS budget_total
      FROM projects p JOIN procurement_methods m USING (method_id)
     WHERE p.fiscal_year_be = :fy
     GROUP BY 1, 2, 3
     ORDER BY 1, 3
""")


@router.get("/summary")
def summary(fiscal_year: FiscalYear, db: DB, _: Annotated[User, Depends(require(Perm.DASHBOARD_VIEW))]) -> dict:
    monthly = [dict(r._mapping) for r in db.execute(_MONTHLY_SQL, {"fy": fiscal_year})]
    by_status = [dict(r._mapping) for r in db.execute(_BY_STATUS_SQL, {"fy": fiscal_year})]
    total_budget = sum(r["budget_total"] for r in by_status)
    total_award = sum(r["award_total"] for r in monthly)
    return {
        "fiscal_year": fiscal_year,
        "kpi": {
            "project_count": sum(r["project_count"] for r in by_status),
            "budget_total": total_budget,
            "award_total": total_award,
            "savings_total": sum(r["savings_total"] for r in monthly),
        },
        "monthly_by_method": monthly,
        "by_method_status": by_status,
    }


@router.get("/report.xlsx")
def monthly_report(fiscal_year: FiscalYear, request: Request, db: DB,
                   user: Annotated[User, Depends(require(Perm.DASHBOARD_VIEW))]) -> Response:
    rows = [dict(r._mapping) for r in db.execute(_MONTHLY_SQL, {"fy": fiscal_year})]
    content = build_summary_workbook(rows, f"สรุปผลการจัดซื้อจัดจ้าง ปีงบประมาณ พ.ศ. {fiscal_year} (รายเดือน/รายวิธี)")
    write_audit(db, action="EXPORT_REPORT", user_id=user.user_id, request=request,
                new={"report": "monthly_by_method", "fiscal_year": fiscal_year})
    return Response(content, media_type=MEDIA_TYPES["XLSX"],
                    headers={"Content-Disposition": f'attachment; filename="procurement-{fiscal_year}.xlsx"'})
