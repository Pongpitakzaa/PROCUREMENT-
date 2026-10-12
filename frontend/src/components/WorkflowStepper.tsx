/**
 * แสดงขั้นตอนของโครงการตามวิธีจัดหา (ลำดับมาจาก backend: workflow_steps)
 * ปุ่มของแต่ละขั้นตอนเปิดได้ตามลำดับเท่านั้น — UI สะท้อนกฎ แต่ backend เป็นผู้บังคับจริง
 */
import { exportDocument } from "../api";
import type { ProjectDetail } from "../types";

const STATUS_TH: Record<string, string> = {
  PENDING: "รอดำเนินการ", IN_PROGRESS: "กำลังดำเนินการ", SUBMITTED: "รออนุมัติ",
  APPROVED: "อนุมัติแล้ว", REJECTED: "ส่งกลับแก้ไข", SKIPPED: "ไม่ต้องดำเนินการ",
};

interface Props {
  project: ProjectDetail;
  activeStep: string | null;
  onSelect: (code: string) => void;
  onError: (message: string) => void;
}

export function WorkflowStepper({ project, activeStep, onSelect, onError }: Props) {
  const firstOpen = project.steps.findIndex((s) => !["APPROVED", "SKIPPED"].includes(s.status));
  return (
    <ol className="stepper">
      {project.steps.map((s, i) => {
        const reachable = firstOpen === -1 || i <= firstOpen;
        const canExport = s.has_document && ["SUBMITTED", "APPROVED"].includes(s.status);
        return (
          <li key={s.code} className={`step step-${s.status.toLowerCase()} ${activeStep === s.code ? "active" : ""}`}>
            <button type="button" disabled={!reachable} onClick={() => onSelect(s.code)}>
              <span className="no">{i + 1}</span> {s.name_th}
            </button>
            <span className="status">{STATUS_TH[s.status]}</span>
            {canExport && (
              <span className="exports">
                {(["docx", "pdf"] as const).map((f) => (
                  <button key={f} type="button" onClick={() => exportDocument(project.project_id, s.code, f)
                    .catch((e: Error) => onError(`สร้างเอกสารไม่สำเร็จ: ${e.message}`))}>
                    {f.toUpperCase()}
                  </button>
                ))}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
