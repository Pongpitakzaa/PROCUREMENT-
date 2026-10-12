-- =============================================================================
-- ข้อมูลอ้างอิงตั้งต้น (Reference data)
-- หมายเหตุ: เพดานวงเงินเป็นค่าตามกฎกระทรวง/ระเบียบ ณ เวลาออกแบบ ผู้ดูแลระบบต้องทบทวน
--           ให้ตรงกับกฎกระทรวงและหนังสือเวียนกรมบัญชีกลางฉบับล่าสุดก่อนใช้งานจริง
-- =============================================================================

INSERT INTO roles (code, name_th) VALUES
  ('ADMIN',               'ผู้ดูแลระบบ'),
  ('PROCUREMENT_OFFICER', 'เจ้าหน้าที่พัสดุ'),
  ('HEAD_OF_PROCUREMENT', 'หัวหน้าเจ้าหน้าที่'),
  ('EXECUTIVE',           'ผู้บริหาร / หัวหน้าหน่วยงานของรัฐ'),
  ('AUDITOR',             'ผู้ตรวจสอบภายใน (อ่านอย่างเดียว)');

-- พ.ร.บ. มาตรา 55
INSERT INTO procurement_methods (code, category, name_th, legal_basis, min_budget_exclusive, max_budget_inclusive) VALUES
  ('E_MARKET',  'GENERAL_INVITATION', 'วิธีประกาศเชิญชวนทั่วไป: ตลาดอิเล็กทรอนิกส์ (e-market)',
                'พ.ร.บ. มาตรา 55(1)', 500000.00, NULL),
  ('E_BIDDING', 'GENERAL_INVITATION', 'วิธีประกาศเชิญชวนทั่วไป: ประกวดราคาอิเล็กทรอนิกส์ (e-bidding)',
                'พ.ร.บ. มาตรา 55(1)', 500000.00, NULL),
  ('SELECTION', 'SELECTION',          'วิธีคัดเลือก',
                'พ.ร.บ. มาตรา 55(2) ประกอบมาตรา 56(1)', NULL, NULL),
  ('SPECIFIC',  'SPECIFIC',           'วิธีเฉพาะเจาะจง',
                'พ.ร.บ. มาตรา 55(3) ประกอบมาตรา 56(2)', NULL, NULL);

INSERT INTO method_justifications (method_id, clause_ref, description_th, max_budget_inclusive)
SELECT m.method_id, j.clause_ref, j.description_th, j.max_budget
  FROM procurement_methods m
  JOIN (VALUES
    ('SELECTION', 'มาตรา 56(1)(ก)', 'ใช้วิธีประกาศเชิญชวนทั่วไปแล้วไม่มีผู้ยื่นข้อเสนอ/ข้อเสนอไม่ได้รับการคัดเลือก', NULL::numeric),
    ('SELECTION', 'มาตรา 56(1)(ข)', 'พัสดุมีคุณลักษณะเฉพาะเป็นพิเศษหรือซับซ้อน มีผู้ประกอบการจำนวนจำกัด', NULL),
    ('SELECTION', 'มาตรา 56(1)(ค)', 'มีความจำเป็นเร่งด่วนอันเนื่องมาจากเหตุที่ไม่อาจคาดหมายได้', NULL),
    ('SELECTION', 'มาตรา 56(1)(ง)', 'เป็นพัสดุที่โดยลักษณะต้องซื้อหรือจ้างโดยตรงจากต่างประเทศ', NULL),
    ('SELECTION', 'มาตรา 56(1)(จ)', 'เป็นพัสดุที่ใช้ในราชการลับ/ความมั่นคงของประเทศ', NULL),
    ('SELECTION', 'มาตรา 56(1)(ฉ)', 'งานจ้างซ่อมพัสดุที่ต้องถอดตรวจให้ทราบความชำรุดเสียหายก่อน', NULL),
    ('SPECIFIC',  'มาตรา 56(2)(ก)', 'ใช้วิธีเชิญชวนทั่วไป/คัดเลือกแล้วไม่มีผู้ยื่นข้อเสนอหรือไม่ได้รับการคัดเลือก', NULL),
    -- กฎกระทรวงกำหนดวงเงินการจัดซื้อจัดจ้างพัสดุโดยวิธีเฉพาะเจาะจง พ.ศ. 2560: ไม่เกิน 500,000 บาท
    ('SPECIFIC',  'มาตรา 56(2)(ข)', 'การจัดซื้อจัดจ้างพัสดุที่มีการผลิต จำหน่าย ก่อสร้าง หรือให้บริการทั่วไป และมีวงเงินไม่เกินที่กำหนดในกฎกระทรวง', 500000.00),
    ('SPECIFIC',  'มาตรา 56(2)(ค)', 'มีผู้ประกอบการที่มีคุณสมบัติโดยตรงเพียงรายเดียว', NULL),
    ('SPECIFIC',  'มาตรา 56(2)(ง)', 'มีความจำเป็นต้องใช้พัสดุโดยฉุกเฉิน', NULL),
    ('SPECIFIC',  'มาตรา 56(2)(จ)', 'เป็นพัสดุที่เกี่ยวพันกับพัสดุที่ได้จัดซื้อจัดจ้างไว้ก่อนแล้ว', NULL),
    ('SPECIFIC',  'มาตรา 56(2)(ฉ)', 'เป็นพัสดุที่จะขายทอดตลาดโดยหน่วยงานของรัฐ/องค์การระหว่างประเทศ', NULL)
  ) AS j(method_code, clause_ref, description_th, max_budget) ON j.method_code = m.code;

INSERT INTO committee_types (code, name_th, min_members) VALUES
  ('TOR_PRICE',      'คณะกรรมการจัดทำร่างขอบเขตของงาน (TOR) และกำหนดราคากลาง', 3),
  ('BID_EVALUATION', 'คณะกรรมการพิจารณาผลการประกวดราคาอิเล็กทรอนิกส์', 3),
  ('SELECTION',      'คณะกรรมการซื้อหรือจ้างโดยวิธีคัดเลือก', 3),
  ('INSPECTION',     'คณะกรรมการตรวจรับพัสดุ / ผู้ตรวจรับพัสดุ', 1);  -- 1 = กรณีวงเงินเล็กน้อยตามกฎกระทรวง (ตรวจใน backend)

-- ชื่อเอกสารตรงตามชื่อแบบของกรมบัญชีกลาง (ตัวไฟล์ต้องดาวน์โหลดจาก gprocurement.go.th แล้วลงทะเบียน)
INSERT INTO document_types (code, name_th) VALUES
  ('PRINCIPLE_APPROVAL',     'บันทึกขออนุมัติหลักการ'),
  ('COMMITTEE_ORDER',        'คำสั่งแต่งตั้งคณะกรรมการ'),
  ('MEDIAN_PRICE_TABLE',     'ตารางแสดงวงเงินงบประมาณที่ได้รับจัดสรรและรายละเอียดค่าใช้จ่าย (ราคากลาง)'),
  ('PUBLIC_HEARING',         'ประกาศเผยแพร่ร่างเอกสารประกวดราคาเพื่อรับฟังความคิดเห็น'),
  ('PURCHASE_REQUEST_REPORT','รายงานขอซื้อ/ขอจ้าง'),
  ('INVITATION',             'ประกาศเชิญชวน / หนังสือเชิญชวน'),
  ('PRICE_AGREEMENT',        'บันทึกการตกลงราคา'),
  ('EVALUATION_REPORT',      'รายงานผลการพิจารณา'),
  ('AWARD_APPROVAL',         'รายงานผลการพิจารณาและขออนุมัติสั่งซื้อ/สั่งจ้าง'),
  ('WINNER_ANNOUNCEMENT',    'ประกาศผู้ชนะการเสนอราคา'),
  ('PURCHASE_ORDER',         'ใบสั่งซื้อ/ใบสั่งจ้าง'),
  ('CONTRACT',               'สัญญา (ตามแบบที่ กวพ. กำหนด)');

-- -----------------------------------------------------------------------------
-- Workflow ของแต่ละวิธี (ลำดับ = ลำดับปฏิบัติงานจริง)
-- -----------------------------------------------------------------------------
INSERT INTO workflow_steps (method_id, step_order, code, name_th, legal_ref,
                            output_document_type_id, required_committee_type_id, applies_when_budget_over)
SELECT m.method_id, s.step_order, s.code, s.name_th, s.legal_ref,
       dt.document_type_id, ct.committee_type_id, s.budget_over
  FROM (VALUES
    -- วิธีเฉพาะเจาะจง
    ('SPECIFIC', 1, 'CREATE_PROJECT',          'สร้างโครงการ',                                   'ระเบียบ ข้อ 11 (แผนจัดซื้อจัดจ้าง)', NULL, NULL, NULL::numeric),
    ('SPECIFIC', 2, 'PURCHASE_REQUEST_REPORT', 'จัดทำรายงานขอซื้อขอจ้าง / แต่งตั้งผู้ตรวจรับ',   'ระเบียบ ข้อ 22, ข้อ 79',     'PURCHASE_REQUEST_REPORT', 'INSPECTION', NULL),
    ('SPECIFIC', 3, 'PRICE_AGREEMENT',         'บันทึกตกลงราคา',                                 'ระเบียบ ข้อ 79',             'PRICE_AGREEMENT', NULL, NULL),
    ('SPECIFIC', 4, 'AWARD_APPROVAL',          'รายงานผลการพิจารณาและขออนุมัติสั่งซื้อสั่งจ้าง / ประกาศผู้ชนะ', 'ระเบียบ ข้อ 79, พ.ร.บ. มาตรา 66', 'AWARD_APPROVAL', NULL, NULL),
    ('SPECIFIC', 5, 'PURCHASE_ORDER',          'ออกใบสั่งซื้อ/ใบสั่งจ้าง (PO)',                   'พ.ร.บ. มาตรา 93',            'PURCHASE_ORDER', NULL, NULL),
    -- วิธีคัดเลือก
    ('SELECTION', 1, 'CREATE_PROJECT',          'สร้างโครงการ',                                  'ระเบียบ ข้อ 11', NULL, NULL, NULL),
    ('SELECTION', 2, 'PURCHASE_REQUEST_REPORT', 'รายงานขอซื้อขอจ้าง / แต่งตั้งกรรมการคัดเลือกและตรวจรับ', 'ระเบียบ ข้อ 22, ข้อ 74', 'PURCHASE_REQUEST_REPORT', 'SELECTION', NULL),
    ('SELECTION', 3, 'INVITATION',              'ส่งหนังสือเชิญชวนผู้ประกอบการ (ไม่น้อยกว่า 3 ราย)', 'พ.ร.บ. มาตรา 56(1), ระเบียบ ข้อ 74', 'INVITATION', NULL, NULL),
    ('SELECTION', 4, 'EVALUATION_REPORT',       'รายงานผลการพิจารณา',                            'ระเบียบ ข้อ 74', 'EVALUATION_REPORT', NULL, NULL),
    ('SELECTION', 5, 'AWARD_APPROVAL',          'ขออนุมัติสั่งซื้อสั่งจ้าง / ประกาศผู้ชนะ',          'พ.ร.บ. มาตรา 66', 'AWARD_APPROVAL', NULL, NULL),
    ('SELECTION', 6, 'CONTRACT',                'ลงนามสัญญา (หลังพ้นระยะอุทธรณ์)',                'พ.ร.บ. มาตรา 66 วรรคสอง, มาตรา 117', 'CONTRACT', 'INSPECTION', NULL),
    -- e-bidding
    ('E_BIDDING', 1, 'PRINCIPLE_APPROVAL',      'ขออนุมัติหลักการ',                               NULL, 'PRINCIPLE_APPROVAL', NULL, NULL),
    ('E_BIDDING', 2, 'APPOINT_TOR_COMMITTEE',   'แต่งตั้งคณะกรรมการร่าง TOR และราคากลาง',          'ระเบียบ ข้อ 21', 'COMMITTEE_ORDER', 'TOR_PRICE', NULL),
    ('E_BIDDING', 3, 'TOR_MEDIAN_PRICE',        'จัดทำ TOR และราคากลาง',                          'ระเบียบ ข้อ 21', 'MEDIAN_PRICE_TABLE', NULL, NULL),
    ('E_BIDDING', 4, 'PUBLIC_HEARING',          'เผยแพร่ร่างเอกสารเพื่อรับฟังความคิดเห็น',          'ระเบียบ ข้อ 45', 'PUBLIC_HEARING', NULL, 5000000.00),
    ('E_BIDDING', 5, 'PURCHASE_REQUEST_REPORT', 'รายงานขอซื้อขอจ้าง / แต่งตั้งกรรมการพิจารณาผล',   'ระเบียบ ข้อ 22', 'PURCHASE_REQUEST_REPORT', 'BID_EVALUATION', NULL),
    ('E_BIDDING', 6, 'APPROVE_ANNOUNCEMENT',    'อนุมัติประกาศและเอกสารประกวดราคา',                'ระเบียบ ข้อ 43-46', 'INVITATION', NULL, NULL),
    ('E_BIDDING', 7, 'EVALUATION_REPORT',       'รายงานผลการพิจารณา',                            'ระเบียบ ข้อ 55', 'EVALUATION_REPORT', NULL, NULL),
    ('E_BIDDING', 8, 'AWARD_APPROVAL',          'ขออนุมัติสั่งซื้อสั่งจ้าง / ประกาศผู้ชนะ',          'พ.ร.บ. มาตรา 66', 'AWARD_APPROVAL', NULL, NULL),
    ('E_BIDDING', 9, 'CONTRACT',                'ลงนามสัญญา (หลังพ้นระยะอุทธรณ์)',                'พ.ร.บ. มาตรา 66 วรรคสอง, มาตรา 117', 'CONTRACT', 'INSPECTION', NULL),
    -- e-market
    ('E_MARKET', 1, 'CREATE_PROJECT',          'สร้างโครงการ',                                   'ระเบียบ ข้อ 11', NULL, NULL, NULL),
    ('E_MARKET', 2, 'PURCHASE_REQUEST_REPORT', 'รายงานขอซื้อขอจ้าง / แต่งตั้งกรรมการ',             'ระเบียบ ข้อ 22', 'PURCHASE_REQUEST_REPORT', 'BID_EVALUATION', NULL),
    ('E_MARKET', 3, 'APPROVE_ANNOUNCEMENT',    'อนุมัติประกาศและเอกสารประกวดราคา',                NULL, 'INVITATION', NULL, NULL),
    ('E_MARKET', 4, 'EVALUATION_REPORT',       'รายงานผลการพิจารณา',                             NULL, 'EVALUATION_REPORT', NULL, NULL),
    ('E_MARKET', 5, 'AWARD_APPROVAL',          'ขออนุมัติสั่งซื้อสั่งจ้าง / ประกาศผู้ชนะ',           'พ.ร.บ. มาตรา 66', 'AWARD_APPROVAL', NULL, NULL),
    ('E_MARKET', 6, 'CONTRACT',                'ลงนามสัญญา (หลังพ้นระยะอุทธรณ์)',                 'พ.ร.บ. มาตรา 117', 'CONTRACT', 'INSPECTION', NULL)
  ) AS s(method_code, step_order, code, name_th, legal_ref, doc_code, committee_code, budget_over)
  JOIN procurement_methods m ON m.code = s.method_code
  LEFT JOIN document_types dt ON dt.code = s.doc_code
  LEFT JOIN committee_types ct ON ct.code = s.committee_code;
