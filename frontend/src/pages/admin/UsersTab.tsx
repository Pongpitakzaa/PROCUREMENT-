/**
 * แท็บจัดการผู้ใช้งาน (user:manage)
 * - รายชื่อผู้ใช้ + สถานะ (ใช้งาน / ระงับ / ล็อกจากรหัสผิด)
 * - เพิ่มผู้ใช้: เลือกบุคลากรเดิม หรือเพิ่มบุคลากรใหม่ (เลขบัตรประชาชนเข้ารหัส) → ระบบสุ่มรหัสผ่านชั่วคราวให้
 * - แก้บทบาท / ระงับ / ปลดล็อก / รีเซ็ตรหัสผ่าน (ทุกการกระทำถูกบันทึก Audit)
 * กฎเดียวกับ backend: แบ่งแยกหน้าที่ระดับบทบาท + ห้ามระงับ/ถอด ADMIN ของตนเอง
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../api";
import type { Department, ManagedUser, RoleCode, RoleInfo } from "../../types";
import { roleProblems, USERNAME_RE } from "../../userValidation";
import { isValidThaiTaxId } from "../../validation";

const ROLE_TH: Record<RoleCode, string> = {
  PROCUREMENT_OFFICER: "เจ้าหน้าที่พัสดุ", HEAD_OF_PROCUREMENT: "หัวหน้าเจ้าหน้าที่", EXECUTIVE: "ผู้บริหาร",
  AUDITOR: "ผู้ตรวจสอบภายใน", ADMIN: "ผู้ดูแลระบบ",
};
const EMPLOYMENT_TH = {
  CIVIL_SERVANT: "ข้าราชการ", GOV_EMPLOYEE: "พนักงานราชการ", PERMANENT_EMPLOYEE: "ลูกจ้างประจำ",
  STATE_OFFICIAL: "เจ้าหน้าที่ของรัฐอื่น", OTHER: "อื่น ๆ",
} as const;
const thDateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("th-TH", { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const errText = (e: unknown) =>
  e instanceof ApiError ? [e.message, ...e.violations.map((v) => `${v.field ? `${v.field}: ` : ""}${v.message}`)].join(" — ") : "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้";

type Panel = { kind: "none" } | { kind: "create" } | { kind: "edit"; id: number } | { kind: "secret"; username: string; password: string; reason: string };

export function UsersTab({ meId }: { meId: number }) {
  const [users, setUsers] = useState<ManagedUser[] | null>(null);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [q, setQ] = useState("");
  const [panel, setPanel] = useState<Panel>({ kind: "none" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    api<ManagedUser[]>("/api/admin/users").then(setUsers).catch((e) => setMsg({ ok: false, text: errText(e) }));
  }, []);
  useEffect(() => {
    load();
    api<RoleInfo[]>("/api/admin/roles").then(setRoles);
  }, [load]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (users ?? []).filter((u) => !t || u.username.includes(t) || u.full_name_th.toLowerCase().includes(t));
  }, [users, q]);
  const counts = useMemo(() => ({
    active: users?.filter((u) => u.is_active).length ?? 0,
    locked: users?.filter((u) => u.is_locked).length ?? 0,
    inactive: users?.filter((u) => !u.is_active).length ?? 0,
  }), [users]);
  const selected = panel.kind === "edit" ? users?.find((u) => u.user_id === panel.id) : undefined;

  return (
    <div className="admin-grid">
      <div className="card panel-lg">
        <div className="section-head">
          <div>
            <h3>ผู้ใช้งาน</h3>
            <p className="muted small">
              ใช้งาน {counts.active} · ระงับ {counts.inactive}{counts.locked > 0 && <> · <span className="text-err">ล็อก {counts.locked}</span></>}
            </p>
          </div>
          <button type="button" onClick={() => { setMsg(null); setPanel({ kind: "create" }); }}>+ เพิ่มผู้ใช้</button>
        </div>
        {msg && <p role="status" className={msg.ok ? "banner-ok" : "banner-error"}>{msg.text}</p>}
        <input type="search" className="user-search" placeholder="ค้นหาชื่อหรือชื่อผู้ใช้" value={q}
               onChange={(e) => setQ(e.target.value)} aria-label="ค้นหาผู้ใช้" />
        <ul className="user-list">
          {shown.map((u) => (
            <li key={u.user_id}>
              <button type="button" className={`user-row ${selected?.user_id === u.user_id ? "selected" : ""} ${u.is_active ? "" : "inactive"}`}
                      onClick={() => { setMsg(null); setPanel({ kind: "edit", id: u.user_id }); }}>
                <span className="avatar" aria-hidden>{u.full_name_th.replace(/^(นาย|นางสาว|นาง)/, "").trim().charAt(0)}</span>
                <span className="user-main">
                  <strong>{u.full_name_th}{u.user_id === meId && <span className="muted"> (คุณ)</span>}</strong>
                  <span className="muted small">{u.username} · {u.position_th}</span>
                  <span className="role-chips">{u.roles.map((r) => <span key={r} className={`role-chip role-${r.toLowerCase()}`}>{ROLE_TH[r]}</span>)}</span>
                </span>
                <span className="user-side">
                  {!u.is_active ? <span className="badge">ระงับ</span>
                    : u.is_locked ? <span className="badge badge-cancelled">ล็อก</span>
                    : <span className="badge badge-completed">ใช้งาน</span>}
                  <small className="muted">เข้าล่าสุด {thDateTime(u.last_login_at)}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {users && shown.length === 0 && <div className="empty">ไม่พบผู้ใช้</div>}
      </div>

      <aside className="card panel-lg">
        {panel.kind === "none" && (
          <>
            <h3>บทบาทและสิทธิ์</h3>
            <ul className="role-guide">
              {roles.map((r) => (
                <li key={r.code}><span className={`role-chip role-${r.code.toLowerCase()}`}>{ROLE_TH[r.code]}</span> {r.description_th}</li>
              ))}
            </ul>
            <p className="muted small">หลักแบ่งแยกหน้าที่: ผู้ดูแลระบบไม่ทำรายการพัสดุ · ผู้ตรวจสอบมีบทบาทเดียว · ผู้เสนอกับผู้อนุมัติต้องเป็นคนละคน</p>
          </>
        )}
        {panel.kind === "create" && (
          <CreateUserForm roles={roles} onCancel={() => setPanel({ kind: "none" })}
                          onCreated={(username, password) => { load(); setPanel({ kind: "secret", username, password, reason: "สร้างบัญชีแล้ว" }); }} />
        )}
        {panel.kind === "edit" && selected && (
          <EditUser key={selected.user_id} user={selected} roles={roles} isMe={selected.user_id === meId}
                    onChanged={(text) => { load(); setMsg({ ok: true, text }); }}
                    onError={(text) => setMsg({ ok: false, text })}
                    onReset={(password) => { load(); setPanel({ kind: "secret", username: selected.username, password, reason: "รีเซ็ตรหัสผ่านแล้ว" }); }} />
        )}
        {panel.kind === "secret" && (
          <SecretReveal {...panel} onDone={() => setPanel({ kind: "none" })} />
        )}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function SecretReveal({ username, password, reason, onDone }: { username: string; password: string; reason: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="secret">
      <h3>{reason}: {username}</h3>
      <p className="muted small">รหัสผ่านชั่วคราว (แสดงครั้งเดียว ระบบไม่เก็บค่านี้ไว้)</p>
      <div className="secret-box">
        <code>{password}</code>
        <button type="button" className="ghost" onClick={() => navigator.clipboard?.writeText(password).then(() => setCopied(true))}>
          {copied ? "คัดลอกแล้ว" : "คัดลอก"}
        </button>
      </div>
      <ul className="tips">
        <li>ส่งให้ผู้ใช้ทางช่องทางที่ปลอดภัย (ไม่ส่งในกลุ่มแชต)</li>
        <li>ให้ผู้ใช้เปลี่ยนรหัสผ่านทันทีที่เมนู “เปลี่ยนรหัสผ่าน” มุมขวาบน</li>
      </ul>
      <button type="button" className="full" onClick={onDone}>เสร็จสิ้น</button>
    </div>
  );
}

function RolePicker({ roles, value, onChange, disabledCodes = [] }: {
  roles: RoleInfo[]; value: RoleCode[]; onChange: (v: RoleCode[]) => void; disabledCodes?: RoleCode[];
}) {
  const problems = roleProblems(value);
  return (
    <fieldset className="role-picker">
      <legend>บทบาท</legend>
      {roles.map((r) => (
        <label key={r.code} className={value.includes(r.code) ? "on" : ""}>
          <input type="checkbox" checked={value.includes(r.code)} disabled={disabledCodes.includes(r.code)}
                 onChange={(e) => onChange(e.target.checked ? [...value, r.code] : value.filter((x) => x !== r.code))} />
          <span><strong>{ROLE_TH[r.code]}</strong><small>{r.description_th}</small></span>
        </label>
      ))}
      {problems.map((p) => <small key={p} role="alert" className="error">{p}</small>)}
    </fieldset>
  );
}

/* ------------------------------------------------------------------ */
function EditUser({ user, roles, isMe, onChanged, onError, onReset }: {
  user: ManagedUser; roles: RoleInfo[]; isMe: boolean;
  onChanged: (msg: string) => void; onError: (msg: string) => void; onReset: (password: string) => void;
}) {
  const [draft, setDraft] = useState<RoleCode[]>(user.roles);
  const [confirmReset, setConfirmReset] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = [...draft].sort().join() !== [...user.roles].sort().join();

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (e) { onError(errText(e)); } finally { setBusy(false); }
  };
  const patch = (body: object, text: string) => run(async () => {
    await api(`/api/admin/users/${user.user_id}`, { method: "PATCH", body: JSON.stringify(body) });
    onChanged(text);
  });

  return (
    <div className="edit-user">
      <div className="detail-head">
        <div>
          <h3>{user.full_name_th}</h3>
          <p className="muted">{user.username} · {user.position_th}</p>
        </div>
      </div>
      <dl className="info-list compact">
        <dt>เข้าระบบล่าสุด</dt><dd>{thDateTime(user.last_login_at)}</dd>
        <dt>เปลี่ยนรหัสผ่านล่าสุด</dt><dd>{thDateTime(user.password_changed_at)}</dd>
        <dt>รหัสผิดสะสม</dt><dd>{user.failed_login_count} ครั้ง{user.is_locked && <> · <span className="text-err">ล็อกถึง {thDateTime(user.locked_until)}</span></>}</dd>
      </dl>

      <RolePicker roles={roles} value={draft} onChange={setDraft} disabledCodes={isMe ? ["ADMIN"] : []} />
      {isMe && <p className="muted small">ถอดบทบาทผู้ดูแลระบบของตนเองไม่ได้ (กันระบบไม่มีผู้ดูแล)</p>}
      <div className="form-actions">
        <button type="button" className="ghost" disabled={!dirty || busy} onClick={() => setDraft(user.roles)}>คืนค่า</button>
        <button type="button" disabled={!dirty || busy || roleProblems(draft).length > 0}
                onClick={() => patch({ roles: draft }, `บันทึกบทบาทของ ${user.username} แล้ว`)}>บันทึกบทบาท</button>
      </div>

      <h4>บัญชี</h4>
      <div className="account-actions">
        <label className="switch">
          <input type="checkbox" checked={user.is_active} disabled={isMe || busy}
                 onChange={() => patch({ is_active: !user.is_active },
                   user.is_active ? `ระงับบัญชี ${user.username} แล้ว (ออกจากระบบทันที)` : `เปิดใช้บัญชี ${user.username} แล้ว`)} />
          <span>{user.is_active ? "บัญชีใช้งานอยู่" : "บัญชีถูกระงับ"}</span>
        </label>
        {user.is_locked && (
          <button type="button" className="ghost" disabled={busy} onClick={() => run(async () => {
            await api(`/api/admin/users/${user.user_id}/unlock`, { method: "POST" });
            onChanged(`ปลดล็อก ${user.username} แล้ว`);
          })}>ปลดล็อก</button>
        )}
        {!isMe && !confirmReset && (
          <button type="button" className="ghost danger" disabled={busy} onClick={() => setConfirmReset(true)}>รีเซ็ตรหัสผ่าน</button>
        )}
      </div>
      {confirmReset && (
        <div className="confirm-box">
          <p>ระบบจะสร้างรหัสผ่านชั่วคราวใหม่ และ <strong>{user.username}</strong> จะออกจากระบบทุกอุปกรณ์ทันที</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => setConfirmReset(false)}>ยกเลิก</button>
            <button type="button" className="danger-solid" disabled={busy} onClick={() => run(async () => {
              const r = await api<{ temporary_password: string }>(`/api/admin/users/${user.user_id}/reset-password`, { method: "POST" });
              onReset(r.temporary_password);
            })}>ยืนยันรีเซ็ต</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
interface PersonDraft {
  department_id: string; title_th: string; first_name_th: string; last_name_th: string;
  position_th: string; employment_type: keyof typeof EMPLOYMENT_TH; citizen_id: string;
}

function CreateUserForm({ roles, onCancel, onCreated }: {
  roles: RoleInfo[]; onCancel: () => void; onCreated: (username: string, password: string) => void;
}) {
  const [source, setSource] = useState<"existing" | "new">("existing");
  const [people, setPeople] = useState<{ personnel_id: number; full_name_th: string; position_th: string }[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [personnelId, setPersonnelId] = useState("");
  const [person, setPerson] = useState<PersonDraft>({ department_id: "", title_th: "นาย", first_name_th: "", last_name_th: "",
                                                      position_th: "", employment_type: "CIVIL_SERVANT", citizen_id: "" });
  const [username, setUsername] = useState("");
  const [picked, setPicked] = useState<RoleCode[]>(["PROCUREMENT_OFFICER"]);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<typeof people>("/api/admin/personnel-without-account").then((p) => { setPeople(p); if (!p.length) setSource("new"); });
    api<Department[]>("/api/departments").then((d) => { setDepartments(d); if (d.length === 1) setPerson((x) => ({ ...x, department_id: String(d[0]!.department_id) })); });
  }, []);

  const errors: Record<string, string> = {};
  if (!USERNAME_RE.test(username)) errors.username = "a-z, 0-9, จุด ขีด หรือ _ ยาว 3–60 ตัว (ตัวพิมพ์เล็ก)";
  if (source === "existing" && !personnelId) errors.personnel_id = "เลือกบุคลากร";
  if (source === "new") {
    if (!person.department_id) errors.department_id = "เลือกหน่วยงาน";
    if (!person.first_name_th.trim()) errors.first_name_th = "กรอกชื่อ";
    if (!person.last_name_th.trim()) errors.last_name_th = "กรอกนามสกุล";
    if (!person.position_th.trim()) errors.position_th = "กรอกตำแหน่ง";
    if (!isValidThaiTaxId(person.citizen_id)) errors.citizen_id = "เลขประจำตัวประชาชน 13 หลักไม่ถูกต้อง";
    else if (person.citizen_id.startsWith("0")) errors.citizen_id = "เลขที่ขึ้นต้นด้วย 0 เป็นเลขนิติบุคคล";
  }
  const roleErrs = roleProblems(picked);
  const err = (k: string) => (showAll ? errors[k] : undefined);
  const setP = (k: keyof PersonDraft, v: string) => setPerson((x) => ({ ...x, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setShowAll(true);
    if (Object.keys(errors).length || roleErrs.length) return;
    setBusy(true);
    setError(null);
    try {
      const body = source === "existing"
        ? { username, roles: picked, personnel_id: Number(personnelId) }
        : { username, roles: picked, personnel: { ...person, department_id: Number(person.department_id),
            first_name_th: person.first_name_th.trim(), last_name_th: person.last_name_th.trim(), position_th: person.position_th.trim() } };
      const r = await api<{ temporary_password: string }>("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
      onCreated(username, r.temporary_password);
    } catch (e2) {
      setError(errText(e2));
    } finally {
      setBusy(false);
    }
  }

  const field = (k: string, label: string, input: React.ReactNode, help?: string) => (
    <div className={`field ${err(k) ? "has-error" : ""}`}>
      <label htmlFor={`u-${k}`}>{label}</label>
      {input}
      {help && !err(k) && <small className="help">{help}</small>}
      {err(k) && <small role="alert" className="error">{err(k)}</small>}
    </div>
  );

  return (
    <form onSubmit={submit} noValidate className="create-user">
      <h3>เพิ่มผู้ใช้</h3>
      <div className="chips" role="radiogroup" aria-label="แหล่งข้อมูลบุคลากร">
        {(["existing", "new"] as const).map((s) => (
          <label key={s} className={`chip ${source === s ? "on" : ""}`}>
            <input type="radio" name="source" checked={source === s} onChange={() => setSource(s)} disabled={s === "existing" && !people.length} />
            {s === "existing" ? `บุคลากรเดิม (${people.length})` : "เพิ่มบุคลากรใหม่"}
          </label>
        ))}
      </div>

      {source === "existing" ? field("personnel_id", "บุคลากรที่ยังไม่มีบัญชี", (
        <select id="u-personnel_id" value={personnelId} onChange={(e) => setPersonnelId(e.target.value)}>
          <option value="">— เลือก —</option>
          {people.map((p) => <option key={p.personnel_id} value={p.personnel_id}>{p.full_name_th} — {p.position_th}</option>)}
        </select>
      )) : (
        <div className="new-person">
          {field("department_id", "หน่วยงาน", (
            <select id="u-department_id" value={person.department_id} onChange={(e) => setP("department_id", e.target.value)}>
              <option value="">— เลือก —</option>
              {departments.map((d) => <option key={d.department_id} value={d.department_id}>{d.name_th}</option>)}
            </select>
          ))}
          <div className="name-row">
            {field("title_th", "คำนำหน้า", (
              <select id="u-title_th" value={person.title_th} onChange={(e) => setP("title_th", e.target.value)}>
                {["นาย", "นาง", "นางสาว"].map((t) => <option key={t}>{t}</option>)}
              </select>
            ))}
            {field("first_name_th", "ชื่อ", <input id="u-first_name_th" maxLength={100} value={person.first_name_th} onChange={(e) => setP("first_name_th", e.target.value)} />)}
            {field("last_name_th", "นามสกุล", <input id="u-last_name_th" maxLength={100} value={person.last_name_th} onChange={(e) => setP("last_name_th", e.target.value)} />)}
          </div>
          <div className="grid-2">
            {field("position_th", "ตำแหน่ง", <input id="u-position_th" maxLength={150} value={person.position_th} onChange={(e) => setP("position_th", e.target.value)} />)}
            {field("employment_type", "ประเภทบุคลากร", (
              <select id="u-employment_type" value={person.employment_type} onChange={(e) => setP("employment_type", e.target.value)}>
                {Object.entries(EMPLOYMENT_TH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            ))}
          </div>
          {field("citizen_id", "เลขประจำตัวประชาชน", (
            <input id="u-citizen_id" inputMode="numeric" maxLength={13} value={person.citizen_id}
                   onChange={(e) => setP("citizen_id", e.target.value.replace(/\D/g, ""))} />
          ), "เข้ารหัสก่อนบันทึก · ใช้ตรวจบุคลากรซ้ำ · ไม่แสดงในหน้าจอใด")}
        </div>
      )}

      {field("username", "ชื่อผู้ใช้", (
        <input id="u-username" autoComplete="off" maxLength={60} value={username}
               onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s/g, ""))} placeholder="เช่น somchai.j" />
      ))}
      <RolePicker roles={roles} value={picked} onChange={setPicked} />
      {error && <p role="alert" className="banner-error">{error}</p>}
      <p className="muted small">ระบบจะสร้างรหัสผ่านชั่วคราวให้ และแสดงเพียงครั้งเดียว</p>
      <div className="form-actions">
        <button type="button" className="ghost" onClick={onCancel}>ยกเลิก</button>
        <button type="submit" disabled={busy}>{busy ? "กำลังสร้าง…" : "สร้างผู้ใช้"}</button>
      </div>
    </form>
  );
}
