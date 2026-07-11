// Empty by default: requests go to the same origin and Vite's dev proxy
// forwards /api/* to the FastAPI service. Set VITE_API_URL for a production
// build that talks to a different host.
const BASE = import.meta.env.VITE_API_URL ?? "";

export type Role = "admin" | "clinician";

export interface Span {
  start: number;
  end: number;
  category: string;
  text: string;
}

export interface RedactResponse {
  redacted_text: string;
  spans: Span[];
  counts: Record<string, number>;
  latency_ms: number;
  safe_to_transmit: boolean;
}

export interface EgressResponse {
  allowed: boolean;
  destination: string;
  reason?: string;
  residual?: Array<{ start: number; end: number; category: string }>;
  chars_transmitted?: number;
}

export interface Patient {
  id: string;
  full_name: string;
  dob: string;
  ssn: string;
  symptoms: string;
  clinical_notes: string;
  created_by: number;
}

export interface PRF {
  tp: number; fp: number; fn: number;
  precision: number; recall: number; f1: number; f2: number;
}

export interface BenchReport {
  redactor: string;
  notes: number;
  leak_rate: number;
  char_recall: number;
  gold_spans: number;
  fully_missed_spans: number;
  missed_by_category: Record<string, number>;
  hallucinated_spans: number;
  strict: PRF;
  partial: PRF;
  per_category: Record<string, PRF>;
  mean_latency_ms: number;
  total_cost_usd: number;
}

export interface AuditEntry {
  ts: string;
  action: string;
  actor_id: number | null;
  actor_role: string | null;
  prev: string;
  [k: string]: unknown;
}

const TOKEN_KEY = "spi.token";

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property —
  // the tsconfig sets `erasableSyntaxOnly`, which forbids that shorthand.
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const t = token.get();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(t ? { authorization: `Bearer ${t}` } : {}),
      ...init.headers,
    },
  });

  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
          : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; role: Role; username: string }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),

  me: () => request<{ id: number; username: string; role: Role }>("/api/auth/me"),

  patients: () => request<Patient[]>("/api/patients"),

  revealSsn: (id: string, reason: string) =>
    request<{ ssn: string; audited: boolean }>(`/api/patients/${id}/ssn`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  redact: (text: string) =>
    request<RedactResponse>("/api/deid/redact", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  egress: (text: string, destination = "anthropic:claude-opus-4-8") =>
    request<EgressResponse>("/api/deid/egress", {
      method: "POST",
      body: JSON.stringify({ text, destination }),
    }),

  benchmark: () => request<{ reports: BenchReport[] }>("/api/benchmark"),

  audit: (limit = 200) =>
    request<{
      entries: AuditEntry[];
      total: number;
      chain_valid: boolean;
      broken_at: number | null;
      reason: string | null;
    }>(`/api/audit?limit=${limit}`),

  health: () =>
    request<{ status: string; detector: string; detector_is_local: boolean }>(
      "/api/health",
    ),
};
