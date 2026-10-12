# 4. การนำแบบฟอร์มมาตรฐานกรมบัญชีกลางเข้าระบบ

ระบบนี้ **ไม่ฝังแบบฟอร์มไว้ในโค้ด** และไม่สร้างแบบฟอร์มขึ้นเอง ใช้ไฟล์ต้นฉบับจากกรมบัญชีกลางเท่านั้น
repository จึงไม่มีไฟล์แบบฟอร์มติดมา ผู้ดูแลระบบต้องดาวน์โหลดเองจากแหล่งทางการ

## ขั้นตอน

1. ดาวน์โหลดแบบฟอร์ม (.docx / .xlsx) จาก **https://www.gprocurement.go.th** (เมนูแบบฟอร์ม/คู่มือ) และจดเลขหนังสือเวียนหรือประกาศ กวพ. ที่กำหนดแบบนั้น
2. เปิดไฟล์ใน Word แล้ว **แทนเฉพาะช่องว่างที่ต้องกรอก** ด้วยตัวแปร Jinja โดยห้ามแก้ข้อความ/รูปแบบส่วนอื่น เช่น
   `เรื่อง รายงานขอซื้อ {{ project_title }}` · `เป็นเงิน {{ budget_amount }} บาท ({{ budget_text }})`
   ตารางรายการ: ใส่ `{%tr for it in items %}` … `{%tr endfor %}` ในแถวตาราง
3. อัปโหลดผ่าน `POST /api/admin/templates` (ADMIN) — ต้องระบุ `source_url` ที่เป็นโดเมน `gprocurement.go.th` และ `cgd_reference`
   ระบบดึงรายชื่อตัวแปรจากไฟล์อัตโนมัติ เก็บ SHA-256 และตั้งสถานะ "รอตรวจรับรอง"
4. หัวหน้าเจ้าหน้าที่ (คนละคนกับผู้อัปโหลด) เปรียบเทียบกับต้นฉบับ แล้วกด `POST /api/admin/templates/{id}/verify` → ฉบับเดิมถูกปิดอัตโนมัติ
5. ทุกครั้งที่สร้างเอกสาร ระบบตรวจ SHA-256 ของไฟล์ซ้ำ ถ้าไฟล์ถูกแก้ไขบน storage จะไม่ออกเอกสาร

## ตัวแปรที่ระบบเตรียมให้ (`export_service.build_render_context`)

| ตัวแปร | ความหมาย |
|---|---|
| `agency_name` | ชื่อส่วนราชการ |
| `doc_no`, `doc_date_th` | เลขที่หนังสือ, วันที่แบบไทย (เช่น 12 ตุลาคม 2569) |
| `project_code`, `egp_project_no`, `fiscal_year` | เลขโครงการภายใน / e-GP / ปีงบประมาณ พ.ศ. |
| `project_title`, `reason` | ชื่อโครงการ, เหตุผลความจำเป็น |
| `method_name`, `legal_basis`, `justification` | วิธีจัดหา, มาตราที่อ้าง, เหตุผลตามอนุมาตรา |
| `budget_amount`, `budget_text` | วงเงิน (1,234.00) และตัวอักษร (…บาทถ้วน) |
| `reference_price`, `reference_price_text` | ราคากลาง |
| `items[]` (`no, description, quantity, unit, unit_price, total`), `items_total`, `items_total_text` | ตารางรายการพัสดุ |
| `committees.<type>[]` (`seq, name, position, role`) | รายชื่อกรรมการ เช่น `committees.inspection` |
| ข้อมูลฟอร์มของขั้นตอน | ทุกช่องใน FieldSpec; ช่อง `*_amount` ได้ `*_amount_text` เพิ่ม; ช่อง `*_date` ได้ `*_date_th` เพิ่ม |

ถ้าแบบฟอร์มมีตัวแปรที่ระบบไม่มีข้อมูล การสร้างเอกสารจะถูกปฏิเสธพร้อมรายชื่อตัวแปรที่ขาด (ไม่ออกเอกสารที่มีช่องว่าง)

## แบบฟอร์ม Excel (เช่น ตารางราคากลาง บก.01–บก.06)

ส่ง `xlsx_variable_schema` ตอนอัปโหลด เพื่อบอกตำแหน่งเซลล์:

```json
{"cells": {"C3": "project_title", "C4": "agency_name", "F20": "items_total"},
 "table": {"sheet": "บก.01", "start_row": 10,
           "columns": {"A": "no", "B": "description", "D": "quantity", "E": "unit", "F": "unit_price", "G": "total"}}}
```
