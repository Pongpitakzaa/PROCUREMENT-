import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { DynamicStepForm } from "../components/DynamicStepForm";
import { StepAttachments } from "../components/StepAttachments";
import { StatusBadge } from "../components/StatusBadge";
import { WorkflowStepper } from "../components/WorkflowStepper";
import type { ProjectDetail } from "../types";

interface Props {
  projectId: number;
  canApprove: boolean;
  canSubmit: boolean;
  canShareLine: boolean;
  myUserId: number | null;
  onBack: () => void;
}

export function ProjectDetailPage({ projectId, canApprove, canSubmit, canShareLine, myUserId, onBack }: Props) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setProject(await api<ProjectDetail>(`/api/projects/${projectId}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="project">
      <button type="button" className="link" onClick={onBack}>← รายการโครงการ</button>
      {error && <p role="alert" className="banner-error">{error}</p>}
      {notice && <p role="status" className="banner-ok" onClick={() => setNotice(null)}>{notice}</p>}
      {project && (
        <>
          <div className="project-head">
            <h2>{project.project_code} — {project.title_th}</h2>
            <p>
              {project.method.name_th} · วงเงิน{" "}
              {Number(project.budget_amount).toLocaleString("th-TH", { minimumFractionDigits: 2 })} บาท ·{" "}
              <StatusBadge status={project.status} />
            </p>
          </div>
          <div className="layout">
            <WorkflowStepper project={project} activeStep={activeStep} canShareLine={canShareLine}
                             onSelect={setActiveStep} onError={setError}
                             onNotice={(m) => { setError(null); setNotice(m); }} />
            {activeStep ? (
              <div className="step-panel">
                <DynamicStepForm
                  // row_version เปลี่ยนหลังบันทึก → remount เพื่อโหลดสถานะใหม่ (ฟอร์มถูกล็อก)
                  key={`${activeStep}-${project.row_version}`}
                  projectId={project.project_id}
                  stepCode={activeStep}
                  canApprove={canApprove}
                  canRevert={canApprove || canSubmit}
                  onSubmitted={load}
                />
                <StepAttachments key={`att-${activeStep}`} projectId={project.project_id} stepCode={activeStep}
                                 canUpload={canSubmit || canApprove} canApprove={canApprove} myUserId={myUserId} />
              </div>
            ) : (
              <div className="card empty">เลือกขั้นตอนทางซ้ายเพื่อกรอกข้อมูลหรือดูรายละเอียด</div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
