import { useCallback, useState } from "react";
import { ApiError, api, isLoggedIn, login } from "./api";
import { DynamicStepForm } from "./components/DynamicStepForm";
import { WorkflowStepper } from "./components/WorkflowStepper";
import type { ProjectDetail } from "./types";

export function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [activeStep, setActiveStep] = useState<string | null>(null);

  const loadProject = useCallback(async (id: number) => {
    setProject(await api<ProjectDetail>(`/api/projects/${id}`));
  }, []);

  if (!authed) {
    return (
      <form
        className="login"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          try {
            await login(String(f.get("username")), String(f.get("password")));
            setAuthed(true);
          } catch (err) {
            setError(err instanceof ApiError ? err.message : "เข้าสู่ระบบไม่สำเร็จ");
          }
        }}
      >
        <h1>ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ</h1>
        {error && <p role="alert">{error}</p>}
        <input name="username" autoComplete="username" placeholder="ชื่อผู้ใช้" required />
        <input name="password" type="password" autoComplete="current-password" placeholder="รหัสผ่าน" required />
        <button type="submit">เข้าสู่ระบบ</button>
      </form>
    );
  }

  return (
    <main>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const id = Number(new FormData(e.currentTarget).get("pid"));
          if (Number.isInteger(id) && id > 0) loadProject(id).catch((err) => setError(String(err.message)));
        }}
      >
        <input name="pid" type="number" min={1} placeholder="รหัสโครงการ" />
        <button type="submit">เปิดโครงการ</button>
      </form>
      {error && <p role="alert">{error}</p>}

      {project && (
        <section className="project">
          <h2>{project.project_code} — {project.title_th}</h2>
          <p>{project.method.name_th} · วงเงิน {Number(project.budget_amount).toLocaleString("th-TH", { minimumFractionDigits: 2 })} บาท</p>
          <WorkflowStepper project={project} activeStep={activeStep} onSelect={setActiveStep} />
          {activeStep && (
            <DynamicStepForm
              key={activeStep}
              projectId={project.project_id}
              stepCode={activeStep}
              onSubmitted={() => loadProject(project.project_id)}
            />
          )}
        </section>
      )}
    </main>
  );
}
