import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type EgressResponse, type RedactResponse, type Span } from "../api";
import { Badge, Card } from "../components/ui";

const SAMPLE = `ADMISSION NOTE
Facility: Presbyterian Medical Center, Hyderabad, MN
Patient: Soren Whitfield   MRN: 5686099
DOB: September 18, 2019   SSN: 218-34-1441

HISTORY OF PRESENT ILLNESS
The patient is a 38-year-old schoolteacher who presented with epigastric burning. Ms. Whitfield was last seen at Presbyterian Medical Center on 2017-12-14 by Dr. Thorne. Whitfield has not been compliant with her medication regimen. Reachable at (361) 889-6980 or soren.whitfield@example-health.org.`;

const CATEGORIES = [
  "NAME", "DATE", "ID", "CONTACT", "LOCATION", "AGE", "PROFESSION",
] as const;

/** Split text into alternating plain / PHI chunks so each span can animate in. */
function chunk(text: string, spans: Span[]) {
  const out: Array<{ text: string; span?: Span; key: string }> = [];
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  let cursor = 0;
  sorted.forEach((s, i) => {
    if (s.start > cursor) {
      out.push({ text: text.slice(cursor, s.start), key: `p${i}` });
    }
    // Overlapping spans would rewind the cursor and duplicate text; skip any
    // span that starts before we've caught up.
    if (s.start >= cursor) {
      out.push({ text: text.slice(s.start, s.end), span: s, key: `s${i}` });
      cursor = s.end;
    }
  });
  if (cursor < text.length) out.push({ text: text.slice(cursor), key: "tail" });
  return out;
}

export default function DeidStudio() {
  const [text, setText] = useState(SAMPLE);
  const [result, setResult] = useState<RedactResponse | null>(null);
  const [egress, setEgress] = useState<EgressResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendRaw, setSendRaw] = useState(false);
  const timer = useRef<number | null>(null);

  const run = useCallback(async (value: string) => {
    if (!value.trim()) { setResult(null); return; }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.redact(value));
      setEgress(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Redaction failed");
    } finally {
      setBusy(false);
    }
  }, []);

  // Debounce: the detector is sub-millisecond, but the round trip is not.
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => run(text), 350);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [text, run]);

  const attemptEgress = useCallback(async () => {
    if (!result) return;
    const payload = sendRaw ? text : result.redacted_text;
    try {
      setEgress(await api.egress(payload));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Egress failed");
    }
  }, [result, sendRaw, text]);

  const chunks = useMemo(
    () => (result ? chunk(text, result.spans) : []),
    [text, result],
  );

  const total = result ? result.spans.length : 0;

  return (
    <div className="studio">
      <header className="page-head">
        <div>
          <h1>De-identification Studio</h1>
          <p className="page-sub">
            The detector runs on this machine. Note text is never transmitted to
            an external service — the boundary below enforces it.
          </p>
        </div>
        <div className="legend" role="list" aria-label="PHI categories">
          {CATEGORIES.map((c) => (
            <span className="legend-item" role="listitem" key={c}>
              <span className="swatch" style={{ background: `var(--phi-${c})` }} aria-hidden />
              {c}
            </span>
          ))}
        </div>
      </header>

      <div className="studio-grid">
        {/* ------------------------------------------------------- input */}
        <Card
          title="Clinical note"
          subtitle="Edit freely. Detection re-runs as you type."
          actions={
            <button className="btn ghost" onClick={() => setText(SAMPLE)}>
              Reset sample
            </button>
          }
        >
          <textarea
            className="note-input"
            value={text}
            spellCheck={false}
            aria-label="Clinical note input"
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row-between">
            <span className="muted">{text.length.toLocaleString()} characters</span>
            {busy && <span className="muted">detecting…</span>}
          </div>
        </Card>

        {/* ------------------------------------------------- highlighted */}
        <Card
          title="Detected PHI"
          subtitle={
            result
              ? `${total} span${total === 1 ? "" : "s"} in ${result.latency_ms.toFixed(2)} ms`
              : "—"
          }
          actions={
            result && (
              <Badge tone={total > 0 ? "critical" : "good"}>
                {total > 0 ? "contains PHI" : "clean"}
              </Badge>
            )
          }
        >
          <div className="note-render" aria-live="polite">
            {chunks.map(({ text: t, span, key }) =>
              span ? (
                <motion.mark
                  key={key}
                  className="phi"
                  style={{ ["--hue" as string]: `var(--phi-${span.category})` }}
                  initial={{ backgroundColor: "transparent" }}
                  animate={{ backgroundColor: `color-mix(in srgb, var(--hue) 22%, transparent)` }}
                  transition={{ duration: 0.25 }}
                  title={span.category}
                >
                  {t}
                  <span className="phi-tag" aria-hidden>{span.category}</span>
                </motion.mark>
              ) : (
                <span key={key}>{t}</span>
              ),
            )}
          </div>
        </Card>

        {/* ---------------------------------------------------- redacted */}
        <Card title="Redacted output" subtitle="What is safe to transmit">
          <pre className="note-output">{result?.redacted_text ?? "—"}</pre>
          {result && (
            <div className="counts">
              {Object.entries(result.counts).map(([cat, n]) => (
                <span key={cat} className="count-chip">
                  <span className="swatch" style={{ background: `var(--phi-${cat})` }} aria-hidden />
                  {cat} <strong>{n}</strong>
                </span>
              ))}
              {total === 0 && <span className="muted">No PHI detected.</span>}
            </div>
          )}
        </Card>

        {/* ------------------------------------------------- the boundary */}
        <Card
          title="Trust boundary"
          subtitle="Nothing crosses until the local detector says it is clean"
        >
          <Boundary
            blocked={egress ? !egress.allowed : null}
            sendRaw={sendRaw}
            hasPhi={total > 0}
          />

          <div className="boundary-controls">
            <label className="toggle">
              <input
                type="checkbox"
                checked={sendRaw}
                onChange={(e) => { setSendRaw(e.target.checked); setEgress(null); }}
              />
              <span>Try to send the <strong>raw</strong> note (the unsafe thing)</span>
            </label>
            <button className="btn primary" onClick={attemptEgress} disabled={!result}>
              Transmit to claude-opus-4-8
            </button>
          </div>

          <AnimatePresence mode="wait">
            {egress && (
              <motion.div
                key={egress.allowed ? "ok" : "blocked"}
                className={`egress ${egress.allowed ? "ok" : "blocked"}`}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
              >
                <strong>{egress.allowed ? "✓ Transmitted" : "⚠ Blocked"}</strong>
                <span>
                  {egress.allowed
                    ? `${egress.chars_transmitted} redacted characters sent to ${egress.destination}. Recorded in the audit log.`
                    : egress.reason}
                </span>
              </motion.div>
            )}
          </AnimatePresence>

          {error && <p className="error">{error}</p>}
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- boundary animation */
function Boundary({
  blocked, sendRaw, hasPhi,
}: { blocked: boolean | null; sendRaw: boolean; hasPhi: boolean }) {
  const willBlock = sendRaw && hasPhi;
  return (
    <div className="boundary">
      <div className="zone local">
        <div className="zone-title">This machine</div>
        <div className="zone-body">
          <div className="chip">clinical note</div>
          <div className="chip">rule detector</div>
          <div className="chip">audit log</div>
        </div>
      </div>

      <div className="conduit" aria-hidden>
        <motion.div
          className={`packet ${willBlock ? "danger" : "safe"}`}
          key={`${sendRaw}-${hasPhi}-${blocked}`}
          initial={{ left: "2%", opacity: 0 }}
          animate={
            blocked === true || willBlock
              ? { left: ["2%", "44%", "38%"], opacity: [0, 1, 1] }
              : { left: ["2%", "92%"], opacity: [0, 1] }
          }
          transition={{ duration: 1.4, repeat: Infinity, repeatDelay: 0.5 }}
        />
        <motion.div
          className="shield"
          animate={
            willBlock
              ? { opacity: 1, scale: [1, 1.12, 1] }
              : { opacity: 0.28, scale: 1 }
          }
          transition={{ duration: 1.1, repeat: willBlock ? Infinity : 0 }}
        >
          <span aria-hidden>🛡</span>
        </motion.div>
      </div>

      <div className="zone cloud">
        <div className="zone-title">Hosted model</div>
        <div className="zone-body">
          <div className="chip muted-chip">redacted text only</div>
        </div>
      </div>
    </div>
  );
}
