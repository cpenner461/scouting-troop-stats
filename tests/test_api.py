"""Tests for scouting_db.api."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from scouting_db.api import ScoutingAPI, ScoutingAPIError, authenticate


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> MagicMock:
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


def _patch_urlopen(data: dict):
    return patch(
        "scouting_db.api.urllib.request.urlopen",
        return_value=_mock_response(data),
    )


# ── ScoutingAPIError ──────────────────────────────────────────────────────────


class TestScoutingAPIError:
    def test_attributes(self):
        err = ScoutingAPIError(404, "not found")
        assert err.status_code == 404
        assert err.message == "not found"

    def test_str_contains_status_code(self):
        err = ScoutingAPIError(401, "unauthorized")
        assert "401" in str(err)

    def test_is_exception(self):
        assert isinstance(ScoutingAPIError(0, ""), Exception)

    def test_zero_status_code(self):
        err = ScoutingAPIError(0, "No token")
        assert err.status_code == 0
        assert err.message == "No token"


# ── authenticate ──────────────────────────────────────────────────────────────


class TestAuthenticate:
    def test_success_returns_token_and_user_id(self):
        resp = {"token": "abc123", "account": {"userId": "U42"}}
        with _patch_urlopen(resp):
            token, user_id = authenticate("user@example.com", "password")
        assert token == "abc123"
        assert user_id == "U42"

    def test_http_error_raises_scoutingerror(self):
        with patch(
            "scouting_db.api.urllib.request.urlopen",
            side_effect=_http_error(401, "Unauthorized"),
        ):
            with pytest.raises(ScoutingAPIError) as exc_info:
                authenticate("user@example.com", "badpass")
        assert exc_info.value.status_code == 401

    def test_missing_token_raises_scoutingerror_status_zero(self):
        resp = {"account": {"userId": "U42"}}  # no token field
        with _patch_urlopen(resp):
            with pytest.raises(ScoutingAPIError) as exc_info:
                authenticate("user@example.com", "password")
        assert exc_info.value.status_code == 0

    def test_missing_account_returns_none_user_id(self):
        """token returned even when account key is absent."""
        resp = {"token": "tok"}
        with _patch_urlopen(resp):
            token, user_id = authenticate("u", "p")
        assert token == "tok"
        assert user_id is None

    def test_empty_account_dict_returns_none_user_id(self):
        resp = {"token": "tok", "account": {}}
        with _patch_urlopen(resp):
            token, user_id = authenticate("u", "p")
        assert token == "tok"
        assert user_id is None

    def test_username_with_spaces_is_percent_encoded(self):
        resp = {"token": "t", "account": {"userId": "1"}}
        with _patch_urlopen(resp) as mock_open:
            authenticate("user name", "pass")
        url = mock_open.call_args[0][0].full_url
        assert "user%20name" in url

    def test_post_method_used(self):
        resp = {"token": "t", "account": {"userId": "1"}}
        with _patch_urlopen(resp) as mock_open:
            authenticate("u", "p")
        req = mock_open.call_args[0][0]
        assert req.get_method() == "POST"

    def test_500_error_propagates_status_code(self):
        with patch(
            "scouting_db.api.urllib.request.urlopen",
            side_effect=_http_error(500, "Internal Server Error"),
        ):
            with pytest.raises(ScoutingAPIError) as exc_info:
                authenticate("u", "p")
        assert exc_info.value.status_code == 500


# ── ScoutingAPI._request ──────────────────────────────────────────────────────


class TestScoutingAPIRequest:
    def setup_method(self):
        self.api = ScoutingAPI(token="test-token")

    def test_get_returns_parsed_json(self):
        data = {"ranks": [{"id": 1, "name": "Scout"}]}
        with _patch_urlopen(data):
            result = self.api._request("/advancements/ranks")
        assert result == data

    def test_get_with_params_builds_query_string(self):
        with _patch_urlopen({}) as mock_open:
            self.api._request("/path", params={"foo": "bar", "baz": 42})
        url = mock_open.call_args[0][0].full_url
        assert "foo=bar" in url
        assert "baz=42" in url

    def test_base_url_prepended(self):
        with _patch_urlopen({}) as mock_open:
            self.api._request("/my/path")
        url = mock_open.call_args[0][0].full_url
        assert url.startswith("https://api.scouting.org/my/path")

    def test_auth_token_added_as_bearer(self):
        with _patch_urlopen({}) as mock_open:
            self.api._request("/path")
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer test-token"

    def test_no_auth_header_when_no_token(self):
        api = ScoutingAPI(token=None)
        with _patch_urlopen({}) as mock_open:
            api._request("/path")
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") is None

    def test_http_error_raises_scoutingerror(self):
        with patch(
            "scouting_db.api.urllib.request.urlopen",
            side_effect=_http_error(500, "Server Error"),
        ):
            with pytest.raises(ScoutingAPIError) as exc_info:
                self.api._request("/path")
        assert exc_info.value.status_code == 500

    def test_post_with_body_sends_json(self):
        with _patch_urlopen({}) as mock_open:
            self.api._request("/path", method="POST", body={"key": "value"})
        req = mock_open.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"
        assert json.loads(req.data) == {"key": "value"}

    def test_get_default_method(self):
        with _patch_urlopen({}) as mock_open:
            self.api._request("/path")
        req = mock_open.call_args[0][0]
        assert req.get_method() == "GET"

    def test_401_error_preserves_status_code(self):
        with patch(
            "scouting_db.api.urllib.request.urlopen",
            side_effect=_http_error(401, "Unauthorized"),
        ):
            with pytest.raises(ScoutingAPIError) as exc_info:
                self.api._request("/path")
        assert exc_info.value.status_code == 401


# ── ScoutingAPI endpoint URL construction ─────────────────────────────────────


class TestScoutingAPIEndpoints:
    def setup_method(self):
        self.api = ScoutingAPI(token="tok")

    def _get_url(self, fn, *args, **kwargs):
        with _patch_urlopen({}) as m:
            fn(*args, **kwargs)
        return m.call_args[0][0].full_url

    def test_get_ranks_default_params(self):
        url = self._get_url(self.api.get_ranks)
        assert "/advancements/ranks" in url
        assert "version=2" in url
        assert "status=Active" in url

    def test_get_ranks_with_program_id(self):
        url = self._get_url(self.api.get_ranks, program_id=2)
        assert "programId=2" in url

    def test_get_ranks_custom_version(self):
        url = self._get_url(self.api.get_ranks, version=3)
        assert "version=3" in url

    def test_get_rank_requirements_url(self):
        url = self._get_url(self.api.get_rank_requirements, 123)
        assert "/advancements/ranks/123/requirements" in url

    def test_get_youth_ranks_url(self):
        url = self._get_url(self.api.get_youth_ranks, "U99")
        assert "/advancements/v2/youth/U99/ranks" in url

    def test_get_youth_merit_badges_url(self):
        url = self._get_url(self.api.get_youth_merit_badges, "U99")
        assert "/advancements/v2/youth/U99/meritBadges" in url

    def test_get_youth_awards_url(self):
        url = self._get_url(self.api.get_youth_awards, "U99")
        assert "/advancements/v2/youth/U99/awards" in url

    def test_get_mb_requirements_url(self):
        url = self._get_url(self.api.get_mb_requirements, 55)
        assert "/advancements/meritBadges/55/requirements" in url

    def test_get_youth_mb_requirements_url(self):
        url = self._get_url(self.api.get_youth_mb_requirements, "U99", 55)
        assert "/advancements/v2/youth/U99/meritBadges/55/requirements" in url

    def test_get_youth_rank_requirements_url(self):
        url = self._get_url(self.api.get_youth_rank_requirements, "U99", 7)
        assert "/advancements/v2/youth/U99/ranks/7/requirements" in url

    def test_get_leadership_history_url(self):
        url = self._get_url(self.api.get_leadership_history, "U99")
        assert "/advancements/youth/U99/leadershipPositionHistory" in url

    def test_get_person_profile_url(self):
        url = self._get_url(self.api.get_person_profile, "U99")
        assert "/persons/v2/U99/personprofile" in url

    def test_validate_token_url(self):
        url = self._get_url(self.api.validate_token, "U99")
        assert "/advancements/v2/youth/U99/ranks" in url

    def test_validate_token_raises_on_401(self):
        with patch(
            "scouting_db.api.urllib.request.urlopen",
            side_effect=_http_error(401, "Unauthorized"),
        ):
            with pytest.raises(ScoutingAPIError) as exc_info:
                self.api.validate_token("U99")
        assert exc_info.value.status_code == 401
