/**
 * แสดงขั้นตอนของโครงการตามวิธีจัดหา (ลำดับมาจาก backend: workflow_steps)
 * ปุ่มของแต่ละขั้นตอนเปิดได้ตามลำดับเท่านั้น — UI สะท้อนกฎ แต่ backend เป็นผู้บังคับจริง
 */
import { useEffect, useState } from "react";
import { api, exportDocument, shareToLine } from "../api";
import type { LineTarget, ProjectDetail } from "../types";

const STATUS_TH: Record<string, string> = {
  PENDING: "รอดำเนินการ", IN_PROGRESS: "กำลังดำเนินการ", SUBMITTED: "รออนุมัติ",
  APPROVED: "อนุมัติแล้ว", REJECTED: "ส่งกลับแก้ไข", SKIPPED: "ไม่ต้องดำเนินการ",
};

interface Props {
  project: ProjectDetail;
  activeStep: string | null;
  canShareLine: boolean;
  onSelect: (code: string) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}

export function WorkflowStepper({ project, activeStep, canShareLine, onSelect, onError, onNotice }: Props) {
  const firstOpen = project.steps.findIndex((s) => !["APPROVED", "SKIPPED"].includes(s.status));
  const [targets, setTargets] = useState<LineTarget[]>([]);
  const [sending, setSending] = useState(false);
  useEffect(() => {
    if (canShareLine) api<LineTarget[]>("/api/line-channels").then(setTargets).catch(() => setTargets([]));
  }, [canShareLine]);

  // ส่งสถานะล่าสุดเข้ากลุ่ม: กลุ่มเดียวส่งทันที หลายกลุ่มให้เลือก (ส่งอัตโนมัติมีอยู่แล้วตอนส่งพิจารณา/อนุมัติ — ปุ่มนี้ไว้ส่งซ้ำ/แจ้งเพิ่ม)
  async function share(channelId: number) {
    setSending(true);
    try {
      await shareToLine(project.project_id, channelId);
      onNotice(`ส่ง LINE ไปยัง “${targets.find((t) => t.channel_id === channelId)?.name_th ?? "กลุ่ม"}” แล้ว`);
    } catch (e) {
      onError(`ส่ง LINE ไม่สำเร็จ: ${(e as Error).message}`);
    } finally {
      setSending(false);
    }
  }
  return (
    <>
    {canShareLine && targets.length > 0 && project.steps.length > 0 && (
      <div className="line-share">
        {targets.length === 1 ? (
          <button type="button" className="ghost" disabled={sending} onClick={() => share(targets[0]!.channel_id)}>
            💬 ส่งสถานะเข้า LINE
          </button>
        ) : (
          <label>
            💬 ส่งสถานะเข้า LINE
            <select disabled={sending} value="" onChange={(e) => e.target.value && share(Number(e.target.value))}>
              <option value="">เลือกกลุ่ม…</option>
              {targets.map((t) => <option key={t.channel_id} value={t.channel_id}>{t.name_th}</option>)}
            </select>
          </label>
        )}
      </div>
    )}
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
    </>
  );
}
