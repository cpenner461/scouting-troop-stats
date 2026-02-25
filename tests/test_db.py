"""Tests for scouting_db.db."""

import csv
import sqlite3

import pytest

from scouting_db.db import (
    EAGLE_REQUIRED_MERIT_BADGES,
    get_connection,
    import_roster_csv,
    init_db,
    seed_eagle_merit_badges,
    set_setting,
    store_leadership,
    store_youth_mb_requirements,
    store_youth_merit_badges,
    store_youth_rank_requirements,
    store_youth_ranks,
    upsert_mb_requirements,
    upsert_ranks,
    upsert_requirements,
    upsert_scout,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _insert_rank(conn, rank_id, name="Test Rank", level=0, program_id=2):
    conn.execute(
        "INSERT OR REPLACE INTO ranks (id, name, level, program_id, active) VALUES (?, ?, ?, ?, 1)",
        (rank_id, name, level, program_id),
    )
    conn.commit()


def _insert_scout(conn, user_id="U1", first="Alice", last="Scout"):
    upsert_scout(conn, user_id, first, last)


def _write_csv(tmp_path, headers, rows, filename="roster.csv"):
    path = tmp_path / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


# ── get_connection ────────────────────────────────────────────────────────────


class TestGetConnection:
    def test_returns_sqlite_connection(self, tmp_path):
        conn = get_connection(str(tmp_path / "test.db"))
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_is_sqlite_row(self, tmp_path):
        conn = get_connection(str(tmp_path / "test.db"))
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_foreign_keys_enabled(self, tmp_path):
        conn = get_connection(str(tmp_path / "test.db"))
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
        conn.close()


# ── init_db ───────────────────────────────────────────────────────────────────


class TestInitDb:
    def test_creates_all_tables(self, conn):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "settings",
            "ranks",
            "requirements",
            "merit_badges",
            "scouts",
            "scout_advancements",
            "scout_merit_badges",
            "scout_requirement_completions",
            "scout_leadership",
            "mb_requirements",
            "scout_mb_requirement_completions",
        }
        assert expected.issubset(tables)

    def test_creates_indexes(self, conn):
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_scout_adv_type" in indexes
        assert "idx_scout_mb_status" in indexes

    def test_seeds_eagle_merit_badges(self, conn):
        count = conn.execute(
            "SELECT COUNT(*) FROM merit_badges WHERE is_eagle_required = 1"
        ).fetchone()[0]
        assert count == len(EAGLE_REQUIRED_MERIT_BADGES)

    def test_sets_troop_name_when_provided(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        init_db(c, troop_name="Troop 13")
        row = c.execute("SELECT value FROM settings WHERE key='troop_name'").fetchone()
        assert row["value"] == "Troop 13"

    def test_no_troop_name_setting_when_omitted(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        init_db(c)
        row = c.execute("SELECT value FROM settings WHERE key='troop_name'").fetchone()
        assert row is None

    def test_idempotent_no_duplicates(self, conn):
        init_db(conn)  # run a second time
        count = conn.execute("SELECT COUNT(*) FROM merit_badges").fetchone()[0]
        assert count == len(EAGLE_REQUIRED_MERIT_BADGES)


# ── set_setting ───────────────────────────────────────────────────────────────


class TestSetSetting:
    def test_inserts_new_setting(self, conn):
        set_setting(conn, "mykey", "myval")
        row = conn.execute("SELECT value FROM settings WHERE key='mykey'").fetchone()
        assert row["value"] == "myval"

    def test_updates_existing_setting(self, conn):
        set_setting(conn, "mykey", "first")
        set_setting(conn, "mykey", "second")
        row = conn.execute("SELECT value FROM settings WHERE key='mykey'").fetchone()
        assert row["value"] == "second"

    def test_multiple_keys_independent(self, conn):
        set_setting(conn, "a", "1")
        set_setting(conn, "b", "2")
        assert conn.execute("SELECT value FROM settings WHERE key='a'").fetchone()["value"] == "1"
        assert conn.execute("SELECT value FROM settings WHERE key='b'").fetchone()["value"] == "2"


# ── seed_eagle_merit_badges ───────────────────────────────────────────────────


class TestSeedEagleMeritBadges:
    def test_all_eagle_mbs_present(self, conn):
        rows = conn.execute(
            "SELECT name FROM merit_badges WHERE is_eagle_required = 1"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert names == set(EAGLE_REQUIRED_MERIT_BADGES)

    def test_all_mbs_marked_active(self, conn):
        inactive = conn.execute(
            "SELECT COUNT(*) FROM merit_badges WHERE is_eagle_required = 1 AND active = 0"
        ).fetchone()[0]
        assert inactive == 0

    def test_idempotent_no_duplicates(self, conn):
        seed_eagle_merit_badges(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM merit_badges WHERE is_eagle_required = 1"
        ).fetchone()[0]
        assert count == len(EAGLE_REQUIRED_MERIT_BADGES)

    def test_correct_count(self, conn):
        assert len(EAGLE_REQUIRED_MERIT_BADGES) == 18


# ── upsert_ranks ──────────────────────────────────────────────────────────────


class TestUpsertRanks:
    def test_from_list(self, conn):
        count = upsert_ranks(conn, [{"id": 1, "name": "Scout", "level": 0, "programId": 2}])
        assert count == 1
        row = conn.execute("SELECT name FROM ranks WHERE id=1").fetchone()
        assert row["name"] == "Scout"

    def test_from_dict_with_value_key(self, conn):
        data = {"value": [{"id": 2, "name": "Tenderfoot", "level": 1, "programId": 2}]}
        count = upsert_ranks(conn, data)
        assert count == 1
        assert conn.execute("SELECT id FROM ranks WHERE id=2").fetchone() is not None

    def test_from_dict_with_ranks_key(self, conn):
        data = {"ranks": [{"id": 3, "name": "Second Class", "level": 2, "programId": 2}]}
        count = upsert_ranks(conn, data)
        assert count == 1

    def test_updates_existing_rank(self, conn):
        upsert_ranks(conn, [{"id": 1, "name": "Old", "level": 0, "programId": 2}])
        upsert_ranks(conn, [{"id": 1, "name": "New", "level": 0, "programId": 2}])
        row = conn.execute("SELECT name FROM ranks WHERE id=1").fetchone()
        assert row["name"] == "New"

    def test_active_string_true_stored_as_1(self, conn):
        upsert_ranks(conn, [{"id": 1, "name": "R", "level": 0, "programId": 2, "active": "True"}])
        row = conn.execute("SELECT active FROM ranks WHERE id=1").fetchone()
        assert row["active"] == 1

    def test_active_string_false_stored_as_0(self, conn):
        upsert_ranks(conn, [{"id": 1, "name": "R", "level": 0, "programId": 2, "active": "False"}])
        row = conn.execute("SELECT active FROM ranks WHERE id=1").fetchone()
        assert row["active"] == 0

    def test_multiple_ranks_returns_count(self, conn):
        ranks = [{"id": i, "name": f"Rank{i}", "level": i, "programId": 2} for i in range(1, 6)]
        count = upsert_ranks(conn, ranks)
        assert count == 5

    def test_stores_image_url(self, conn):
        upsert_ranks(conn, [{"id": 1, "name": "Scout", "level": 0, "programId": 2, "imageUrl200": "http://img.example.com/scout.png"}])
        row = conn.execute("SELECT image_url FROM ranks WHERE id=1").fetchone()
        assert row["image_url"] == "http://img.example.com/scout.png"


# ── upsert_requirements ───────────────────────────────────────────────────────


class TestUpsertRequirements:
    def test_flat_requirements(self, conn):
        _insert_rank(conn, 10)
        reqs = [
            {"id": 100, "requirementNumber": "1", "name": "Req 1"},
            {"id": 101, "requirementNumber": "2", "name": "Req 2"},
        ]
        count = upsert_requirements(conn, 10, reqs)
        assert count == 2
        rows = conn.execute("SELECT id FROM requirements WHERE rank_id=10").fetchall()
        assert len(rows) == 2

    def test_nested_requirements_sets_parent_id(self, conn):
        _insert_rank(conn, 10)
        reqs = [
            {
                "id": 100,
                "requirementNumber": "1",
                "name": "Parent",
                "requirements": [
                    {"id": 101, "requirementNumber": "1a", "name": "Child"},
                ],
            }
        ]
        count = upsert_requirements(conn, 10, reqs)
        assert count == 2
        child = conn.execute(
            "SELECT parent_requirement_id FROM requirements WHERE id=101"
        ).fetchone()
        assert child["parent_requirement_id"] == 100

    def test_deeply_nested_requirements(self, conn):
        _insert_rank(conn, 10)
        reqs = [
            {
                "id": 100,
                "requirementNumber": "1",
                "name": "L1",
                "requirements": [
                    {
                        "id": 101,
                        "requirementNumber": "1a",
                        "name": "L2",
                        "children": [
                            {"id": 102, "requirementNumber": "1a-i", "name": "L3"},
                        ],
                    }
                ],
            }
        ]
        count = upsert_requirements(conn, 10, reqs)
        assert count == 3

    def test_from_dict_requirements_key(self, conn):
        _insert_rank(conn, 10)
        count = upsert_requirements(conn, 10, {"requirements": [{"id": 200, "requirementNumber": "1", "name": "R"}]})
        assert count == 1

    def test_from_dict_value_key(self, conn):
        _insert_rank(conn, 10)
        count = upsert_requirements(conn, 10, {"value": [{"id": 300, "requirementNumber": "1", "name": "R"}]})
        assert count == 1

    def test_skips_items_without_id(self, conn):
        _insert_rank(conn, 10)
        reqs = [
            {"requirementNumber": "1", "name": "No ID"},
            {"id": 400, "requirementNumber": "2", "name": "Has ID"},
        ]
        count = upsert_requirements(conn, 10, reqs)
        assert count == 1

    def test_required_field_stored(self, conn):
        _insert_rank(conn, 10)
        upsert_requirements(conn, 10, [{"id": 500, "required": "False"}])
        row = conn.execute("SELECT required FROM requirements WHERE id=500").fetchone()
        assert row["required"] == 0


# ── upsert_scout ──────────────────────────────────────────────────────────────


class TestUpsertScout:
    def test_inserts_new_scout(self, conn):
        upsert_scout(conn, "U1", "Alice", "Smith")
        row = conn.execute("SELECT first_name, last_name FROM scouts WHERE user_id='U1'").fetchone()
        assert row["first_name"] == "Alice"
        assert row["last_name"] == "Smith"

    def test_update_preserves_existing_value_on_none(self, conn):
        upsert_scout(conn, "U1", "Alice", "Smith", patrol="Eagle")
        upsert_scout(conn, "U1", patrol=None)  # None should not overwrite "Eagle"
        row = conn.execute("SELECT patrol FROM scouts WHERE user_id='U1'").fetchone()
        assert row["patrol"] == "Eagle"

    def test_update_overwrites_with_new_value(self, conn):
        upsert_scout(conn, "U1", "Alice", "Smith", patrol="Eagle")
        upsert_scout(conn, "U1", patrol="Falcon")
        row = conn.execute("SELECT patrol FROM scouts WHERE user_id='U1'").fetchone()
        assert row["patrol"] == "Falcon"

    def test_sets_last_synced_at(self, conn):
        upsert_scout(conn, "U1")
        row = conn.execute("SELECT last_synced_at FROM scouts WHERE user_id='U1'").fetchone()
        assert row["last_synced_at"] is not None

    def test_stores_birthdate(self, conn):
        upsert_scout(conn, "U1", birthdate="2010-05-15")
        row = conn.execute("SELECT birthdate FROM scouts WHERE user_id='U1'").fetchone()
        assert row["birthdate"] == "2010-05-15"

    def test_stores_scouting_member_id(self, conn):
        upsert_scout(conn, "U1", scouting_member_id="M12345")
        row = conn.execute("SELECT scouting_member_id FROM scouts WHERE user_id='U1'").fetchone()
        assert row["scouting_member_id"] == "M12345"


# ── import_roster_csv ─────────────────────────────────────────────────────────


class TestImportRosterCsv:
    def test_standard_scoutbook_columns(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["User ID", "First Name", "Last Name", "Patrol"],
            [
                {"User ID": "U1", "First Name": "Alice", "Last Name": "Scout", "Patrol": "Eagle"},
                {"User ID": "U2", "First Name": "Bob", "Last Name": "Smith", "Patrol": "Falcon"},
            ],
        )
        imported, skipped = import_roster_csv(conn, path)
        assert imported == 2
        assert skipped == 0
        row = conn.execute("SELECT patrol FROM scouts WHERE user_id='U1'").fetchone()
        assert row["patrol"] == "Eagle"

    def test_alternative_column_names_userid_first_last(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["UserID", "First", "Last"],
            [{"UserID": "U3", "First": "Carol", "Last": "Jones"}],
        )
        imported, skipped = import_roster_csv(conn, path)
        assert imported == 1
        assert skipped == 0
        row = conn.execute("SELECT first_name FROM scouts WHERE user_id='U3'").fetchone()
        assert row["first_name"] == "Carol"

    def test_name_column_splits_into_first_and_last(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["User ID", "Name"],
            [{"User ID": "U4", "Name": "Dave Miller"}],
        )
        imported, _ = import_roster_csv(conn, path)
        assert imported == 1
        row = conn.execute(
            "SELECT first_name, last_name FROM scouts WHERE user_id='U4'"
        ).fetchone()
        assert row["first_name"] == "Dave"
        assert row["last_name"] == "Miller"

    def test_type_column_filters_non_youth(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["User ID", "First Name", "Last Name", "Type"],
            [
                {"User ID": "U1", "First Name": "Alice", "Last Name": "S", "Type": "YOUTH"},
                {"User ID": "U2", "First Name": "Bob", "Last Name": "L", "Type": "ADULT"},
            ],
        )
        imported, skipped = import_roster_csv(conn, path)
        assert imported == 1
        assert skipped == 1
        assert conn.execute("SELECT user_id FROM scouts WHERE user_id='U1'").fetchone() is not None
        assert conn.execute("SELECT user_id FROM scouts WHERE user_id='U2'").fetchone() is None

    def test_missing_id_columns_raises_value_error(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["First Name", "Last Name"],
            [{"First Name": "Alice", "Last Name": "Scout"}],
        )
        with pytest.raises(ValueError, match="User ID"):
            import_roster_csv(conn, path)

    def test_rows_without_id_are_skipped(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["User ID", "First Name", "Last Name"],
            [
                {"User ID": "", "First Name": "Ghost", "Last Name": "Scout"},
                {"User ID": "U5", "First Name": "Real", "Last Name": "Scout"},
            ],
        )
        imported, skipped = import_roster_csv(conn, path)
        assert imported == 1
        assert skipped == 1

    def test_member_id_used_as_primary_when_no_user_id(self, conn, tmp_path):
        path = _write_csv(
            tmp_path,
            ["Scouting Member ID", "First Name", "Last Name"],
            [{"Scouting Member ID": "M100", "First Name": "Eve", "Last Name": "W"}],
        )
        imported, _ = import_roster_csv(conn, path)
        assert imported == 1
        assert conn.execute("SELECT user_id FROM scouts WHERE user_id='M100'").fetchone() is not None

    def test_bom_utf8_encoding_handled(self, conn, tmp_path):
        path = tmp_path / "roster_bom.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            f.write("User ID,First Name,Last Name\nU9,Test,Scout\n")
        imported, _ = import_roster_csv(conn, path)
        assert imported == 1


# ── store_youth_ranks ─────────────────────────────────────────────────────────


class TestStoreYouthRanks:
    def _make_response(self, program_id=2, ranks=None):
        return {
            "program": [
                {
                    "programId": program_id,
                    "program": "Scouts BSA",
                    "ranks": ranks or [],
                }
            ]
        }

    def test_stores_completed_rank(self, conn):
        _insert_scout(conn, "U1")
        resp = self._make_response(ranks=[{"id": 1, "name": "Scout", "dateEarned": "2023-01-01"}])
        total = store_youth_ranks(conn, "U1", resp)
        assert total == 1
        row = conn.execute(
            "SELECT status, date_completed FROM scout_advancements WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["status"] == "completed"
        assert row["date_completed"] == "2023-01-01"

    def test_stores_in_progress_rank(self, conn):
        _insert_scout(conn, "U1")
        resp = self._make_response(ranks=[{"id": 5, "name": "Eagle Scout"}])
        store_youth_ranks(conn, "U1", resp)
        row = conn.execute(
            "SELECT status FROM scout_advancements WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["status"] == "in_progress"

    def test_updates_current_rank_id_to_highest_earned(self, conn):
        _insert_scout(conn, "U1")
        resp = self._make_response(
            ranks=[
                {"id": 1, "name": "Scout", "dateEarned": "2022-01-01"},
                {"id": 3, "name": "First Class", "dateEarned": "2023-06-01"},
                {"id": 2, "name": "Tenderfoot", "dateEarned": "2022-06-01"},
            ]
        )
        store_youth_ranks(conn, "U1", resp)
        row = conn.execute("SELECT current_rank_id FROM scouts WHERE user_id='U1'").fetchone()
        assert row["current_rank_id"] == 3

    def test_non_bsa_program_does_not_update_current_rank(self, conn):
        _insert_scout(conn, "U1")
        resp = self._make_response(program_id=99, ranks=[{"id": 10, "name": "Lion", "dateEarned": "2020-01-01"}])
        store_youth_ranks(conn, "U1", resp)
        row = conn.execute("SELECT current_rank_id FROM scouts WHERE user_id='U1'").fetchone()
        assert row["current_rank_id"] is None

    def test_returns_total_count(self, conn):
        _insert_scout(conn, "U1")
        resp = self._make_response(
            ranks=[
                {"id": 1, "name": "Scout", "dateEarned": "2022-01-01"},
                {"id": 2, "name": "Tenderfoot"},
            ]
        )
        total = store_youth_ranks(conn, "U1", resp)
        assert total == 2

    def test_empty_programs_returns_zero(self, conn):
        _insert_scout(conn, "U1")
        total = store_youth_ranks(conn, "U1", {"program": []})
        assert total == 0


# ── store_youth_merit_badges ──────────────────────────────────────────────────


class TestStoreYouthMeritBadges:
    def test_completed_mb(self, conn):
        _insert_scout(conn, "U1")
        items = [{"name": "Cooking", "dateCompleted": "2023-05-01", "isEagleRequired": True, "id": 50, "versionId": "v1"}]
        earned, total = store_youth_merit_badges(conn, "U1", items)
        assert earned == 1
        assert total == 1
        row = conn.execute(
            "SELECT status, date_completed FROM scout_merit_badges WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["status"] == "completed"
        assert row["date_completed"] == "2023-05-01"

    def test_in_progress_mb_with_date_started(self, conn):
        _insert_scout(conn, "U1")
        items = [{"name": "Camping", "dateStarted": "2023-01-01", "id": 51, "versionId": "v1"}]
        earned, total = store_youth_merit_badges(conn, "U1", items)
        assert earned == 0
        assert total == 1
        row = conn.execute(
            "SELECT status FROM scout_merit_badges WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["status"] == "in_progress"

    def test_updates_merit_badge_eagle_flag(self, conn):
        _insert_scout(conn, "U1")
        items = [{"name": "NewBadge", "dateCompleted": "2023-01-01", "isEagleRequired": True, "id": 99, "versionId": "v1"}]
        store_youth_merit_badges(conn, "U1", items)
        row = conn.execute(
            "SELECT is_eagle_required FROM merit_badges WHERE name='NewBadge'"
        ).fetchone()
        assert row["is_eagle_required"] == 1

    def test_uses_short_field_when_name_absent(self, conn):
        _insert_scout(conn, "U1")
        items = [{"short": "FallbackName", "dateCompleted": "2023-01-01", "id": 77, "versionId": "v1"}]
        store_youth_merit_badges(conn, "U1", items)
        row = conn.execute(
            "SELECT merit_badge_name FROM scout_merit_badges WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["merit_badge_name"] == "FallbackName"

    def test_empty_list_returns_zeros(self, conn):
        _insert_scout(conn, "U1")
        earned, total = store_youth_merit_badges(conn, "U1", [])
        assert earned == 0
        assert total == 0

    def test_non_list_input_treated_as_empty(self, conn):
        _insert_scout(conn, "U1")
        earned, total = store_youth_merit_badges(conn, "U1", {"unexpected": "dict"})
        assert earned == 0
        assert total == 0

    def test_date_earned_field_recognized(self, conn):
        _insert_scout(conn, "U1")
        items = [{"name": "Swimming", "dateEarned": "2023-03-01", "id": 60, "versionId": "v1"}]
        earned, total = store_youth_merit_badges(conn, "U1", items)
        assert earned == 1

    def test_multiple_mbs_for_same_scout(self, conn):
        _insert_scout(conn, "U1")
        items = [
            {"name": "Cooking", "dateCompleted": "2023-01-01", "id": 1, "versionId": "v1"},
            {"name": "Swimming", "dateCompleted": "2023-02-01", "id": 2, "versionId": "v1"},
            {"name": "Camping", "id": 3, "versionId": "v1"},
        ]
        earned, total = store_youth_merit_badges(conn, "U1", items)
        assert earned == 2
        assert total == 3


# ── upsert_mb_requirements ────────────────────────────────────────────────────


class TestUpsertMbRequirements:
    def test_flat_requirements(self, conn):
        reqs = [
            {"id": 1000, "requirementNumber": "1", "name": "Req A"},
            {"id": 1001, "requirementNumber": "2", "name": "Req B"},
        ]
        count = upsert_mb_requirements(conn, mb_api_id=50, mb_version_id="v1", requirements=reqs)
        assert count == 2

    def test_nested_requirements_sets_parent(self, conn):
        reqs = [
            {
                "id": 2000,
                "requirementNumber": "1",
                "name": "Parent",
                "requirements": [
                    {"id": 2001, "requirementNumber": "1a", "name": "Child"},
                ],
            }
        ]
        count = upsert_mb_requirements(conn, 55, "v2", reqs)
        assert count == 2
        child = conn.execute(
            "SELECT parent_requirement_id FROM mb_requirements WHERE id=2001"
        ).fetchone()
        assert child["parent_requirement_id"] == 2000

    def test_from_dict_requirements_key(self, conn):
        data = {"requirements": [{"id": 3000, "requirementNumber": "1", "name": "R"}]}
        count = upsert_mb_requirements(conn, 60, "v1", data)
        assert count == 1

    def test_stores_mb_api_id_and_version(self, conn):
        upsert_mb_requirements(conn, 77, "v3", [{"id": 4000, "requirementNumber": "1", "name": "X"}])
        row = conn.execute(
            "SELECT mb_api_id, mb_version_id FROM mb_requirements WHERE id=4000"
        ).fetchone()
        assert row["mb_api_id"] == 77
        assert row["mb_version_id"] == "v3"

    def test_skips_items_without_id(self, conn):
        reqs = [
            {"requirementNumber": "1", "name": "No ID"},
            {"id": 5000, "requirementNumber": "2", "name": "Has ID"},
        ]
        count = upsert_mb_requirements(conn, 80, "v1", reqs)
        assert count == 1


# ── store_youth_mb_requirements ───────────────────────────────────────────────


class TestStoreYouthMbRequirements:
    def test_completed_requirement(self, conn):
        _insert_scout(conn, "U1")
        count = store_youth_mb_requirements(conn, "U1", 50, "v1", [{"id": 1000, "dateCompleted": "2023-06-01"}])
        assert count == 1
        row = conn.execute(
            "SELECT completed, date_completed FROM scout_mb_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["completed"] == 1
        assert row["date_completed"] == "2023-06-01"

    def test_incomplete_requirement(self, conn):
        _insert_scout(conn, "U1")
        store_youth_mb_requirements(conn, "U1", 50, "v1", [{"id": 1001}])
        row = conn.execute(
            "SELECT completed FROM scout_mb_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["completed"] == 0

    def test_date_earned_field_recognized(self, conn):
        _insert_scout(conn, "U1")
        store_youth_mb_requirements(conn, "U1", 50, "v1", [{"id": 1002, "dateEarned": "2023-01-01"}])
        row = conn.execute(
            "SELECT completed FROM scout_mb_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["completed"] == 1

    def test_recursive_children(self, conn):
        _insert_scout(conn, "U1")
        reqs = [
            {
                "id": 2000,
                "dateCompleted": "2023-01-01",
                "requirements": [{"id": 2001}],
            }
        ]
        count = store_youth_mb_requirements(conn, "U1", 55, "v2", reqs)
        assert count == 2

    def test_from_dict_value_key(self, conn):
        _insert_scout(conn, "U1")
        count = store_youth_mb_requirements(conn, "U1", 60, "v1", {"value": [{"id": 3000}]})
        assert count == 1

    def test_stores_mb_api_id(self, conn):
        _insert_scout(conn, "U1")
        store_youth_mb_requirements(conn, "U1", 77, "v2", [{"id": 4000}])
        row = conn.execute(
            "SELECT mb_api_id, mb_version_id FROM scout_mb_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["mb_api_id"] == 77
        assert row["mb_version_id"] == "v2"


# ── store_youth_rank_requirements ─────────────────────────────────────────────


class TestStoreYouthRankRequirements:
    def _setup(self, conn, req_id=500, rank_id=10):
        _insert_rank(conn, rank_id)
        _insert_scout(conn, "U1")
        conn.execute(
            "INSERT INTO requirements (id, rank_id, required) VALUES (?, ?, 1)",
            (req_id, rank_id),
        )
        conn.commit()

    def test_completed_requirement(self, conn):
        self._setup(conn)
        count = store_youth_rank_requirements(conn, "U1", 10, [{"id": 500, "dateCompleted": "2023-03-01"}])
        assert count == 1
        row = conn.execute(
            "SELECT completed, date_completed FROM scout_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["completed"] == 1
        assert row["date_completed"] == "2023-03-01"

    def test_incomplete_requirement(self, conn):
        self._setup(conn)
        store_youth_rank_requirements(conn, "U1", 10, [{"id": 500}])
        row = conn.execute(
            "SELECT completed FROM scout_requirement_completions WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["completed"] == 0

    def test_recursive_children(self, conn):
        _insert_rank(conn, 10)
        _insert_scout(conn, "U1")
        conn.execute("INSERT INTO requirements (id, rank_id, required) VALUES (600, 10, 1)")
        conn.execute(
            "INSERT INTO requirements (id, rank_id, parent_requirement_id, required) VALUES (601, 10, 600, 1)"
        )
        conn.commit()
        reqs = [{"id": 600, "requirements": [{"id": 601, "dateCompleted": "2023-01-01"}]}]
        count = store_youth_rank_requirements(conn, "U1", 10, reqs)
        assert count == 2

    def test_from_dict_value_key(self, conn):
        self._setup(conn)
        count = store_youth_rank_requirements(conn, "U1", 10, {"value": [{"id": 500}]})
        assert count == 1

    def test_from_dict_requirements_key(self, conn):
        self._setup(conn)
        count = store_youth_rank_requirements(conn, "U1", 10, {"requirements": [{"id": 500}]})
        assert count == 1


# ── store_leadership ──────────────────────────────────────────────────────────


class TestStoreLeadership:
    def test_from_list(self, conn):
        _insert_scout(conn, "U1")
        positions = [
            {
                "positionTitle": "Senior Patrol Leader",
                "dateStarted": "2023-01-01",
                "dateEnded": "2023-12-31",
                "approvalStatus": "Approved",
                "numberOfDaysInPosition": 365,
            }
        ]
        count = store_leadership(conn, "U1", positions)
        assert count == 1
        row = conn.execute(
            "SELECT position, approved, days_in_position FROM scout_leadership WHERE scout_user_id='U1'"
        ).fetchone()
        assert row["position"] == "Senior Patrol Leader"
        assert row["approved"] == 1
        assert row["days_in_position"] == 365

    def test_from_dict_value_key(self, conn):
        _insert_scout(conn, "U1")
        data = {"value": [{"positionTitle": "Patrol Leader", "dateStarted": "2023-06-01"}]}
        count = store_leadership(conn, "U1", data)
        assert count == 1

    def test_from_dict_positions_key(self, conn):
        _insert_scout(conn, "U1")
        data = {"positions": [{"position": "Scribe", "dateStarted": "2023-01-01"}]}
        count = store_leadership(conn, "U1", data)
        assert count == 1
        row = conn.execute("SELECT position FROM scout_leadership WHERE scout_user_id='U1'").fetchone()
        assert row["position"] == "Scribe"

    def test_uses_title_field_as_fallback(self, conn):
        _insert_scout(conn, "U1")
        store_leadership(conn, "U1", [{"title": "Librarian"}])
        row = conn.execute("SELECT position FROM scout_leadership WHERE scout_user_id='U1'").fetchone()
        assert row["position"] == "Librarian"

    def test_defaults_to_unknown_when_no_position_field(self, conn):
        _insert_scout(conn, "U1")
        store_leadership(conn, "U1", [{}])
        row = conn.execute("SELECT position FROM scout_leadership WHERE scout_user_id='U1'").fetchone()
        assert row["position"] == "Unknown"

    def test_unapproved_stored_as_zero(self, conn):
        _insert_scout(conn, "U1")
        store_leadership(conn, "U1", [{"positionTitle": "SPL"}])
        row = conn.execute("SELECT approved FROM scout_leadership WHERE scout_user_id='U1'").fetchone()
        assert row["approved"] == 0

    def test_multiple_positions_returns_count(self, conn):
        _insert_scout(conn, "U1")
        positions = [
            {"positionTitle": "SPL"},
            {"positionTitle": "ASPL"},
            {"title": "Historian"},
        ]
        count = store_leadership(conn, "U1", positions)
        assert count == 3

    def test_start_date_field_recognized(self, conn):
        _insert_scout(conn, "U1")
        store_leadership(conn, "U1", [{"positionTitle": "SPL", "startDate": "2023-01-01"}])
        row = conn.execute("SELECT start_date FROM scout_leadership WHERE scout_user_id='U1'").fetchone()
        assert row["start_date"] == "2023-01-01"
