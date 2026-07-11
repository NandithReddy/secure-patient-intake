"""FastAPI service.

The SSN disclosure policy
------------------------
The original project could not decide who sees a Social Security Number. Its
README said clinicians; its code (`routes/patients.ts:56`) gave it to admins
and masked it for clinicians; its frontend (`Dashboard.tsx:238`) did the
reverse of the backend, so in practice nobody ever saw one and the clinician
edit form was unusable.

That was not a bug so much as an absent policy. Here is a policy, built on
separation of duties and HIPAA's "minimum necessary" principle:

  admin      Operates the system. Manages users, reads the audit log,
             verifies the hash chain. Never sees PHI. Not a clinician.
  clinician  Treats patients. Sees masked SSNs by default. May "break glass"
             to reveal one, must state a reason, and every reveal is written
             to the audit log.

Nobody sees a full SSN as a side effect of listing patients. The SSN is
encrypted at rest, so the database file alone discloses nothing.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from deid.audit import AuditLog
from deid.config import O_LOGIT_PENALTY
from deid.guard import EgressGuard, PhiLeakBlocked
from deid.redactors.rules import RuleRedactor
from deid.types import apply_redaction

from . import db, security

AUDIT_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

audit = AuditLog(AUDIT_PATH)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "deid-roberta"


def _build_detector():
    """Prefer the trained local model; fall back to rules.

    Both run entirely in this process — EgressGuard rejects any detector whose
    `transmits_offsite` is True, so the LLM redactor can never end up here by
    accident. The fallback is loud rather than silent: a service quietly serving
    a 20.81% leak rate because a checkpoint was missing is worse than one that
    refuses to start.
    """
    if MODEL_DIR.exists():
        try:
            from deid.redactors.transformer import TransformerRedactor
            return TransformerRedactor(MODEL_DIR, o_logit_penalty=O_LOGIT_PENALTY)
        except ImportError:
            print(f"WARNING: {MODEL_DIR} exists but torch is not installed "
                  f"(pip install -e '.[ml]'). Falling back to the rule baseline, "
                  f"which leaks 20.81% of PHI on the benchmark.")
    else:
        print(f"WARNING: no checkpoint at {MODEL_DIR}. Serving the rule baseline, "
              f"which leaks 20.81% of PHI. Train one: python -m deid.train "
              f"--out models/deid-roberta --n-synth 200 --epochs 6")
    return RuleRedactor()


detector = _build_detector()
guard = EgressGuard(detector, audit)

app = FastAPI(
    title="Secure Patient Intake",
    description="PHI de-identification with a measured trust boundary.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ schemas
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class PatientIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    dob: str = Field(min_length=1, max_length=32)
    ssn: str
    symptoms: str = ""
    clinical_notes: str = ""

    @field_validator("ssn")
    @classmethod
    def ssn_must_be_nine_digits(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 9:
            # The original had this check only in the React form, so any direct
            # API call could overwrite a stored SSN with the string "***-**-1441".
            raise ValueError("SSN must contain exactly 9 digits")
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


class PatientOut(BaseModel):
    id: str
    full_name: str
    dob: str
    ssn: str  # always masked; see /patients/{id}/ssn to reveal
    symptoms: str
    clinical_notes: str
    created_by: int


class RevealRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


class RedactRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class SpanOut(BaseModel):
    start: int
    end: int
    category: str
    text: str


class RedactResponse(BaseModel):
    redacted_text: str
    spans: list[SpanOut]
    counts: dict[str, int]
    latency_ms: float
    safe_to_transmit: bool


class EgressRequest(BaseModel):
    text: str
    destination: str = "anthropic:claude-opus-4-8"


class User(BaseModel):
    id: int
    username: str
    role: Literal["admin", "clinician"]


# --------------------------------------------------------------- dependencies
def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = security.decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return User(id=int(payload["sub"]), username=payload["username"],
                role=payload["role"])


def require_role(*roles: str):
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role {user.role!r} may not perform this action",
            )
        return user
    return dep


CurrentUser = Annotated[User, Depends(current_user)]
Clinician = Annotated[User, Depends(require_role("clinician"))]
Admin = Annotated[User, Depends(require_role("admin"))]


# ---------------------------------------------------------------- lifecycle
@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE role='clinician' LIMIT 1"
        ).fetchone()
    if row:
        db.seed_demo_patients(row["id"])


# --------------------------------------------------------------------- auth
@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request) -> TokenResponse:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (body.username,)
        ).fetchone()

    # Hash even on a missing user so response time does not reveal which
    # usernames exist.
    stored = row["password_hash"] if row else security.hash_password("dummy")
    if not security.verify_password(body.password, stored) or row is None:
        audit.record("LOGIN_FAILED", username=body.username,
                     ip=request.client.host if request.client else None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    audit.record("LOGIN", actor_id=row["id"], actor_role=row["role"])
    return TokenResponse(
        access_token=security.create_token(row["id"], row["username"], row["role"]),
        role=row["role"], username=row["username"],
    )


@app.get("/api/auth/me", response_model=User)
def me(user: CurrentUser) -> User:
    return user


# ----------------------------------------------------------------- patients
def _to_out(row) -> PatientOut:
    return PatientOut(
        id=row["id"], full_name=row["full_name"], dob=row["dob"],
        ssn=f"***-**-{row['ssn_last4']}",
        symptoms=row["symptoms"], clinical_notes=row["clinical_notes"],
        created_by=row["created_by"],
    )


@app.get("/api/patients", response_model=list[PatientOut])
def list_patients(user: CurrentUser) -> list[PatientOut]:
    """Both roles list patients. Neither sees an SSN here."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM patients ORDER BY created_at DESC"
        ).fetchall()
    audit.record("VIEW_PATIENTS", actor_id=user.id, actor_role=user.role,
                 count=len(rows))
    return [_to_out(r) for r in rows]


@app.post("/api/patients", response_model=PatientOut,
          status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientIn, user: Clinician) -> PatientOut:
    pid = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO patients (id, created_by, full_name, dob, "
            "ssn_encrypted, ssn_last4, symptoms, clinical_notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, user.id, body.full_name, body.dob,
             security.encrypt_field(body.ssn), body.ssn[-4:],
             body.symptoms, body.clinical_notes),
        )
        row = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    audit.record("CREATE_PATIENT", actor_id=user.id, actor_role=user.role,
                 patient_id=pid)
    return _to_out(row)


@app.put("/api/patients/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: str, body: PatientIn, user: Clinician) -> PatientOut:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
        if row["created_by"] != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your patient")
        conn.execute(
            "UPDATE patients SET full_name=?, dob=?, ssn_encrypted=?, "
            "ssn_last4=?, symptoms=?, clinical_notes=? WHERE id=?",
            (body.full_name, body.dob, security.encrypt_field(body.ssn),
             body.ssn[-4:], body.symptoms, body.clinical_notes, patient_id),
        )
        row = conn.execute(
            "SELECT * FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
    audit.record("EDIT_PATIENT", actor_id=user.id, actor_role=user.role,
                 patient_id=patient_id)
    return _to_out(row)


@app.delete("/api/patients/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient(patient_id: str, user: Clinician) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT created_by FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
        if row["created_by"] != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your patient")
        conn.execute("DELETE FROM patients WHERE id=?", (patient_id,))
    audit.record("DELETE_PATIENT", actor_id=user.id, actor_role=user.role,
                 patient_id=patient_id)


@app.post("/api/patients/{patient_id}/ssn")
def reveal_ssn(patient_id: str, body: RevealRequest, user: Clinician) -> dict:
    """Break-glass. Clinicians only, reason required, always audited.

    An admin calling this gets a 403. Managing the system does not entitle you
    to a patient's Social Security Number.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ssn_encrypted FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")

    audit.record("REVEAL_SSN", actor_id=user.id, actor_role=user.role,
                 patient_id=patient_id, reason=body.reason)
    return {"ssn": security.decrypt_field(row["ssn_encrypted"]),
            "audited": True, "reason": body.reason}


# ---------------------------------------------------------------- de-id core
@app.post("/api/deid/redact", response_model=RedactResponse)
def redact(body: RedactRequest, user: CurrentUser) -> RedactResponse:
    """Run the local detector. Note text never leaves this process."""
    t0 = time.perf_counter()
    spans = detector.find(body.text)
    elapsed = (time.perf_counter() - t0) * 1000.0

    counts: dict[str, int] = {}
    for s in spans:
        counts[s.category.value] = counts.get(s.category.value, 0) + 1

    redacted = apply_redaction(body.text, spans)
    audit.record("REDACT", actor_id=user.id, actor_role=user.role,
                 chars=len(body.text), redactions=counts)

    return RedactResponse(
        redacted_text=redacted,
        spans=[SpanOut(start=s.start, end=s.end, category=s.category.value,
                       text=s.text) for s in spans],
        counts=counts,
        latency_ms=round(elapsed, 3),
        # Re-inspect the *output*: if the detector still finds PHI in its own
        # redaction, something is very wrong and the guard would block it.
        safe_to_transmit=not detector.find(redacted),
    )


@app.post("/api/deid/egress")
def attempt_egress(body: EgressRequest, user: CurrentUser) -> dict:
    """Ask the guard to transmit. Demonstrates the boundary refusing raw PHI."""
    try:
        guard.send(
            body.text, destination=body.destination,
            fn=lambda safe: safe, actor_id=user.id, actor_role=user.role,
        )
    except PhiLeakBlocked as e:
        return {
            "allowed": False,
            "destination": body.destination,
            "reason": str(e),
            "residual": [
                {"start": s.start, "end": s.end, "category": s.category.value}
                for s in e.spans
            ],
        }
    return {"allowed": True, "destination": body.destination,
            "chars_transmitted": len(body.text)}


# -------------------------------------------------------------------- audit
@app.get("/api/audit")
def read_audit(user: Admin, limit: int = 200) -> dict:
    """Admins read the log. Clinicians do not audit themselves."""
    entries = list(audit.read())
    verification = audit.verify()
    return {
        "entries": entries[-limit:][::-1],
        "total": len(entries),
        "chain_valid": verification.ok,
        "broken_at": verification.broken_at,
        "reason": verification.reason,
    }


# ---------------------------------------------------------------- benchmark
@app.get("/api/benchmark")
def benchmark() -> dict:
    """Serve whatever eval reports have been generated into results/."""
    import json
    reports = []
    if RESULTS_DIR.is_dir():
        for path in sorted(RESULTS_DIR.glob("*.json")):
            try:
                reports.append(json.loads(path.read_text()))
            except json.JSONDecodeError:
                continue
    return {"reports": reports}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "detector": detector.name,
            "detector_is_local": not detector.transmits_offsite}
