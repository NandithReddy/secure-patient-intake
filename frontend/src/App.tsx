import { useEffect, useState } from "react";
import {
  BrowserRouter, Navigate, NavLink, Outlet, Route, Routes,
} from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Spinner } from "./components/ui";
import AuditTrail from "./pages/AuditTrail";
import Benchmark from "./pages/Benchmark";
import DeidStudio from "./pages/DeidStudio";
import LoginPage from "./pages/LoginPage";
import Patients from "./pages/Patients";
import "./theme.css";
import "./App.css";

type Theme = "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(
    () =>
      (localStorage.getItem("spi.theme") as Theme) ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("spi.theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

function Shell() {
  const { user, logout } = useAuth();
  const [theme, toggle] = useTheme();

  return (
    <div className="shell">
      <nav className="nav">
        <div className="nav-brand">
          <span aria-hidden>🛡</span>
          <span>Secure Patient Intake</span>
        </div>

        <div className="nav-links">
          <NavLink to="/studio">Studio</NavLink>
          <NavLink to="/benchmark">Benchmark</NavLink>
          <NavLink to="/patients">Patients</NavLink>
          {user?.role === "admin" && <NavLink to="/audit">Audit</NavLink>}
        </div>

        <div className="nav-right">
          <button className="btn ghost sm" onClick={toggle}
                  aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <span className="who">
            {user?.username} <span className="muted">· {user?.role}</span>
          </span>
          <button className="btn ghost sm" onClick={logout}>Sign out</button>
        </div>
      </nav>

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

/** Gate that waits for the session probe before deciding. Redirecting while
 *  `loading` is true bounces an authenticated user to /login on every refresh. */
function Protected({ role }: { role?: "admin" | "clinician" }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner label="Restoring session" />;
  if (!user) return <Navigate to="/login" replace />;
  if (role && user.role !== role) return <Navigate to="/studio" replace />;
  return <Shell />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Protected />}>
            <Route path="/studio" element={<DeidStudio />} />
            <Route path="/benchmark" element={<Benchmark />} />
            <Route path="/patients" element={<Patients />} />
          </Route>
          <Route element={<Protected role="admin" />}>
            <Route path="/audit" element={<AuditTrail />} />
          </Route>
          <Route path="*" element={<Navigate to="/studio" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
