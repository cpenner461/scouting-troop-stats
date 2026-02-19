"""MCP server exposing Scouting troop SQLite database to Claude."""

import json
import os
import sqlite3

from mcp.server.fastmcp import FastMCP

DB_PATH = os.environ.get("BSA_DB_PATH", "scouting_troop.db")

mcp = FastMCP("scouting")


def _connect() -> sqlite3.Connection:
    """Open a read-only connection to the database."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def schema() -> str:
    """Return all CREATE TABLE and CREATE INDEX statements from the database.

    Call this first to understand the database structure before writing queries.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        return "\n\n".join(row["sql"] for row in rows)
    finally:
        conn.close()


@mcp.tool()
def query(sql: str) -> str:
    """Execute a read-only SQL query and return results as JSON.

    The database is opened in read-only mode so only SELECT statements will work.
    """
    conn = _connect()
    try:
        rows = conn.execute(sql).fetchall()
        return json.dumps([dict(row) for row in rows], default=str)
    finally:
        conn.close()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
