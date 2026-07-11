import { motion } from "framer-motion";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("clinician");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      nav("/studio");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <motion.form
        className="login-card"
        onSubmit={submit}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0.7, 0.3, 1] }}
      >
        <div className="brand">
          <span className="brand-mark" aria-hidden>🛡</span>
          <div>
            <h1>Secure Patient Intake</h1>
            <p>PHI de-identification with a measured trust boundary</p>
          </div>
        </div>

        <label>
          <span>Username</span>
          <input value={username} autoComplete="username"
                 onChange={(e) => setUsername(e.target.value)} required />
        </label>

        <label>
          <span>Password</span>
          <input type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>

        {error && <p className="error" role="alert">{error}</p>}

        <button className="btn primary full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <div className="demo-creds">
          <p className="muted">Demo accounts — passwords are bcrypt-hashed server-side.</p>
          <div className="demo-buttons">
            <button type="button" className="btn ghost sm"
                    onClick={() => { setUsername("clinician"); setPassword("clinician123"); }}>
              clinician — treats patients, may break-glass
            </button>
            <button type="button" className="btn ghost sm"
                    onClick={() => { setUsername("admin"); setPassword("admin123"); }}>
              admin — operates the system, never sees PHI
            </button>
          </div>
        </div>
      </motion.form>
    </div>
  );
}
