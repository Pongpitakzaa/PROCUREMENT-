import { useEffect, useState } from "react";
import { ApiError, api, isLoggedIn, login, logout } from "./api";
import { ProjectCreatePage } from "./pages/ProjectCreatePage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import type { MethodInfo } from "./types";

interface Me { full_name_th: string; roles: string[]; permissions: string[] }

type View = { name: "list" } | { name: "create" } | { name: "detail"; projectId: number };

const ROLE_TH: Record<string, string> = {
  ADMIN: "ผู้ดูแลระบบ", PROCUREMENT_OFFICER: "เจ้าหน้าที่พัสดุ", HEAD_OF_PROCUREMENT: "หัวหน้าเจ้าหน้าที่",
  EXECUTIVE: "ผู้บริหาร", AUDITOR: "ผู้ตรวจสอบ",
};

export function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [me, setMe] = useState<Me | null>(null);
  const [methods, setMethods] = useState<MethodInfo[]>([]);
  const [view, setView] = useState<View>({ name: "list" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authed) return;
    api<Me>("/api/auth/me").then(setMe).catch(() => setAuthed(false));
    api<MethodInfo[]>("/api/methods").then(setMethods).catch(() => setMethods([]));
  }, [authed]);

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
              setView({ name: "list" });
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

  const canCreate = me?.permissions.includes("project:write") ?? false;
  const toList = () => setView({ name: "list" });

  return (
    <>
      <header className="app-header">
        <div className="brand">◆ e-Procurement <span>· ระบบจัดซื้อจัดจ้าง</span></div>
        <nav className="nav">
          <button type="button" className={view.name !== "create" ? "on" : ""} onClick={toList}>โครงการ</button>
          {canCreate && (
            <button type="button" className={view.name === "create" ? "on" : ""} onClick={() => setView({ name: "create" })}>
              สร้างโครงการ
            </button>
          )}
        </nav>
        {me && (
          <div className="user">
            <span>{me.full_name_th}</span>
            <small>{me.roles.map((r) => ROLE_TH[r] ?? r).join(", ")}</small>
            <button type="button" className="ghost" onClick={() => { logout(); setAuthed(false); setMe(null); }}>
              ออกจากระบบ
            </button>
          </div>
        )}
      </header>

      <main className="app">
        {view.name === "list" && (
          <ProjectListPage methods={methods} canCreate={canCreate}
                           onOpen={(projectId) => setView({ name: "detail", projectId })}
                           onCreate={() => setView({ name: "create" })} />
        )}
        {view.name === "create" && (
          <ProjectCreatePage methods={methods} onCancel={toList}
                             onCreated={(projectId) => setView({ name: "detail", projectId })} />
        )}
        {view.name === "detail" && <ProjectDetailPage projectId={view.projectId} onBack={toList} />}
      </main>
    </>
  );
}
