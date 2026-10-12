import { useCallback, useEffect, useState } from "react";
import { ApiError, api, isLoggedIn, login, logout } from "./api";
import { DynamicStepForm } from "./components/DynamicStepForm";
import { WorkflowStepper } from "./components/WorkflowStepper";
import type { ProjectDetail } from "./types";

interface Me { full_name_th: string; roles: string[] }

const ROLE_TH: Record<string, string> = {
  ADMIN: "ผู้ดูแลระบบ", PROCUREMENT_OFFICER: "เจ้าหน้าที่พัสดุ", HEAD_OF_PROCUREMENT: "หัวหน้าเจ้าหน้าที่",
  EXECUTIVE: "ผู้บริหาร", AUDITOR: "ผู้ตรวจสอบ",
};

export function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [activeStep, setActiveStep] = useState<string | null>(null);

  useEffect(() => {
    if (authed) api<Me>("/api/auth/me").then(setMe).catch(() => setAuthed(false));
  }, [authed]);

  const loadProject = useCallback(async (id: number) => {
    setError(null);
    setProject(await api<ProjectDetail>(`/api/projects/${id}`));
  }, []);

  if (!authed) {
    return (
      <div className="login-page">
        <form
          className="login card"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            try {
              await login(String(f.get("username")), String(f.get("password")));
              setError(null);
              setAuthed(true);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "เข้าสู่ระบบไม่สำเร็จ");
            }
          }}
        >
          <div className="brand">◆ e-Procurement</div>
          <h1>ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ</h1>
          {error && <p role="alert" className="banner-error">{error}</p>}
          <label htmlFor="username">ชื่อผู้ใช้</label>
          <input id="username" name="username" autoComplete="username" required />
          <label htmlFor="password">รหัสผ่าน</label>
          <input id="password" name="password" type="password" autoComplete="current-password" required />
          <button type="submit">เข้าสู่ระบบ</button>
        </form>
      </div>
    );
  }

  return (
    <>
      <header className="app-header">
        <div className="brand">◆ e-Procurement <span>· ระบบจัดซื้อจัดจ้าง</span></div>
        {me && (
          <div className="user">
            <span>{me.full_name_th}</span>
            <small>{me.roles.map((r) => ROLE_TH[r] ?? r).join(", ")}</small>
            <button type="button" className="ghost" onClick={() => { logout(); setAuthed(false); setProject(null); }}>
              ออกจากระบบ
            </button>
          </div>
        )}
      </header>

      <main className="app">
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            const id = Number(new FormData(e.currentTarget).get("pid"));
            setActiveStep(null);
            if (Number.isInteger(id) && id > 0) loadProject(id).catch((err) => setError(String(err.message)));
          }}
        >
          <input name="pid" type="number" min={1} placeholder="รหัสโครงการ" aria-label="รหัสโครงการ" />
          <button type="submit">เปิดโครงการ</button>
        </form>
        {error && <p role="alert" className="banner-error">{error}</p>}

        {project ? (
          <section className="project">
            <div className="project-head">
              <h2>{project.project_code} — {project.title_th}</h2>
              <p>
                {project.method.name_th} · วงเงิน{" "}
                {Number(project.budget_amount).toLocaleString("th-TH", { minimumFractionDigits: 2 })} บาท
              </p>
            </div>
            <div className="layout">
              <WorkflowStepper project={project} activeStep={activeStep} onSelect={setActiveStep} onError={setError} />
              {activeStep ? (
                <DynamicStepForm
                  // row_version เปลี่ยนหลังบันทึก → remount เพื่อโหลดสถานะใหม่ (ฟอร์มถูกล็อก)
                  key={`${activeStep}-${project.row_version}`}
                  projectId={project.project_id}
                  stepCode={activeStep}
                  onSubmitted={() => loadProject(project.project_id)}
                />
              ) : (
                <div className="card empty">เลือกขั้นตอนทางซ้ายเพื่อกรอกข้อมูลหรือดูรายละเอียด</div>
              )}
            </div>
          </section>
        ) : (
          <div className="card empty">กรอกรหัสโครงการเพื่อเริ่มต้น</div>
        )}
      </main>
    </>
  );
}
