-- =============================================================================
-- ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ — Database Schema (PostgreSQL 14+)
-- ออกแบบระดับ 3NF: ทุก non-key attribute ขึ้นกับ key ทั้งหมด และไม่มี transitive dependency
--   * ค่าที่คำนวณได้ (ยอดรวมรายการ, ปีงบประมาณจากวันที่) ไม่เก็บซ้ำ → ใช้ VIEW
--   * ข้อมูลอ้างอิง (วิธีจัดหา, ประเภทกรรมการ, ประเภทเอกสาร) แยกเป็น lookup table
-- อ้างอิงกฎหมาย: พ.ร.บ.การจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 (ต่อไปเรียก "พ.ร.บ.")
--               ระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างฯ พ.ศ. 2560 (ต่อไปเรียก "ระเบียบ")
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest() สำหรับ hash chain

-- -----------------------------------------------------------------------------
-- 1) โครงสร้างองค์กร / บุคลากร / ผู้ใช้งาน
-- -----------------------------------------------------------------------------
CREATE TABLE departments (
    department_id        SERIAL PRIMARY KEY,
    code                 VARCHAR(20)  NOT NULL UNIQUE,
    name_th              VARCHAR(255) NOT NULL,
    parent_department_id INT REFERENCES departments(department_id)
);

CREATE TABLE personnel (
    personnel_id      SERIAL PRIMARY KEY,
    department_id     INT          NOT NULL REFERENCES departments(department_id),
    title_th          VARCHAR(50)  NOT NULL,              -- คำนำหน้า (นาย/นาง/นางสาว/ยศ)
    first_name_th     VARCHAR(100) NOT NULL,
    last_name_th      VARCHAR(100) NOT NULL,
    position_th       VARCHAR(150) NOT NULL,              -- ตำแหน่ง (ใช้ในคำสั่งแต่งตั้งกรรมการ)
    employment_type   VARCHAR(30)  NOT NULL
        CHECK (employment_type IN ('CIVIL_SERVANT','GOV_EMPLOYEE','PERMANENT_EMPLOYEE','STATE_OFFICIAL','OTHER')),
    -- เลขประจำตัวประชาชน = ข้อมูลส่วนบุคคล (PDPA) → เก็บแบบเข้ารหัส AES-256-GCM
    citizen_id_enc    BYTEA        NOT NULL,
    citizen_id_hmac   CHAR(64)     NOT NULL UNIQUE,       -- blind index (HMAC-SHA256) สำหรับค้นหา/กันซ้ำ
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE roles (
    role_id   SMALLSERIAL PRIMARY KEY,
    code      VARCHAR(40)  NOT NULL UNIQUE,   -- ADMIN, PROCUREMENT_OFFICER, HEAD_OF_PROCUREMENT, EXECUTIVE, AUDITOR
    name_th   VARCHAR(100) NOT NULL
);

CREATE TABLE users (
    user_id             SERIAL PRIMARY KEY,
    personnel_id        INT          NOT NULL UNIQUE REFERENCES personnel(personnel_id),
    username            VARCHAR(60)  NOT NULL UNIQUE,
    password_hash       VARCHAR(255) NOT NULL,           -- Argon2id (ไม่เก็บรหัสผ่านจริง)
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_login_count  SMALLINT     NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_login_at       TIMESTAMPTZ
);

CREATE TABLE user_roles (
    user_id INT      NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id SMALLINT NOT NULL REFERENCES roles(role_id),
    PRIMARY KEY (user_id, role_id)
);

-- -----------------------------------------------------------------------------
-- 2) ข้อมูลอ้างอิงตามกฎหมาย: วิธีจัดหา / เหตุผลการเลือกวิธี / ขั้นตอนงาน
-- -----------------------------------------------------------------------------
CREATE TABLE procurement_methods (
    method_id      SMALLSERIAL PRIMARY KEY,
    code           VARCHAR(30)   NOT NULL UNIQUE,     -- E_MARKET, E_BIDDING, SELECTION, SPECIFIC
    category       VARCHAR(30)   NOT NULL
        CHECK (category IN ('GENERAL_INVITATION','SELECTION','SPECIFIC')),   -- พ.ร.บ. มาตรา 55
    name_th        VARCHAR(150)  NOT NULL,
    legal_basis    VARCHAR(255)  NOT NULL,
    -- ช่วงวงเงินที่วิธีนี้ "อนุญาต" (NULL = ไม่จำกัด) — เป็นปราการสุดท้ายใน DB (trigger ด้านล่าง)
    min_budget_exclusive NUMERIC(15,2),
    max_budget_inclusive NUMERIC(15,2)
);

-- เหตุผลการใช้วิธีคัดเลือก/เฉพาะเจาะจง ต้องอ้างอนุมาตราได้ (พ.ร.บ. มาตรา 56(1)(ก)-(ฉ), 56(2)(ก)-(ฉ))
CREATE TABLE method_justifications (
    justification_id     SMALLSERIAL PRIMARY KEY,
    method_id            SMALLINT     NOT NULL REFERENCES procurement_methods(method_id),
    clause_ref           VARCHAR(40)  NOT NULL,          -- เช่น 'มาตรา 56(2)(ข)'
    description_th       TEXT         NOT NULL,
    -- บางอนุมาตรามีเพดานวงเงินของตัวเอง เช่น 56(2)(ข) วงเงินไม่เกินที่กฎกระทรวงกำหนด (500,000 บาท)
    max_budget_inclusive NUMERIC(15,2),
    UNIQUE (method_id, clause_ref)
);

CREATE TABLE document_types (
    document_type_id SMALLSERIAL PRIMARY KEY,
    code             VARCHAR(50)  NOT NULL UNIQUE,   -- PURCHASE_REQUEST_REPORT, PO, ...
    name_th          VARCHAR(255) NOT NULL
);

CREATE TABLE committee_types (
    committee_type_id SMALLSERIAL PRIMARY KEY,
    code              VARCHAR(40)  NOT NULL UNIQUE,  -- TOR_PRICE, BID_EVALUATION, SELECTION, INSPECTION
    name_th           VARCHAR(255) NOT NULL,
    min_members       SMALLINT     NOT NULL DEFAULT 3  -- ระเบียบ ข้อ 25: ประธาน 1 + กรรมการอย่างน้อย 2
);

-- ลำดับขั้นตอนของแต่ละวิธี (Dynamic Workflow ขับเคลื่อนด้วยข้อมูล ไม่ hard-code ใน UI)
CREATE TABLE workflow_steps (
    step_id                   SERIAL PRIMARY KEY,
    method_id                 SMALLINT     NOT NULL REFERENCES procurement_methods(method_id),
    step_order                SMALLINT     NOT NULL,
    code                      VARCHAR(50)  NOT NULL,
    name_th                   VARCHAR(255) NOT NULL,
    legal_ref                 VARCHAR(255),
    output_document_type_id   SMALLINT     REFERENCES document_types(document_type_id),
    required_committee_type_id SMALLINT    REFERENCES committee_types(committee_type_id),
    -- ขั้นตอนแบบมีเงื่อนไข เช่น รับฟังคำวิจารณ์ร่าง TOR เฉพาะวงเงิน > 5 ล้าน
    applies_when_budget_over  NUMERIC(15,2),
    UNIQUE (method_id, step_order),
    UNIQUE (method_id, code)
);

-- -----------------------------------------------------------------------------
-- 3) ผู้ประกอบการ (Vendors)
-- -----------------------------------------------------------------------------
CREATE TABLE vendors (
    vendor_id        SERIAL PRIMARY KEY,
    tax_id           CHAR(13)     NOT NULL UNIQUE
        CHECK (tax_id ~ '^[0-9]{13}$'),   -- checksum ตรวจใน backend (mod 11) อีกชั้น
    vendor_type      VARCHAR(20)  NOT NULL CHECK (vendor_type IN ('JURISTIC','INDIVIDUAL')),
    name_th          VARCHAR(255) NOT NULL,
    address_th       TEXT         NOT NULL,
    phone_enc        BYTEA,                -- เข้ารหัส (ข้อมูลติดต่อบุคคลธรรมดา = ข้อมูลส่วนบุคคล)
    email            VARCHAR(255),
    bank_account_enc BYTEA,                -- เลขบัญชีรับเงินเข้ารหัส
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- รายชื่อผู้ทิ้งงาน/ถูกระงับ แยกตารางเพื่อเก็บประวัติ (พ.ร.บ. มาตรา 109)
CREATE TABLE vendor_sanctions (
    sanction_id    SERIAL PRIMARY KEY,
    vendor_id      INT         NOT NULL REFERENCES vendors(vendor_id),
    sanction_type  VARCHAR(30) NOT NULL CHECK (sanction_type IN ('ABANDONED_WORK','SUSPENDED')),
    reference_no   VARCHAR(100) NOT NULL,   -- เลขหนังสือแจ้งเวียนชื่อ
    effective_from DATE        NOT NULL,
    effective_to   DATE,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

-- -----------------------------------------------------------------------------
-- 4) โครงการ (Projects)
-- -----------------------------------------------------------------------------
CREATE TABLE projects (
    project_id        SERIAL PRIMARY KEY,
    project_code      VARCHAR(30)   NOT NULL UNIQUE,            -- เลขที่ภายในหน่วยงาน
    egp_project_no    CHAR(11)      UNIQUE CHECK (egp_project_no ~ '^[0-9]{11}$'), -- เลขโครงการในระบบ e-GP
    fiscal_year_be    SMALLINT      NOT NULL CHECK (fiscal_year_be BETWEEN 2560 AND 2700), -- ปีงบประมาณ พ.ศ.
    title_th          VARCHAR(500)  NOT NULL,
    reason_th         TEXT          NOT NULL,       -- เหตุผลความจำเป็น (ระเบียบ ข้อ 22(1))
    department_id     INT           NOT NULL REFERENCES departments(department_id),
    method_id         SMALLINT      NOT NULL REFERENCES procurement_methods(method_id),
    justification_id  SMALLINT      REFERENCES method_justifications(justification_id),
    procurement_type  VARCHAR(20)   NOT NULL
        CHECK (procurement_type IN ('GOODS','SERVICE','CONSTRUCTION','CONSULTANT','DESIGN')),
    budget_amount     NUMERIC(15,2) NOT NULL CHECK (budget_amount > 0),        -- วงเงินงบประมาณ
    reference_price   NUMERIC(15,2) CHECK (reference_price > 0),               -- ราคากลาง
    delivery_days     SMALLINT      NOT NULL CHECK (delivery_days > 0),        -- กำหนดเวลาส่งมอบ (ข้อ 22(5))
    status            VARCHAR(20)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT','IN_PROGRESS','AWARDED','CONTRACTED','CANCELLED','COMPLETED')),
    created_by        INT           NOT NULL REFERENCES users(user_id),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    row_version       INT           NOT NULL DEFAULT 1   -- optimistic locking กันบันทึกทับกัน
);
CREATE INDEX ix_projects_method_year ON projects (method_id, fiscal_year_be);
CREATE INDEX ix_projects_dept        ON projects (department_id);

-- รายการพัสดุ: ยอดรวม = quantity * unit_price → คำนวณใน VIEW ไม่เก็บซ้ำ (3NF)
CREATE TABLE project_items (
    item_id      SERIAL PRIMARY KEY,
    project_id   INT           NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    line_no      SMALLINT      NOT NULL,
    description  VARCHAR(500)  NOT NULL,
    quantity     NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    unit_th      VARCHAR(50)   NOT NULL,
    unit_price   NUMERIC(15,2) NOT NULL CHECK (unit_price >= 0),
    UNIQUE (project_id, line_no)
);

-- สถานะรายขั้นตอนของโครงการ (workflow instance)
CREATE TABLE project_steps (
    project_id    INT         NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    step_id       INT         NOT NULL REFERENCES workflow_steps(step_id),
    status        VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','IN_PROGRESS','SUBMITTED','APPROVED','REJECTED','SKIPPED')),
    submitted_by  INT REFERENCES users(user_id),
    submitted_at  TIMESTAMPTZ,
    approved_by   INT REFERENCES users(user_id),
    approved_at   TIMESTAMPTZ,
    step_data     JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- ค่าฟอร์มเฉพาะขั้นตอน (validated แล้ว)
    PRIMARY KEY (project_id, step_id)
    -- Segregation of Duties (ผู้เสนอ ≠ ผู้อนุมัติ) บังคับใน service ตาม PROC_SELF_APPROVAL_ROLES
    -- (ค่าเริ่มต้นให้หัวหน้าเจ้าหน้าที่อนุมัติรายการของตนเองได้ และบันทึก self_approval ใน audit_logs)
);

-- ใบเสนอราคา / ผลการพิจารณา
CREATE TABLE quotations (
    quotation_id   SERIAL PRIMARY KEY,
    project_id     INT           NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    vendor_id      INT           NOT NULL REFERENCES vendors(vendor_id),
    quoted_amount  NUMERIC(15,2) NOT NULL CHECK (quoted_amount > 0),
    agreed_amount  NUMERIC(15,2) CHECK (agreed_amount > 0),     -- ราคาที่ตกลง/ต่อรองได้
    submitted_at   TIMESTAMPTZ   NOT NULL,
    is_qualified   BOOLEAN,
    rank_no        SMALLINT,
    is_winner      BOOLEAN       NOT NULL DEFAULT FALSE,
    UNIQUE (project_id, vendor_id)
);
-- 1 โครงการมีผู้ชนะได้ 1 ราย (ระดับโครงการ; หากแยกรายการให้แตก lot เพิ่ม)
CREATE UNIQUE INDEX ux_quotations_one_winner ON quotations (project_id) WHERE is_winner;

-- -----------------------------------------------------------------------------
-- 5) คณะกรรมการ (Committees)
-- -----------------------------------------------------------------------------
CREATE TABLE committees (
    committee_id      SERIAL PRIMARY KEY,
    project_id        INT          NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    committee_type_id SMALLINT     NOT NULL REFERENCES committee_types(committee_type_id),
    order_no          VARCHAR(50),           -- เลขที่คำสั่งแต่งตั้ง
    order_date        DATE,
    UNIQUE (project_id, committee_type_id)
);

CREATE TABLE committee_members (
    committee_id  INT         NOT NULL REFERENCES committees(committee_id) ON DELETE CASCADE,
    personnel_id  INT         NOT NULL REFERENCES personnel(personnel_id),
    member_role   VARCHAR(20) NOT NULL CHECK (member_role IN ('CHAIR','MEMBER','MEMBER_SECRETARY','SOLE_INSPECTOR')),
    seq_no        SMALLINT    NOT NULL,
    PRIMARY KEY (committee_id, personnel_id),
    UNIQUE (committee_id, seq_no)
);
-- ประธานได้คนเดียวต่อคณะ
CREATE UNIQUE INDEX ux_committee_one_chair ON committee_members (committee_id) WHERE member_role = 'CHAIR';

-- -----------------------------------------------------------------------------
-- 6) แม่แบบเอกสาร (เฉพาะแบบฟอร์มมาตรฐานกรมบัญชีกลาง) และเอกสารที่สร้าง
-- -----------------------------------------------------------------------------
CREATE TABLE document_templates (
    template_id       SERIAL PRIMARY KEY,
    document_type_id  SMALLINT     NOT NULL REFERENCES document_types(document_type_id),
    version_label     VARCHAR(30)  NOT NULL,
    -- ต้องระบุแหล่งที่มาจากกรมบัญชีกลางเสมอ (กติกา: CGD Standard Forms Only)
    source_url        VARCHAR(500) CHECK (source_url IS NULL OR source_url ~* '^https://([a-z0-9-]+\.)*gprocurement\.go\.th/'),  -- ไม่บังคับ ถ้าใส่ต้องเป็นเว็บกรมบัญชีกลาง
    cgd_reference     VARCHAR(255) NOT NULL,   -- เลขหนังสือเวียน/ประกาศ กวพ. ที่กำหนดแบบ
    file_format       VARCHAR(5)   NOT NULL CHECK (file_format IN ('DOCX','XLSX')),
    storage_path      VARCHAR(500) NOT NULL,
    -- สำเนาไฟล์ในฐานข้อมูล: อยู่ในไฟล์สำรอง (pg_dump) ด้วย และสร้างไฟล์บน disk คืนได้เมื่อ storage ถูกล้าง
    -- (เช่น แพลตฟอร์มที่ระบบไฟล์ไม่ถาวร) — ตรวจกับ sha256 ทุกครั้งก่อนใช้
    content           BYTEA,
    sha256            CHAR(64)     NOT NULL,   -- ตรวจว่าไฟล์ไม่ถูกแก้ไขหลังตรวจรับรอง
    variable_schema   JSONB        NOT NULL,   -- รายชื่อตัวแปร + ชนิดข้อมูลที่แบบฟอร์มต้องการ
    effective_from    DATE         NOT NULL,
    is_active         BOOLEAN      NOT NULL DEFAULT FALSE,
    uploaded_by       INT          NOT NULL REFERENCES users(user_id),
    verified_by       INT          REFERENCES users(user_id),   -- ผู้ตรวจว่าตรงกับแบบกรมบัญชีกลาง
    UNIQUE (document_type_id, version_label),
    CHECK (verified_by IS NULL OR verified_by <> uploaded_by),
    CHECK (NOT is_active OR verified_by IS NOT NULL)   -- ต้องผ่านการตรวจก่อนเปิดใช้
);
-- แต่ละประเภทเอกสารใช้แม่แบบที่ active ได้ฉบับเดียว
CREATE UNIQUE INDEX ux_template_one_active ON document_templates (document_type_id) WHERE is_active;

CREATE TABLE generated_documents (
    document_id    BIGSERIAL PRIMARY KEY,
    project_id     INT          NOT NULL REFERENCES projects(project_id),
    template_id    INT          NOT NULL REFERENCES document_templates(template_id),
    document_no    VARCHAR(50),
    output_format  VARCHAR(5)   NOT NULL CHECK (output_format IN ('DOCX','PDF','XLSX')),
    storage_path   VARCHAR(500) NOT NULL,
    sha256         CHAR(64)     NOT NULL,
    render_context JSONB        NOT NULL,   -- snapshot ข้อมูล ณ เวลาสร้าง (หลักฐานตรวจสอบย้อนหลัง)
    generated_by   INT          NOT NULL REFERENCES users(user_id),
    generated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 7) การแจ้งเตือน LINE / สำรองข้อมูล / Audit
-- -----------------------------------------------------------------------------
CREATE TABLE notification_channels (
    channel_id     SMALLSERIAL PRIMARY KEY,
    name_th        VARCHAR(100) NOT NULL,
    line_to_enc    BYTEA        NOT NULL,       -- LINE groupId/userId (เข้ารหัส)
    line_to_hmac   CHAR(64)     UNIQUE,         -- blind index: กันลงทะเบียนกลุ่มเดียวกันซ้ำ (webhook ส่ง join ซ้ำได้)
    source         VARCHAR(10)  NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','WEBHOOK')),
    department_id  INT REFERENCES departments(department_id),
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE notification_logs (
    notification_id BIGSERIAL PRIMARY KEY,
    channel_id      SMALLINT    NOT NULL REFERENCES notification_channels(channel_id),
    project_id      INT         REFERENCES projects(project_id),
    retry_key       UUID        NOT NULL UNIQUE,   -- X-Line-Retry-Key กันส่งซ้ำ
    status          VARCHAR(10) NOT NULL CHECK (status IN ('SENT','FAILED')),
    http_status     SMALLINT,
    sent_by         INT         REFERENCES users(user_id),
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- แจ้งเตือนใกล้ครบกำหนดส่งมอบ: บันทึกว่าส่ง milestone ใดของโครงการไปแล้ว (PK กันส่งซ้ำแม้มีหลาย worker)
CREATE TABLE delivery_reminders (
    project_id  INT         NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    milestone   VARCHAR(10) NOT NULL,            -- D7, D3, D1, D0 (วันครบกำหนด), OVERDUE
    due_date    DATE        NOT NULL,            -- กำหนดส่งมอบที่ใช้คำนวณตอนส่ง (เปลี่ยนแล้วส่งใหม่ได้)
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, milestone, due_date)
);

CREATE TABLE backup_jobs (
    backup_job_id  SERIAL PRIMARY KEY,
    job_type       VARCHAR(10)  NOT NULL CHECK (job_type IN ('BACKUP','RESTORE')),
    file_name      VARCHAR(255) NOT NULL,
    sha256         CHAR(64),
    size_bytes     BIGINT,
    status         VARCHAR(10)  NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED')),
    error_message  TEXT,
    requested_by   INT          NOT NULL REFERENCES users(user_id),
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ
);

-- Audit log แบบ append-only + hash chain: แก้/ลบแถวใดจะทำให้ hash ถัดไปไม่ตรง (tamper-evident)
CREATE TABLE audit_logs (
    audit_id      BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    user_id       INT          REFERENCES users(user_id),
    action        VARCHAR(50)  NOT NULL,       -- LOGIN, LOGIN_FAILED, CREATE, UPDATE, EXPORT, LINE_SEND, BACKUP, RESTORE ...
    entity_table  VARCHAR(60),
    entity_id     VARCHAR(60),
    old_values    JSONB,
    new_values    JSONB,
    ip_address    INET,
    user_agent    VARCHAR(300),
    request_id    UUID,
    prev_hash     CHAR(64)     NOT NULL,
    row_hash      CHAR(64)     NOT NULL UNIQUE
);
CREATE INDEX ix_audit_entity ON audit_logs (entity_table, entity_id);
CREATE INDEX ix_audit_user_time ON audit_logs (user_id, occurred_at);

-- =============================================================================
-- Triggers: ด่านสุดท้ายของกฎทางธุรกิจในระดับฐานข้อมูล (defense in depth)
-- =============================================================================

-- (ก) วงเงินต้องอยู่ในช่วงที่วิธีจัดหา/อนุมาตราอนุญาต
CREATE OR REPLACE FUNCTION fn_check_project_budget() RETURNS trigger AS $$
DECLARE
    m procurement_methods%ROWTYPE;
    j_max NUMERIC(15,2);
    j_method SMALLINT;
BEGIN
    SELECT * INTO m FROM procurement_methods WHERE method_id = NEW.method_id;
    IF m.min_budget_exclusive IS NOT NULL AND NEW.budget_amount <= m.min_budget_exclusive THEN
        RAISE EXCEPTION 'วงเงิน % ต่ำกว่าเกณฑ์ของวิธี % (ต้องเกิน %)', NEW.budget_amount, m.name_th, m.min_budget_exclusive
            USING ERRCODE = 'check_violation';
    END IF;
    IF m.max_budget_inclusive IS NOT NULL AND NEW.budget_amount > m.max_budget_inclusive THEN
        RAISE EXCEPTION 'วงเงิน % เกินเพดานของวิธี % (ไม่เกิน %)', NEW.budget_amount, m.name_th, m.max_budget_inclusive
            USING ERRCODE = 'check_violation';
    END IF;
    IF m.category IN ('SELECTION','SPECIFIC') AND NEW.justification_id IS NULL THEN
        RAISE EXCEPTION 'วิธี % ต้องระบุเหตุผลตาม พ.ร.บ. มาตรา 56', m.name_th USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.justification_id IS NOT NULL THEN
        SELECT method_id, max_budget_inclusive INTO j_method, j_max
          FROM method_justifications WHERE justification_id = NEW.justification_id;
        IF j_method <> NEW.method_id THEN
            RAISE EXCEPTION 'เหตุผลที่เลือกไม่ตรงกับวิธีจัดหา' USING ERRCODE = 'check_violation';
        END IF;
        IF j_max IS NOT NULL AND NEW.budget_amount > j_max THEN
            RAISE EXCEPTION 'วงเงิน % เกินเพดานของอนุมาตราที่อ้าง (ไม่เกิน %)', NEW.budget_amount, j_max
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_budget BEFORE INSERT OR UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION fn_check_project_budget();

-- (ข) ระเบียบ ข้อ 26 (หลักถ่วงดุล): ผู้เป็นกรรมการพิจารณาผล/คัดเลือก
--     ห้ามเป็นกรรมการตรวจรับในโครงการเดียวกัน
CREATE OR REPLACE FUNCTION fn_check_committee_conflict() RETURNS trigger AS $$
DECLARE
    v_project INT;
    v_type    VARCHAR(40);
BEGIN
    SELECT c.project_id, ct.code INTO v_project, v_type
      FROM committees c JOIN committee_types ct USING (committee_type_id)
     WHERE c.committee_id = NEW.committee_id;

    IF EXISTS (
        SELECT 1
          FROM committee_members cm
          JOIN committees c       ON c.committee_id = cm.committee_id
          JOIN committee_types ct ON ct.committee_type_id = c.committee_type_id
         WHERE c.project_id = v_project
           AND cm.personnel_id = NEW.personnel_id
           AND cm.committee_id <> NEW.committee_id
           AND (   (v_type = 'INSPECTION' AND ct.code IN ('BID_EVALUATION','SELECTION'))
                OR (v_type IN ('BID_EVALUATION','SELECTION') AND ct.code = 'INSPECTION'))
    ) THEN
        RAISE EXCEPTION 'บุคลากร % เป็นกรรมการพิจารณาผลและกรรมการตรวจรับในโครงการเดียวกันไม่ได้', NEW.personnel_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_committee_conflict BEFORE INSERT OR UPDATE ON committee_members
    FOR EACH ROW EXECUTE FUNCTION fn_check_committee_conflict();

-- (ค) Audit hash chain: row_hash = SHA256(prev_hash || เนื้อหาแถว)
CREATE OR REPLACE FUNCTION fn_audit_hash_chain() RETURNS trigger AS $$
DECLARE
    v_prev CHAR(64);
BEGIN
    -- serialize การเขียน audit เพื่อให้ chain เป็นเส้นตรงเส้นเดียว
    PERFORM pg_advisory_xact_lock(hashtext('audit_logs_chain'));
    SELECT row_hash INTO v_prev FROM audit_logs ORDER BY audit_id DESC LIMIT 1;
    NEW.prev_hash := COALESCE(v_prev, repeat('0', 64));
    NEW.row_hash := encode(digest(
        NEW.prev_hash || '|' || NEW.occurred_at::text || '|' || COALESCE(NEW.user_id::text, '') || '|' ||
        NEW.action || '|' || COALESCE(NEW.entity_table, '') || '|' || COALESCE(NEW.entity_id, '') || '|' ||
        COALESCE(NEW.old_values::text, '') || '|' || COALESCE(NEW.new_values::text, ''), 'sha256'), 'hex');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_hash BEFORE INSERT ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_hash_chain();

-- ตรวจความต่อเนื่องของ hash chain: คืน audit_id แรกที่ผิดปกติ (NULL = สมบูรณ์)
CREATE OR REPLACE FUNCTION fn_verify_audit_chain() RETURNS BIGINT AS $$
    SELECT audit_id FROM (
        SELECT audit_id, prev_hash, row_hash,
               COALESCE(lag(row_hash) OVER (ORDER BY audit_id), repeat('0', 64)) AS expected_prev,
               encode(digest(
                   prev_hash || '|' || occurred_at::text || '|' || COALESCE(user_id::text, '') || '|' ||
                   action || '|' || COALESCE(entity_table, '') || '|' || COALESCE(entity_id, '') || '|' ||
                   COALESCE(old_values::text, '') || '|' || COALESCE(new_values::text, ''), 'sha256'), 'hex')
                   AS expected_hash
          FROM audit_logs) t
     WHERE prev_hash <> expected_prev OR row_hash <> expected_hash
     ORDER BY audit_id LIMIT 1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_audit_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs เป็น append-only: ห้าม UPDATE/DELETE' USING ERRCODE = 'insufficient_privilege';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_immutable();

-- =============================================================================
-- Views สำหรับ Dashboard / Report (ค่าที่คำนวณได้อยู่ที่นี่ ไม่อยู่ในตาราง)
-- =============================================================================
CREATE VIEW v_project_totals AS
SELECT p.project_id,
       COALESCE(SUM(i.quantity * i.unit_price), 0)::NUMERIC(15,2) AS items_total
  FROM projects p
  LEFT JOIN project_items i ON i.project_id = p.project_id
 GROUP BY p.project_id;

CREATE VIEW v_award_summary AS
SELECT p.project_id, p.fiscal_year_be, p.department_id, m.code AS method_code, m.name_th AS method_name_th,
       p.budget_amount, p.status,
       date_trunc('month', ps.approved_at)::date AS award_month,
       COALESCE(q.agreed_amount, q.quoted_amount) AS award_amount,
       p.budget_amount - COALESCE(q.agreed_amount, q.quoted_amount) AS savings_amount
  FROM projects p
  JOIN procurement_methods m ON m.method_id = p.method_id
  LEFT JOIN quotations q ON q.project_id = p.project_id AND q.is_winner
  LEFT JOIN workflow_steps ws ON ws.method_id = p.method_id AND ws.code = 'AWARD_APPROVAL'
  LEFT JOIN project_steps ps ON ps.project_id = p.project_id AND ps.step_id = ws.step_id
                            AND ps.status = 'APPROVED';

-- สิทธิ์ระดับ DB: แอปพลิเคชันใช้ role ที่ไม่มีสิทธิ์ UPDATE/DELETE audit_logs
-- (รันโดย DBA หลังสร้าง role 'procurement_app')
-- REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM procurement_app;
