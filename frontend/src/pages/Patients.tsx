import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type Patient } from "../api";
import { useAuth } from "../context/AuthContext";
import { Badge, Card, Spinner } from "../components/ui";

export default function Patients() {
  const { user } = useAuth();
  const [rows, setRows] = useState<Patient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revealing, setRevealing] = useState<Patient | null>(null);

  useEffect(() => {
    api.patients().then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!rows) return <Spinner label="Loading patients" />;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Patients</h1>
          <p className="page-sub">
            SSNs are encrypted at rest and masked everywhere. Revealing one is a
            deliberate, audited act — and only a clinician may do it.
          </p>
        </div>
        <Badge tone={user?.role === "admin" ? "warning" : "good"}>
          {user?.role === "admin"
            ? "admin — PHI reveal denied by policy"
            : "clinician — break-glass available"}
        </Badge>
      </header>

      <Card>
        <table className="data-table">
          <caption className="sr-only">Patient records</caption>
          <thead>
            <tr>
              <th scope="col">Name</th><th scope="col">DOB</th>
              <th scope="col">SSN</th><th scope="col">Symptoms</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <th scope="row">{p.full_name}</th>
                <td>{p.dob}</td>
                <td className="mono">{p.ssn}</td>
                <td className="truncate">{p.symptoms}</td>
                <td>
                  <button
                    className="btn ghost sm"
                    disabled={user?.role !== "clinician"}
                    title={user?.role !== "clinician"
                      ? "Admins do not have access to PHI"
                      : "Reveal the full SSN (audited)"}
                    onClick={() => setRevealing(p)}
                  >
                    Break glass
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <AnimatePresence>
        {revealing && (
          <RevealModal patient={revealing} onClose={() => setRevealing(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

function RevealModal({ patient, onClose }: { patient: Patient; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [ssn, setSsn] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.revealSsn(patient.id, reason);
      setSsn(res.ssn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reveal failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div className="modal-backdrop" onClick={onClose}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.div className="modal" onClick={(e) => e.stopPropagation()}
                  initial={{ scale: 0.95, y: 12 }} animate={{ scale: 1, y: 0 }}
                  exit={{ scale: 0.97, opacity: 0 }}>
        <h2>Break glass — {patient.full_name}</h2>
        <p className="muted">
          This writes an immutable record to the audit log naming you, the patient,
          the time, and the reason you type below.
        </p>

        {ssn ? (
          <>
            <div className="reveal">{ssn}</div>
            <p className="muted">Recorded. Close this dialog when you are done.</p>
            <button className="btn primary full" onClick={onClose}>Close</button>
          </>
        ) : (
          <form onSubmit={submit}>
            <label>
              <span>Reason (minimum 8 characters)</span>
              <textarea value={reason} rows={3} required minLength={8}
                        placeholder="Verifying identity for insurance claim submission"
                        onChange={(e) => setReason(e.target.value)} />
            </label>
            {error && <p className="error" role="alert">{error}</p>}
            <div className="row-end">
              <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
              <button className="btn danger" disabled={busy || reason.length < 8}>
                {busy ? "Recording…" : "Reveal SSN"}
              </button>
            </div>
          </form>
        )}
      </motion.div>
    </motion.div>
  );
}
