"""Authentication routes: register, login, refresh, password reset."""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from webapp.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from webapp.config import RESET_TOKEN_EXPIRE_MINUTES
from webapp.dependencies import get_current_user, get_db
from webapp.models import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordConfirm,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: sqlite3.Connection = Depends(get_db)):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not req.display_name.strip():
        raise HTTPException(status_code=400, detail="Display name is required")
    existing = db.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    pw_hash = hash_password(req.password)
    cursor = db.execute(
        "INSERT INTO users (email, display_name, password_hash) VALUES (?, ?, ?)",
        (req.email, req.display_name.strip(), pw_hash),
    )
    db.commit()
    user_id = cursor.lastrowid
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/login")
def login(req: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT id, password_hash FROM users WHERE email = ?", (req.email,)).fetchone()
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.post("/refresh")
def refresh(req: RefreshRequest):
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user_id = int(payload["sub"])
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/reset-password/request")
def request_reset(req: ResetPasswordRequest, db: sqlite3.Connection = Depends(get_db)):
    """Generate a password reset token. Returns it in the response.

    In production with SMTP configured, this would email the token instead.
    """
    user = db.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
    if not user:
        # Don't reveal whether account exists
        return {"message": "If an account with that email exists, a reset token has been generated."}
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires.isoformat()),
    )
    db.commit()
    return {"message": "If an account with that email exists, a reset token has been generated.", "token": token}


@router.post("/reset-password/confirm")
def confirm_reset(req: ResetPasswordConfirm, db: sqlite3.Connection = Depends(get_db)):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    row = db.execute(
        """SELECT id, user_id FROM password_reset_tokens
           WHERE token = ? AND used = 0 AND expires_at > ?""",
        (req.token, datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    pw_hash = hash_password(req.new_password)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, row["user_id"]))
    db.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (row["id"],))
    db.commit()
    return {"message": "Password has been reset successfully."}


@router.get("/me")
def get_me(
    user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> UserResponse:
    membership = db.execute(
        """SELECT t.id, t.name, tm.status
           FROM troop_memberships tm JOIN troops t ON t.id = tm.troop_id
           WHERE tm.user_id = ?""",
        (user["id"],),
    ).fetchone()
    troop = None
    if membership:
        troop = {"id": membership["id"], "name": membership["name"], "status": membership["status"]}
    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        troop=troop,
    )
