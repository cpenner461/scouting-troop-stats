"""Tests for scouting_db.queries."""

import sqlite3

import pytest

from scouting_db.db import init_db
from scouting_db.queries import (
    mb_requirement_detail,
    most_common_incomplete_merit_badges,
    optimal_group_activities,
    per_scout_summary,
    requirement_completion_matrix,
    scouts_closest_to_next_rank,
)


# ── Fixtures & helpers ────────────────────────────────────────────────────────


@pytest.fixture
def conn():
    """Fresh in-memory DB with schema and Eagle MBs seeded."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


def _add_rank(conn, rank_id, name="Test Rank", level=0, program_id=2):
    conn.execute(
        "INSERT OR REPLACE INTO ranks (id, name, level, program_id, active) VALUES (?, ?, ?, ?, 1)",
        (rank_id, name, level, program_id),
    )
    conn.commit()


def _add_scout(conn, user_id, first, last, rank_id=None):
    conn.execute(
        "INSERT OR REPLACE INTO scouts (user_id, first_name, last_name, current_rank_id) VALUES (?, ?, ?, ?)",
        (user_id, first, last, rank_id),
    )
    conn.commit()


def _add_mb(conn, name, is_eagle=0):
    conn.execute(
        "INSERT OR IGNORE INTO merit_badges (name, is_eagle_required, active) VALUES (?, ?, 1)",
        (name, is_eagle),
    )
    conn.commit()


def _add_scout_mb(conn, user_id, name, status="completed", mb_api_id=None):
    conn.execute(
        "INSERT OR REPLACE INTO scout_merit_badges "
        "(scout_user_id, merit_badge_name, status, mb_api_id) VALUES (?, ?, ?, ?)",
        (user_id, name, status, mb_api_id),
    )
    conn.commit()


def _add_requirement(conn, req_id, rank_id, req_number="1", parent_id=None, required=1):
    conn.execute(
        "INSERT OR REPLACE INTO requirements "
        "(id, rank_id, requirement_number, required, parent_requirement_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (req_id, rank_id, req_number, required, parent_id),
    )
    conn.commit()


def _add_req_completion(conn, user_id, req_id, rank_id, completed=1):
    conn.execute(
        "INSERT OR REPLACE INTO scout_requirement_completions "
        "(scout_user_id, requirement_id, rank_id, completed) VALUES (?, ?, ?, ?)",
        (user_id, req_id, rank_id, completed),
    )
    conn.commit()


# ── most_common_incomplete_merit_badges ───────────────────────────────────────


class TestMostCommonIncompleteMeritBadges:
    def test_includes_mbs_not_completed_by_scouts(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_mb(conn, "Rowing")
        rows = most_common_incomplete_merit_badges(conn)
        names = [r["merit_badge"] for r in rows]
        assert "Rowing" in names

    def test_excludes_mbs_completed_by_all_scouts(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        # "Swimming" is already Eagle-seeded; complete it for U1
        _add_scout_mb(conn, "U1", "Swimming", status="completed")
        rows = most_common_incomplete_merit_badges(conn)
        names = [r["merit_badge"] for r in rows]
        assert "Swimming" not in names

    def test_eagle_only_filter_excludes_non_eagle(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_mb(conn, "Rowing", is_eagle=0)
        rows = most_common_incomplete_merit_badges(conn, eagle_only=True)
        names = [r["merit_badge"] for r in rows]
        assert "Rowing" not in names

    def test_eagle_only_filter_includes_eagle_mbs(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        rows = most_common_incomplete_merit_badges(conn, eagle_only=True)
        # All 18 Eagle MBs should appear (scout hasn't completed any)
        assert len(rows) > 0
        assert all(r["is_eagle_required"] == 1 for r in rows)

    def test_limit_parameter_respected(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        for i in range(10):
            _add_mb(conn, f"ExtraBadge{i}")
        rows = most_common_incomplete_merit_badges(conn, limit=3)
        assert len(rows) <= 3

    def test_scouts_needing_reflects_count(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "UniqueTestMB")
        # Neither scout completed it
        rows = most_common_incomplete_merit_badges(conn)
        row = next((r for r in rows if r["merit_badge"] == "UniqueTestMB"), None)
        assert row is not None
        assert row["scouts_needing"] == 2

    def test_partial_completion_counted_correctly(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "PartialMB")
        _add_scout_mb(conn, "U1", "PartialMB", status="completed")
        # Only U2 needs it
        rows = most_common_incomplete_merit_badges(conn)
        row = next((r for r in rows if r["merit_badge"] == "PartialMB"), None)
        assert row is not None
        assert row["scouts_needing"] == 1

    def test_returns_expected_columns(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_mb(conn, "TestBadge")
        rows = most_common_incomplete_merit_badges(conn)
        assert len(rows) > 0
        keys = rows[0].keys()
        for col in ("merit_badge", "is_eagle_required", "scouts_needing", "total_scouts", "pct_needing"):
            assert col in keys

    def test_empty_scouts_returns_empty(self, conn):
        rows = most_common_incomplete_merit_badges(conn)
        assert rows == []


# ── scouts_closest_to_next_rank ───────────────────────────────────────────────


class TestScoutsClosestToNextRank:
    def test_returns_scout_with_next_rank_info(self, conn):
        _add_rank(conn, 1, "Scout", level=0)
        _add_rank(conn, 2, "Tenderfoot", level=1)
        _add_scout(conn, "U1", "Alice", "S", rank_id=1)
        _add_requirement(conn, 100, 2, "1")
        _add_requirement(conn, 101, 2, "2")
        _add_req_completion(conn, "U1", 100, 2, completed=1)
        _add_req_completion(conn, "U1", 101, 2, completed=0)

        rows = scouts_closest_to_next_rank(conn)
        assert len(rows) == 1
        row = rows[0]
        assert row["next_rank_name"] == "Tenderfoot"
        assert row["completed_requirements"] == 1
        assert row["remaining"] == 1

    def test_pct_complete_calculated(self, conn):
        _add_rank(conn, 1, "Scout", level=0)
        _add_rank(conn, 2, "Tenderfoot", level=1)
        _add_scout(conn, "U1", "Alice", "S", rank_id=1)
        _add_requirement(conn, 100, 2, "1")
        _add_requirement(conn, 101, 2, "2")
        _add_requirement(conn, 102, 2, "3")
        _add_requirement(conn, 103, 2, "4")
        # Complete 3 of 4
        for req_id in (100, 101, 102):
            _add_req_completion(conn, "U1", req_id, 2, completed=1)
        _add_req_completion(conn, "U1", 103, 2, completed=0)

        rows = scouts_closest_to_next_rank(conn)
        assert rows[0]["pct_complete"] == 75.0

    def test_scout_with_no_rank_gets_level_1_as_next(self, conn):
        _add_rank(conn, 1, "Scout", level=1)
        _add_scout(conn, "U1", "Alice", "S", rank_id=None)
        _add_requirement(conn, 100, 1, "1")

        rows = scouts_closest_to_next_rank(conn)
        assert any(r["next_rank_name"] == "Scout" for r in rows)

    def test_ordered_by_remaining_ascending(self, conn):
        _add_rank(conn, 1, "Scout", level=0)
        _add_rank(conn, 2, "Tenderfoot", level=1)
        _add_scout(conn, "U1", "Alice", "S", rank_id=1)
        _add_scout(conn, "U2", "Bob", "S", rank_id=1)
        _add_requirement(conn, 100, 2, "1")
        _add_requirement(conn, 101, 2, "2")
        _add_requirement(conn, 102, 2, "3")
        # U1 completes 2 of 3 (remaining=1), U2 completes 0 of 3 (remaining=3)
        _add_req_completion(conn, "U1", 100, 2, 1)
        _add_req_completion(conn, "U1", 101, 2, 1)
        _add_req_completion(conn, "U1", 102, 2, 0)
        _add_req_completion(conn, "U2", 100, 2, 0)

        rows = scouts_closest_to_next_rank(conn)
        assert len(rows) == 2
        assert "Alice" in rows[0]["scout_name"]  # Alice has fewer remaining

    def test_empty_when_no_scouts(self, conn):
        rows = scouts_closest_to_next_rank(conn)
        assert rows == []

    def test_excludes_scouts_where_no_next_rank_exists(self, conn):
        # Scout at max rank (no higher rank in DB)
        _add_rank(conn, 7, "Eagle Scout", level=7)
        _add_scout(conn, "U1", "Alice", "S", rank_id=7)
        rows = scouts_closest_to_next_rank(conn)
        assert rows == []


# ── requirement_completion_matrix ─────────────────────────────────────────────


class TestRequirementCompletionMatrix:
    def test_returns_top_level_requirements_for_rank(self, conn):
        _add_rank(conn, 10)
        _add_requirement(conn, 500, 10, "1")
        _add_requirement(conn, 501, 10, "2")
        _add_requirement(conn, 502, 10, "3")

        rows = requirement_completion_matrix(conn, 10)
        assert len(rows) == 3

    def test_completion_counts_are_accurate(self, conn):
        _add_rank(conn, 10)
        _add_requirement(conn, 500, 10, "1")
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_req_completion(conn, "U1", 500, 10, completed=1)
        # U2 has not completed

        rows = requirement_completion_matrix(conn, 10)
        assert len(rows) == 1
        row = rows[0]
        assert row["scouts_completed"] == 1
        assert row["scouts_needing"] == 1

    def test_excludes_child_requirements(self, conn):
        _add_rank(conn, 10)
        _add_requirement(conn, 500, 10, "1", parent_id=None)
        _add_requirement(conn, 501, 10, "1a", parent_id=500)

        rows = requirement_completion_matrix(conn, 10)
        req_numbers = [r["requirement_number"] for r in rows]
        assert "1" in req_numbers
        assert "1a" not in req_numbers

    def test_ordered_by_pct_incomplete_desc(self, conn):
        _add_rank(conn, 10)
        _add_requirement(conn, 500, 10, "1")
        _add_requirement(conn, 501, 10, "2")
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        # Req 500: both scouts completed it (0% incomplete)
        _add_req_completion(conn, "U1", 500, 10, 1)
        _add_req_completion(conn, "U2", 500, 10, 1)
        # Req 501: nobody completed it (100% incomplete)

        rows = requirement_completion_matrix(conn, 10)
        assert rows[0]["requirement_number"] == "2"  # most incomplete first

    def test_returns_empty_for_unknown_rank(self, conn):
        rows = requirement_completion_matrix(conn, 9999)
        assert rows == []

    def test_returns_expected_columns(self, conn):
        _add_rank(conn, 10)
        _add_requirement(conn, 500, 10, "1")
        rows = requirement_completion_matrix(conn, 10)
        assert len(rows) == 1
        keys = rows[0].keys()
        for col in ("requirement_number", "scouts_completed", "scouts_needing", "pct_incomplete"):
            assert col in keys


# ── per_scout_summary ─────────────────────────────────────────────────────────


class TestPerScoutSummary:
    def test_returns_one_row_per_scout(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        rows = per_scout_summary(conn)
        assert len(rows) == 2

    def test_empty_db_returns_empty(self, conn):
        rows = per_scout_summary(conn)
        assert rows == []

    def test_mb_counts_are_correct(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        # 2 completed (1 eagle, 1 non-eagle), 1 in_progress
        _add_mb(conn, "Swimming", is_eagle=1)
        _add_mb(conn, "Rowing", is_eagle=0)
        _add_mb(conn, "Cooking", is_eagle=1)
        _add_scout_mb(conn, "U1", "Swimming", "completed")
        _add_scout_mb(conn, "U1", "Rowing", "completed")
        _add_scout_mb(conn, "U1", "Cooking", "in_progress")

        rows = per_scout_summary(conn)
        assert len(rows) == 1
        row = rows[0]
        assert row["total_mbs_earned"] == 2
        assert row["eagle_mbs_earned"] == 1
        assert row["mbs_in_progress"] == 1

    def test_scout_name_concatenated(self, conn):
        _add_scout(conn, "U1", "Alice", "Smith")
        rows = per_scout_summary(conn)
        assert "Alice" in rows[0]["scout_name"]
        assert "Smith" in rows[0]["scout_name"]

    def test_rank_displayed_for_scout(self, conn):
        _add_rank(conn, 3, "First Class", level=3)
        _add_scout(conn, "U1", "Alice", "S", rank_id=3)
        rows = per_scout_summary(conn)
        assert rows[0]["current_rank"] == "First Class"

    def test_no_rank_shows_placeholder(self, conn):
        _add_scout(conn, "U1", "Alice", "S", rank_id=None)
        rows = per_scout_summary(conn)
        assert rows[0]["current_rank"] == "--"

    def test_scouts_ordered_by_rank_level_desc(self, conn):
        _add_rank(conn, 1, "Scout", level=1)
        _add_rank(conn, 4, "Star", level=4)
        _add_scout(conn, "U1", "Alice", "S", rank_id=1)
        _add_scout(conn, "U2", "Bob", "S", rank_id=4)

        rows = per_scout_summary(conn)
        # Higher rank (level=4) should come first
        assert "Bob" in rows[0]["scout_name"]


# ── mb_requirement_detail ─────────────────────────────────────────────────────


class TestMbRequirementDetail:
    def _setup_in_progress_mb(self, conn):
        """Set up U1 with 'First Aid' in_progress, two requirements (one done, one not)."""
        _add_scout(conn, "U1", "Alice", "S")
        conn.execute(
            "INSERT INTO mb_requirements "
            "(id, mb_api_id, mb_version_id, requirement_number, name, required, parent_requirement_id) "
            "VALUES (?, ?, ?, ?, ?, 1, NULL)",
            (1001, 50, "v1", "1", "Demonstrate first aid"),
        )
        conn.execute(
            "INSERT INTO mb_requirements "
            "(id, mb_api_id, mb_version_id, requirement_number, name, required, parent_requirement_id) "
            "VALUES (?, ?, ?, ?, ?, 1, NULL)",
            (1002, 50, "v1", "2", "Show bandaging"),
        )
        conn.execute(
            "INSERT INTO scout_merit_badges "
            "(scout_user_id, merit_badge_name, status, mb_api_id, mb_version_id) "
            "VALUES ('U1', 'First Aid', 'in_progress', 50, 'v1')"
        )
        conn.execute(
            "INSERT INTO scout_mb_requirement_completions "
            "(scout_user_id, mb_requirement_id, mb_api_id, mb_version_id, completed) "
            "VALUES ('U1', 1001, 50, 'v1', 1)"
        )
        conn.execute(
            "INSERT INTO scout_mb_requirement_completions "
            "(scout_user_id, mb_requirement_id, mb_api_id, mb_version_id, completed) "
            "VALUES ('U1', 1002, 50, 'v1', 0)"
        )
        conn.commit()

    def test_returns_requirement_rows(self, conn):
        self._setup_in_progress_mb(conn)
        rows = mb_requirement_detail(conn)
        assert len(rows) > 0

    def test_filter_by_merit_badge_name(self, conn):
        self._setup_in_progress_mb(conn)
        rows = mb_requirement_detail(conn, merit_badge_name="First Aid")
        assert len(rows) > 0
        assert all(r["merit_badge_name"] == "First Aid" for r in rows)

    def test_filter_excludes_other_mbs(self, conn):
        self._setup_in_progress_mb(conn)
        rows = mb_requirement_detail(conn, merit_badge_name="NonexistentMB")
        assert rows == []

    def test_empty_when_no_in_progress_mbs(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        rows = mb_requirement_detail(conn)
        assert rows == []

    def test_returns_expected_columns(self, conn):
        self._setup_in_progress_mb(conn)
        rows = mb_requirement_detail(conn)
        assert len(rows) > 0
        keys = rows[0].keys()
        for col in ("merit_badge_name", "requirement_number", "scouts_working", "scouts_done", "scouts_needing"):
            assert col in keys

    def test_completed_mb_not_included(self, conn):
        """Completed MBs should not appear in the detail query."""
        _add_scout(conn, "U1", "Alice", "S")
        conn.execute(
            "INSERT INTO scout_merit_badges "
            "(scout_user_id, merit_badge_name, status, mb_api_id, mb_version_id) "
            "VALUES ('U1', 'Cooking', 'completed', 60, 'v1')"
        )
        conn.execute(
            "INSERT INTO mb_requirements "
            "(id, mb_api_id, mb_version_id, requirement_number, name, required, parent_requirement_id) "
            "VALUES (2001, 60, 'v1', '1', 'Cook a meal', 1, NULL)"
        )
        conn.execute(
            "INSERT INTO scout_mb_requirement_completions "
            "(scout_user_id, mb_requirement_id, mb_api_id, mb_version_id, completed) "
            "VALUES ('U1', 2001, 60, 'v1', 1)"
        )
        conn.commit()
        rows = mb_requirement_detail(conn)
        assert rows == []


# ── optimal_group_activities ──────────────────────────────────────────────────


class TestOptimalGroupActivities:
    def test_includes_mbs_above_threshold(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "NewEagleMB", is_eagle=1)
        # Neither scout has it → 100% need it

        rows = optimal_group_activities(conn, min_pct=50.0)
        names = [r["activity_name"] for r in rows]
        assert "NewEagleMB" in names

    def test_excludes_mbs_below_threshold(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "RareMB")
        # Only U1 needs it (U2 completed it) → 50% need it
        _add_scout_mb(conn, "U2", "RareMB", status="completed")

        rows = optimal_group_activities(conn, min_pct=75.0)
        names = [r["activity_name"] for r in rows]
        assert "RareMB" not in names

    def test_eagle_mbs_ordered_before_non_eagle(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_mb(conn, "EagleMB", is_eagle=1)
        _add_mb(conn, "RegularMB", is_eagle=0)

        rows = optimal_group_activities(conn, min_pct=0.0)
        eagle_indices = [i for i, r in enumerate(rows) if r["is_eagle_required"] == 1]
        regular_indices = [i for i, r in enumerate(rows) if r["is_eagle_required"] == 0]
        if eagle_indices and regular_indices:
            assert max(eagle_indices) < min(regular_indices)

    def test_pct_benefiting_is_100_when_all_scouts_need_it(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "UniversalMB")

        rows = optimal_group_activities(conn, min_pct=0.0)
        row = next((r for r in rows if r["activity_name"] == "UniversalMB"), None)
        assert row is not None
        assert row["pct_benefiting"] == 100.0

    def test_empty_when_no_scouts(self, conn):
        rows = optimal_group_activities(conn)
        assert rows == []

    def test_returns_expected_columns(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_mb(conn, "TestMB")

        rows = optimal_group_activities(conn, min_pct=0.0)
        assert len(rows) > 0
        keys = rows[0].keys()
        for col in ("activity_name", "is_eagle_required", "scouts_benefiting", "total_scouts", "pct_benefiting"):
            assert col in keys

    def test_default_threshold_is_50_pct(self, conn):
        _add_scout(conn, "U1", "Alice", "S")
        _add_scout(conn, "U2", "Bob", "S")
        _add_mb(conn, "HalfNeededMB")
        # U1 completed it, U2 needs it → 50% need it
        _add_scout_mb(conn, "U1", "HalfNeededMB", status="completed")

        rows_default = optimal_group_activities(conn)
        names = [r["activity_name"] for r in rows_default]
        # At exactly 50% threshold with default min_pct=50.0, it should be included
        assert "HalfNeededMB" in names
