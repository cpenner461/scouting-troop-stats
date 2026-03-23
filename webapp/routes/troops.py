"""Troop management routes: create, join, approve, remove members."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from webapp.config import TROOP_DB_DIR
from webapp.dependencies import get_current_user, get_current_user_with_troop, get_db
from webapp.models import CreateTroopRequest, JoinTroopRequest, MemberResponse, TroopResponse

router = APIRouter(prefix="/api/troops", tags=["troops"])


@router.get("", response_model=list[TroopResponse])
def list_troops(db: sqlite3.Connection = Depends(get_db)):
    """List all troops (for the registration/join flow)."""
    rows = db.execute("SELECT id, name FROM troops ORDER BY name").fetchall()
    return [TroopResponse(id=r["id"], name=r["name"]) for r in rows]


@router.post("", response_model=TroopResponse, status_code=status.HTTP_201_CREATED)
def create_troop(
    req: CreateTroopRequest,
    user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Create a new troop. The creating user is auto-approved as a member."""
    # Check user doesn't already belong to a troop
    existing = db.execute(
        "SELECT id FROM troop_memberships WHERE user_id = ?", (user["id"],)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="You already belong to a troop")

    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Troop name is required")

    # Validate db_filename: must be a simple filename, no path traversal
    filename = req.db_filename.strip()
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid database filename")
    if not filename.endswith(".db"):
        filename += ".db"

    db_path = str(TROOP_DB_DIR / filename)

    existing_troop = db.execute("SELECT id FROM troops WHERE name = ?", (req.name.strip(),)).fetchone()
    if existing_troop:
        raise HTTPException(status_code=409, detail="A troop with this name already exists")

    cursor = db.execute(
        "INSERT INTO troops (name, db_path) VALUES (?, ?)",
        (req.name.strip(), db_path),
    )
    troop_id = cursor.lastrowid
    db.execute(
        "INSERT INTO troop_memberships (user_id, troop_id, status) VALUES (?, ?, 'approved')",
        (user["id"], troop_id),
    )
    db.commit()
    return TroopResponse(id=troop_id, name=req.name.strip())


@router.post("/join")
def join_troop(
    req: JoinTroopRequest,
    user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Request to join an existing troop (pending approval)."""
    existing = db.execute(
        "SELECT id FROM troop_memberships WHERE user_id = ?", (user["id"],)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="You already belong to a troop")

    troop = db.execute("SELECT id FROM troops WHERE id = ?", (req.troop_id,)).fetchone()
    if not troop:
        raise HTTPException(status_code=404, detail="Troop not found")

    db.execute(
        "INSERT INTO troop_memberships (user_id, troop_id, status) VALUES (?, ?, 'pending')",
        (user["id"], req.troop_id),
    )
    db.commit()
    return {"message": "Join request submitted. An existing troop member must approve your request."}


@router.get("/mine")
def get_my_troop(user: dict = Depends(get_current_user_with_troop)):
    if not user["troop"]:
        raise HTTPException(status_code=404, detail="You are not a member of any troop")
    return {
        "id": user["troop"]["troop_id"],
        "name": user["troop"]["troop_name"],
    }


@router.get("/members", response_model=list[MemberResponse])
def list_members(
    user: dict = Depends(get_current_user_with_troop),
    db: sqlite3.Connection = Depends(get_db),
):
    """List all members of the current user's troop."""
    if not user["troop"]:
        raise HTTPException(status_code=404, detail="You are not a member of any troop")
    rows = db.execute(
        """SELECT u.id AS user_id, u.email, u.display_name, tm.status, tm.created_at
           FROM troop_memberships tm JOIN users u ON u.id = tm.user_id
           WHERE tm.troop_id = ? AND tm.status = 'approved'
           ORDER BY tm.created_at""",
        (user["troop"]["troop_id"],),
    ).fetchall()
    return [
        MemberResponse(
            user_id=r["user_id"], email=r["email"], display_name=r["display_name"],
            status=r["status"], joined_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/pending", response_model=list[MemberResponse])
def list_pending(
    user: dict = Depends(get_current_user_with_troop),
    db: sqlite3.Connection = Depends(get_db),
):
    """List pending join requests for the current user's troop."""
    if not user["troop"]:
        raise HTTPException(status_code=404, detail="You are not a member of any troop")
    rows = db.execute(
        """SELECT u.id AS user_id, u.email, u.display_name, tm.status, tm.created_at
           FROM troop_memberships tm JOIN users u ON u.id = tm.user_id
           WHERE tm.troop_id = ? AND tm.status = 'pending'
           ORDER BY tm.created_at""",
        (user["troop"]["troop_id"],),
    ).fetchall()
    return [
        MemberResponse(
            user_id=r["user_id"], email=r["email"], display_name=r["display_name"],
            status=r["status"], joined_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/members/{user_id}/approve")
def approve_member(
    user_id: int,
    user: dict = Depends(get_current_user_with_troop),
    db: sqlite3.Connection = Depends(get_db),
):
    """Approve a pending join request."""
    if not user["troop"]:
        raise HTTPException(status_code=403, detail="You are not a member of any troop")
    result = db.execute(
        """UPDATE troop_memberships SET status = 'approved'
           WHERE user_id = ? AND troop_id = ? AND status = 'pending'""",
        (user_id, user["troop"]["troop_id"]),
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No pending request found for this user")
    return {"message": "Member approved."}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: int,
    user: dict = Depends(get_current_user_with_troop),
    db: sqlite3.Connection = Depends(get_db),
):
    """Remove a member from the troop. Any troop member can remove any other member."""
    if not user["troop"]:
        raise HTTPException(status_code=403, detail="You are not a member of any troop")
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself. Leave the troop instead.")
    result = db.execute(
        "DELETE FROM troop_memberships WHERE user_id = ? AND troop_id = ?",
        (user_id, user["troop"]["troop_id"]),
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User is not a member of your troop")
    return {"message": "Member removed."}
