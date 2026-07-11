"""Passwords, tokens, and encryption at rest.

The original backend stored passwords as plaintext in a source file:

    export const users: User[] = [
      { id: 1, username: 'admin', password: 'admin123', role: 'admin' },
    ];

and authenticated by base64-decoding the Authorization header directly (not
even `Basic <base64>`), comparing the plaintext, and re-sending the credentials
on every request. There was no login endpoint and no session.

Here: bcrypt for passwords, short-lived JWTs for sessions, and Fernet
(AES-128-CBC + HMAC) for the SSN at rest so a stolen database file is not a
stolen identity.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=8)

_DEV_SECRET = "dev-only-insecure-secret-do-not-ship"


def _secret() -> str:
    secret = os.environ.get("DEID_JWT_SECRET")
    if not secret:
        if os.environ.get("DEID_ENV") == "production":
            raise RuntimeError("DEID_JWT_SECRET must be set in production")
        return _DEV_SECRET
    return secret


def _fernet() -> Fernet:
    """Derive the field-encryption key.

    In production this must come from a KMS or secrets manager, not from an env
    var; the interface stays the same. The dev fallback is derived
    deterministically so a restart does not orphan every row in the database.
    """
    raw = os.environ.get("DEID_FIELD_KEY")
    if raw:
        return Fernet(raw.encode())
    if os.environ.get("DEID_ENV") == "production":
        raise RuntimeError("DEID_FIELD_KEY must be set in production")
    digest = hashlib.sha256(b"dev-only-field-key").digest()
    return Fernet(base64.urlsafe_b64encode(digest))


# ---------------------------------------------------------------- passwords
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# ------------------------------------------------------------------- tokens
def create_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "role": role,
         "iat": now, "exp": now + TOKEN_TTL},
        _secret(), algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# --------------------------------------------------------------- field crypto
def encrypt_field(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_field(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def mask_ssn(ssn: str) -> str:
    """Last four only. Never call this on ciphertext."""
    digits = "".join(c for c in ssn if c.isdigit())
    return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"
