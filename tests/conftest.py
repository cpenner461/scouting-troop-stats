"""Shared pytest fixtures."""

import sqlite3

import pytest

from scouting_db.db import init_db


@pytest.fixture
def conn():
    """In-memory SQLite DB with full schema initialized and Eagle MBs seeded."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c
