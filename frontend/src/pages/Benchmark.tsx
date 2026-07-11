import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type BenchReport } from "../api";
import { Badge, Card, Hero, Spinner, StatTile } from "../components/ui";

/** Recall below this is treated as a leaking category. Chosen because a
 *  de-identification system is not deployable when one PHI class in ten walks
 *  out the door. */
const RECALL_FLOOR = 0.9;

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export default function Benchmark() {
  const [reports, setReports] = useState<BenchReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    api.benchmark()
      .then((r) => setReports(r.reports))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  const primary = reports?.[0];

  const perCategory = useMemo(() => {
    if (!primary) return [];
    return Object.entries(primary.per_category)
      .map(([category, prf]) => ({
        category,
        recall: prf.recall,
        precision: prf.precision,
        f2: prf.f2,
        missed: primary.missed_by_category[category] ?? 0,
        leaking: prf.recall < RECALL_FLOOR,
      }))
      .sort((a, b) => a.recall - b.recall);
  }, [primary]);

  const comparison = useMemo(() => {
    if (!reports?.length) return [];
    const cats = new Set<string>();
    reports.forEach((r) => Object.keys(r.per_category).forEach((c) => cats.add(c)));
    return [...cats].sort().map((category) => {
      const row: Record<string, string | number> = { category };
      reports.forEach((r) => { row[r.redactor] = r.per_category[category]?.recall ?? 0; });
      return row;
    });
  }, [reports]);

  if (error) return <p className="error">{error}</p>;
  if (!reports) return <Spinner label="Loading benchmark" />;

  if (!reports.length) {
    return (
      <Card title="No benchmark results yet">
        <p className="muted">
          Generate one:
          <code className="inline-code">
            python -m deid.cli eval --redactor rules --json-out results/rules.json
          </code>
        </p>
      </Card>
    );
  }

  const leaking = perCategory.filter((c) => c.leaking);

  return (
    <div className="bench">
      <header className="page-head">
        <div>
          <h1>Benchmark</h1>
          <p className="page-sub">
            Scored against gold spans. The headline is the leak rate — the share of
            PHI <em>characters</em> left exposed — because a missed name is a
            disclosure and an over-redacted word is an inconvenience.
          </p>
        </div>
        <Badge tone="warning">synthetic corpus — upper bound</Badge>
      </header>

      {/* One number, so a hero figure, not a one-bar chart. */}
      <div className="hero-row">
        <Hero
          value={primary!.leak_rate * 100}
          label="Leak rate"
          sub={`${primary!.fully_missed_spans} of ${primary!.gold_spans} gold spans never detected · ${primary!.redactor}`}
          tone={primary!.leak_rate > 0.05 ? "critical" : "good"}
        />
        <div className="kpi-row">
          <StatTile label="Character recall" value={primary!.char_recall * 100}
                    decimals={2} suffix="%" hint="PHI characters covered" />
          <StatTile label="Precision (partial)" value={primary!.partial.precision}
                    decimals={3} hint="of what it flagged, how much was PHI" />
          <StatTile label="F2 (recall-weighted)" value={primary!.partial.f2}
                    decimals={3} hint="the deployment score" />
          <StatTile label="Latency" value={primary!.mean_latency_ms}
                    decimals={2} suffix=" ms" hint="per note" />
        </div>
      </div>

      {leaking.length > 0 && (
        <div className="callout critical-callout">
          <strong>⚠ {leaking.length} categories are leaking.</strong>
          <span>
            {leaking.map((c) => c.category).join(", ")} fall below{" "}
            {(RECALL_FLOOR * 100).toFixed(0)}% recall. Every one is a class of
            identifier this redactor cannot see.
          </span>
        </div>
      )}

      {/* Emphasis form: the leaking categories are the story; the rest are context. */}
      <Card
        title="Recall by PHI category"
        subtitle={`${primary!.redactor} · leaking categories highlighted`}
        actions={
          <button className="btn ghost" onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Show chart" : "Show table"}
          </button>
        }
      >
        {showTable ? (
          <table className="data-table">
            <caption className="sr-only">Recall, precision and F2 by PHI category</caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">Recall</th>
                <th scope="col">Precision</th>
                <th scope="col">F2</th>
                <th scope="col">Spans missed</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {perCategory.map((r) => (
                <tr key={r.category}>
                  <th scope="row">{r.category}</th>
                  <td>{r.recall.toFixed(3)}</td>
                  <td>{r.precision.toFixed(3)}</td>
                  <td>{r.f2.toFixed(3)}</td>
                  <td>{r.missed}</td>
                  <td>{r.leaking ? <Badge tone="critical">leaking</Badge> : <Badge tone="good">ok</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(240, perCategory.length * 46)}>
            <BarChart data={perCategory} layout="vertical"
                      margin={{ top: 8, right: 64, bottom: 8, left: 8 }}>
              <CartesianGrid horizontal={false} stroke="var(--grid)" />
              <XAxis type="number" domain={[0, 1]} tickCount={6}
                     tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                     stroke="var(--border)" />
              <YAxis type="category" dataKey="category" width={104}
                     tick={{ fill: "var(--text-secondary)", fontSize: 12 }}
                     stroke="var(--border)" />
              <Tooltip
                cursor={{ fill: "var(--surface-sunken)" }}
                contentStyle={{
                  background: "var(--surface-2)", border: "1px solid var(--border)",
                  borderRadius: 8, color: "var(--text-primary)",
                }}
                formatter={(v: number, _n, p) => [
                  `${(v * 100).toFixed(1)}% recall · ${p.payload.missed} spans missed`,
                  p.payload.category,
                ]}
              />
              <ReferenceLine x={RECALL_FLOOR} stroke="var(--text-muted)"
                             strokeDasharray="4 4"
                             label={{ value: "floor", position: "top",
                                      fill: "var(--text-muted)", fontSize: 11 }} />
              <Bar dataKey="recall" radius={[0, 4, 4, 0]} barSize={18} isAnimationActive>
                {perCategory.map((d) => (
                  <Cell key={d.category}
                        fill={d.leaking ? "var(--critical)" : "var(--recessive)"} />
                ))}
                {/* Direct labels: mandatory relief for the sub-3:1 contrast WARN. */}
                <LabelList dataKey="recall" position="right"
                           formatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                           style={{ fill: "var(--text-secondary)", fontSize: 12 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      {reports.length > 1 && (
        <Card title="Redactor comparison"
              subtitle="Recall by category, same test set, same gold spans">
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={comparison} margin={{ top: 20, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="category" tick={{ fill: "var(--text-secondary)", fontSize: 12 }}
                     stroke="var(--border)" />
              <YAxis domain={[0, 1]} tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                     stroke="var(--border)" />
              <Tooltip
                cursor={{ fill: "var(--surface-sunken)" }}
                contentStyle={{
                  background: "var(--surface-2)", border: "1px solid var(--border)",
                  borderRadius: 8, color: "var(--text-primary)",
                }}
                formatter={(v: number) => `${(v * 100).toFixed(1)}%`}
              />
              <Legend wrapperStyle={{ color: "var(--text-secondary)", fontSize: 12 }} />
              {reports.map((r, i) => (
                <Bar key={r.redactor} dataKey={r.redactor} fill={SERIES[i % SERIES.length]}
                     radius={[4, 4, 0, 0]} barSize={16}>
                  <LabelList dataKey={r.redactor} position="top"
                             formatter={(v: number) => (v > 0 ? `${(v * 100).toFixed(0)}` : "")}
                             style={{ fill: "var(--text-muted)", fontSize: 10 }} />
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>

          <table className="data-table compact">
            <caption>Cost, latency, and hallucinated spans per redactor</caption>
            <thead>
              <tr>
                <th scope="col">Redactor</th><th scope="col">Leak rate</th>
                <th scope="col">F2</th><th scope="col">Latency</th>
                <th scope="col">Cost</th><th scope="col">Hallucinated</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.redactor}>
                  <th scope="row">{r.redactor}</th>
                  <td>{(r.leak_rate * 100).toFixed(2)}%</td>
                  <td>{r.partial.f2.toFixed(3)}</td>
                  <td>{r.mean_latency_ms.toFixed(1)} ms</td>
                  <td>{r.total_cost_usd ? `$${r.total_cost_usd.toFixed(4)}` : "—"}</td>
                  <td>{r.hallucinated_spans || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
