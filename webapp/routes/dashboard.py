"""Dashboard data route: read-only SQL proxy scoped to user's troop database."""

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from webapp.dependencies import get_current_user_with_troop
from webapp.models import QueryRequest

router = APIRouter(prefix="/api/troop", tags=["dashboard"])

# Only allow SELECT and PRAGMA statements (read-only)
_ALLOWED_PATTERN = re.compile(r"^\s*(SELECT|PRAGMA)\b", re.IGNORECASE)
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)


@router.post("/query")
def execute_query(
    req: QueryRequest,
    user: dict = Depends(get_current_user_with_troop),
):
    """Execute a read-only SQL query against the user's troop database."""
    if not user["troop"]:
        raise HTTPException(status_code=403, detail="You must be an approved troop member to query data")

    sql = req.sql.strip()
    if not sql:
        raise HTTPException(status_code=400, detail="SQL query is required")

    if not _ALLOWED_PATTERN.match(sql):
        raise HTTPException(status_code=400, detail="Only SELECT and PRAGMA queries are allowed")

    if _FORBIDDEN_PATTERN.search(sql):
        raise HTTPException(status_code=400, detail="Write operations are not allowed")

    db_path = user["troop"]["db_path"]

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(sql, req.params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(row) for row in cursor.fetchall()]
            return {"columns": columns, "rows": rows}
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        if "unable to open" in str(e) or "no such file" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail="Troop database not found. Data may not have been synced yet.",
            )
        raise HTTPException(status_code=400, detail=f"Query error: {e}")
