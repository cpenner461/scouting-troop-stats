"""FastAPI dependencies (auth, database)."""

import sqlite3

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from webapp.auth import decode_token
from webapp.database import get_app_db

security = HTTPBearer()


def get_db():
    conn = get_app_db()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id = int(payload["sub"])
    user = db.execute("SELECT id, email, display_name FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return dict(user)


def get_current_user_with_troop(
    user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Get current user and their approved troop membership."""
    membership = db.execute(
        """SELECT t.id AS troop_id, t.name AS troop_name, t.db_path
           FROM troop_memberships tm
           JOIN troops t ON t.id = tm.troop_id
           WHERE tm.user_id = ? AND tm.status = 'approved'""",
        (user["id"],),
    ).fetchone()
    if membership:
        user["troop"] = dict(membership)
    else:
        user["troop"] = None
    return user
