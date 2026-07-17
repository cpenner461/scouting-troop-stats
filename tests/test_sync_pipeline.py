"""Tests for scouting_db.sync_pipeline."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from scouting_db.api import ScoutingAPIError
from scouting_db.db import get_connection
from scouting_db.sync_pipeline import run_sync


def _mock_response(data) -> MagicMock:
    """Create a MagicMock that acts as a urllib context-manager response."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def _http_error(code: int, body: str = "error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.com", code, "HTTP Error", MagicMock(), io.BytesIO(body.encode())
    )


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, data):
        self.calls.append((kind, data))


class TestRunSyncAuthFailure:
    def test_bad_credentials_emits_error_and_returns_false(self, tmp_path):
        recorder = _Recorder()
        with patch(
            "scouting_db.sync_pipeline.authenticate",
            side_effect=ScoutingAPIError(401, "bad creds"),
        ):
            result = run_sync(
                "user", "wrongpass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                on_progress=recorder,
            )
        assert result is False
        kinds = [k for k, _ in recorder.calls]
        assert "error" in kinds
        assert not (tmp_path / "config.json").exists()


class TestRunSyncNoScouts:
    def test_no_scouts_and_no_csv_completes_with_tip(self, tmp_path):
        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                on_progress=recorder,
            )
        assert result is True
        assert (tmp_path / "config.json").exists()
        config = json.loads((tmp_path / "config.json").read_text())
        assert config["token"] == "tok"
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "No Scouts" in messages
        assert any(kind == "complete" for kind, _ in recorder.calls)


class TestRunSyncWithRoster:
    def test_csv_import_then_sync_completes(self, tmp_path):
        csv_path = tmp_path / "roster.csv"
        csv_path.write_text("User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n")

        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
            _mock_response({"program": []}),  # get_youth_ranks for U1
            _mock_response([]),  # get_youth_merit_badges for U1
            _mock_response({}),  # get_leadership_history for U1
            _mock_response({}),  # get_person_profile for U1
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                csv_path=str(csv_path), skip_reqs=True,
                on_progress=recorder,
            )
        assert result is True
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "1 Scouts imported" in messages
        assert any(kind == "complete" for kind, _ in recorder.calls)


class TestRunSyncRankRequirementVersionMismatch:
    def test_fetches_matching_version_and_stores_completion_without_fk_error(self, tmp_path):
        """Regression test: BSA revises rank requirement text over time, so
        requirement ids from the "current" definitions endpoint can be
        entirely disjoint from the ids a Scout's in-progress rank actually
        references (e.g. Eagle Scout 2026 vs. 2022 versions). Without passing
        the Scout's versionId through to get_rank_requirements, storing the
        per-scout completion violates the requirements(id) foreign key.
        """
        csv_path = tmp_path / "roster.csv"
        csv_path.write_text("User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n")

        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
            _mock_response({  # get_youth_ranks for U1: in-progress Eagle, older version
                "program": [{
                    "programId": 2,
                    "ranks": [{"id": 7, "name": "Eagle Scout", "versionId": 73}],
                }],
            }),
            _mock_response({"requirements": [{"id": 1508, "requirementNumber": "1"}]}),  # get_rank_requirements(7, versionId=73)
            _mock_response({"requirements": [{"id": 1508, "dateCompleted": None}]}),  # get_youth_rank_requirements(U1, 7)
            _mock_response([]),  # get_youth_merit_badges for U1
            _mock_response({}),  # get_leadership_history for U1
            _mock_response({}),  # get_person_profile for U1
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses) as mock_open:
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                csv_path=str(csv_path), skip_reqs=False,
                on_progress=recorder,
            )

        assert result is True
        assert any(kind == "complete" for kind, _ in recorder.calls)
        assert not any(kind == "error" for kind, _ in recorder.calls)

        rank_reqs_url = mock_open.call_args_list[3][0][0].full_url
        assert "/advancements/ranks/7/requirements" in rank_reqs_url
        assert "versionId=73" in rank_reqs_url

        conn = get_connection(str(tmp_path / "t.db"))
        row = conn.execute(
            "SELECT completed FROM scout_requirement_completions "
            "WHERE scout_user_id = 'U1' AND requirement_id = 1508"
        ).fetchone()
        assert row is not None
        conn.close()


class TestRunSyncTokenExpiresMidSync:
    def test_401_during_scout_sync_emits_error_and_stops(self, tmp_path):
        csv_path = tmp_path / "roster.csv"
        csv_path.write_text("User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n")

        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
            _http_error(401, "expired"),  # get_youth_ranks for U1 -> 401
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                csv_path=str(csv_path), skip_reqs=True,
                on_progress=recorder,
            )
        assert result is False
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "Token expired" in messages
