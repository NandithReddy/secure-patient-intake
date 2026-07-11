import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useEffect } from "react";

/* ------------------------------------------------------------------ Counter */
/** Animated number. Respects prefers-reduced-motion via the spring's stiffness
 *  being irrelevant when the CSS media query kills transitions — but we also
 *  short-circuit for correctness in tests. */
export function Counter({
  value, decimals = 0, suffix = "",
}: { value: number; decimals?: number; suffix?: string }) {
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 90, damping: 20 });
  const text = useTransform(spring, (v) => v.toFixed(decimals) + suffix);
  useEffect(() => { mv.set(value); }, [mv, value]);
  return <motion.span>{text}</motion.span>;
}

/* ---------------------------------------------------------------- Stat tile */
export type Tone = "neutral" | "good" | "warning" | "critical";

const TONE_VAR: Record<Tone, string> = {
  neutral: "var(--text-primary)",
  good: "var(--good)",
  warning: "var(--warning)",
  critical: "var(--critical)",
};

const TONE_ICON: Record<Tone, string> = {
  neutral: "", good: "✓", warning: "▲", critical: "⚠",
};

export function StatTile({
  label, value, decimals = 0, suffix = "", tone = "neutral", hint,
}: {
  label: string; value: number; decimals?: number; suffix?: string;
  tone?: Tone; hint?: string;
}) {
  return (
    <motion.div
      className="tile"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="tile-label">{label}</div>
      <div className="tile-value" style={{ color: TONE_VAR[tone] }}>
        {/* Status colour never carries meaning alone — icon + label accompany it. */}
        {tone !== "neutral" && (
          <span className="tile-icon" aria-hidden>{TONE_ICON[tone]}</span>
        )}
        <Counter value={value} decimals={decimals} suffix={suffix} />
      </div>
      {hint && <div className="tile-hint">{hint}</div>}
    </motion.div>
  );
}

/* -------------------------------------------------------------- Hero figure */
export function Hero({
  value, label, sub, tone = "critical",
}: { value: number; label: string; sub: string; tone?: Tone }) {
  return (
    <motion.div
      className="hero"
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.2, 0.7, 0.3, 1] }}
    >
      <div className="hero-label">{label}</div>
      <div className="hero-value" style={{ color: TONE_VAR[tone] }}>
        <Counter value={value} decimals={2} suffix="%" />
      </div>
      <div className="hero-sub">{sub}</div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------- Shared */
export function Card({
  title, subtitle, children, actions,
}: {
  title?: string; subtitle?: string;
  children: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className={`badge badge-${tone}`}>
      {tone !== "neutral" && <span aria-hidden>{TONE_ICON[tone]}</span>}
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status" aria-live="polite">
      <motion.div
        className="spinner"
        animate={{ rotate: 360 }}
        transition={{ repeat: Infinity, duration: 0.9, ease: "linear" }}
      />
      <span className="sr-only">{label}</span>
    </div>
  );
}
