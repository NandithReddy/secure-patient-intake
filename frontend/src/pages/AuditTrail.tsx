import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type AuditEntry } from "../api";
import { Badge, Card, Spinner, StatTile } from "../components/ui";

const ACTION_TONE: Record<string, "good" | "warning" | "critical" | "neutral"> = {
  LOGIN: "neutral",
  LOGIN_FAILED: "warning",
  REVEAL_SSN: "critical",
  EGRESS: "good",
  EGRESS_BLOCKED: "critical",
  DELETE_PATIENT: "warning",
};

export default function AuditTrail() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.audit>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.audit().then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <Spinner label="Loading audit log" />;

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Audit trail</h1>
          <p className="page-sub">
            Every entry carries the SHA-256 of the one before it. Alter or delete
            any record and the chain breaks at that point — permanently.
          </p>
        </div>
        <Badge tone={data.chain_valid ? "good" : "critical"}>
          {data.chain_valid ? "hash chain intact" : `chain broken at entry ${data.broken_at}`}
        </Badge>
      </header>

      <div className="kpi-row">
        <StatTile label="Total entries" value={data.total} />
        <StatTile
          label="Chain integrity"
          value={data.chain_valid ? 100 : 0}
          suffix="%"
          tone={data.chain_valid ? "good" : "critical"}
          hint={data.chain_valid ? "verified" : data.reason ?? "tampered"}
        />
        <StatTile
          label="SSN reveals"
          value={data.entries.filter((e) => e.action === "REVEAL_SSN").length}
          tone="warning"
          hint="each required a stated reason"
        />
        <StatTile
          label="Egress blocked"
          value={data.entries.filter((e) => e.action === "EGRESS_BLOCKED").length}
          tone="critical"
          hint="PHI stopped at the boundary"
        />
      </div>

      <Card title="Recent activity" subtitle="Newest first">
        <div className="audit-list">
          {data.entries.map((e, i) => (
            <Entry key={`${e.prev}-${i}`} entry={e} index={i} />
          ))}
        </div>
      </Card>
    </div>
  );
}

function Entry({ entry, index }: { entry: AuditEntry; index: number }) {
  const tone = ACTION_TONE[entry.action] ?? "neutral";
  const extra = Object.entries(entry).filter(
    ([k]) => !["ts", "action", "actor_id", "actor_role", "prev"].includes(k),
  );

  return (
    <motion.div
      className="audit-row"
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: Math.min(index * 0.015, 0.3) }}
    >
      <time className="mono muted">{entry.ts.slice(0, 19).replace("T", " ")}</time>
      <Badge tone={tone}>{entry.action}</Badge>
      <span className="actor">
        {entry.actor_role ? `${entry.actor_role} #${entry.actor_id}` : "—"}
      </span>
      <span className="audit-extra mono">
        {extra.map(([k, v]) => (
          <span key={k} className="kv">
            {k}=<strong>{typeof v === "object" ? JSON.stringify(v) : String(v)}</strong>
          </span>
        ))}
      </span>
      <span className="chain mono" title={`prev: ${entry.prev}`}>
        {entry.prev.slice(0, 8)}
      </span>
    </motion.div>
  );
}
