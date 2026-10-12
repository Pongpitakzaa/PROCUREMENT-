import { useEffect, useRef, useState } from "react";
import { ApiError, api, isLoggedIn, login, logout } from "./api";
import { ChangePasswordDialog } from "./components/ChangePasswordDialog";
import { AppStatusBar, InstallButton } from "./components/MobileApp";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ProjectCreatePage } from "./pages/ProjectCreatePage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { VendorsPage } from "./pages/VendorsPage";
import type { MethodInfo } from "./types";

interface Me { user_id: number; username: string; full_name_th: string; roles: string[]; permissions: string[] }

type View = { name: "list" } | { name: "create" } | { name: "detail"; projectId: number } | { name: "dashboard" } | { name: "vendors" } | { name: "admin" };

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
  const [changingPw, setChangingPw] = useState(false);
  const menuRef = useRef<HTMLDetailsElement>(null);
  const closeMenu = () => menuRef.current?.removeAttribute("open");

  // ปิดเมนูผู้ใช้เมื่อคลิกนอกเมนู หรือกด Esc
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeMenu();
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("click", onClick); document.removeEventListener("keydown", onKey); };
  }, []);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!authed) return;
    api<Me>("/api/auth/me").then(setMe).catch(() => setAuthed(false));
    api<MethodInfo[]>("/api/methods").then(setMethods).catch(() => setMethods([]));
  }, [authed]);

  if (!authed) {
    return (
      <>
      <AppStatusBar />
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
          <InstallButton className="ghost install-login" />
        </form>
      </div>
      </>
    );
  }

  const canCreate = me?.permissions.includes("project:write") ?? false;
  const canViewDashboard = me?.permissions.includes("dashboard:view") ?? false;
  const can = (perm: string) => me?.permissions.includes(perm) ?? false;
  const canAdmin = ["backup:run", "template:manage", "template:verify", "audit:read", "user:manage"].some(can);
  const toList = () => setView({ name: "list" });

  return (
    <>
      <AppStatusBar />
      <header className="app-header">
        <div className="brand">◆ e-Procurement <span>· ระบบจัดซื้อจัดจ้าง</span></div>
        <nav className="nav">
          <button type="button" className={view.name === "list" || view.name === "detail" ? "on" : ""} onClick={toList}>
            โครงการ
          </button>
          {canCreate && (
            <button type="button" className={view.name === "create" ? "on" : ""} onClick={() => setView({ name: "create" })}>
              สร้างโครงการ
            </button>
          )}
          <button type="button" className={view.name === "vendors" ? "on" : ""} onClick={() => setView({ name: "vendors" })}>
            ผู้ประกอบการ
          </button>
          {canViewDashboard && (
            <button type="button" className={view.name === "dashboard" ? "on" : ""} onClick={() => setView({ name: "dashboard" })}>
              Dashboard
            </button>
          )}
          {canAdmin && (
            <button type="button" className={view.name === "admin" ? "on" : ""} onClick={() => setView({ name: "admin" })}>
              ผู้ดูแลระบบ
            </button>
          )}
        </nav>
        {me && (
          <details className="user user-menu" ref={menuRef}>
            <summary>
              <span className="avatar" aria-hidden>{me.full_name_th.replace(/^(นาย|นางสาว|นาง)/, "").trim().charAt(0)}</span>
              <span className="who"><span>{me.full_name_th}</span><small>{me.roles.map((r) => ROLE_TH[r] ?? r).join(", ")}</small></span>
            </summary>
            <div className="menu card" role="menu">
              <div className="menu-head muted small">{me.full_name_th} · {me.username}</div>
              <button type="button" role="menuitem" onClick={() => { closeMenu(); setChangingPw(true); }}>เปลี่ยนรหัสผ่าน</button>
              <InstallButton role="menuitem" onBeforeOpen={closeMenu} />
              <button type="button" role="menuitem" onClick={() => { closeMenu(); logout(); setAuthed(false); setMe(null); }}>
                ออกจากระบบ
              </button>
            </div>
          </details>
        )}
      </header>

      {changingPw && me && (
        <ChangePasswordDialog username={me.username} onClose={(changed) => {
          setChangingPw(false);
          if (changed) setNotice("เปลี่ยนรหัสผ่านเรียบร้อยแล้ว");
        }} />
      )}
      <main className="app">
        {notice && <p role="status" className="banner-ok" onClick={() => setNotice(null)}>{notice}</p>}
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
        {view.name === "dashboard" && <DashboardPage />}
        {view.name === "admin" && me && <AdminPage permissions={me.permissions} userId={me.user_id} />}
        {view.name === "vendors" && (
          <VendorsPage canWrite={can("vendor:write")} canSanction={can("vendor:sanction")}
                       onOpenProject={(projectId) => setView({ name: "detail", projectId })} />
        )}
      </main>
    </>
  );
}
