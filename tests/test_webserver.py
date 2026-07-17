"""Tests for scouting_db.webserver."""

import http.client
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from scouting_db.api import ScoutingAPIError
from scouting_db.db import get_connection, init_db
from scouting_db.webserver import build_server


@pytest.fixture
def running_server(tmp_path):
    db_path = tmp_path / "scouting_troop.db"
    conn = get_connection(str(db_path))
    init_db(conn, troop_name="Test Troop")
    conn.close()

    httpd = build_server(str(db_path), port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], db_path
    finally:
        httpd.shutdown()
        thread.join()


class TestStaticRoutes:
    def test_root_serves_dashboard_html(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/html"
        assert b"<!DOCTYPE html>" in body or b"<html" in body

    def test_db_route_serves_current_db_bytes(self, running_server):
        port, db_path = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/scouting_troop.db")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert body == db_path.read_bytes()

    def test_db_route_404s_when_db_missing(self, tmp_path):
        httpd = build_server(str(tmp_path / "missing.db"), port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
            conn.request("GET", "/scouting_troop.db")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            assert resp.status == 404
        finally:
            httpd.shutdown()
            thread.join()

    def test_unknown_route_returns_404(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/nope")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 404


def _mock_response(data) -> MagicMock:
    """Create a MagicMock that acts as a urllib context-manager response."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def _post_multipart(port, fields):
    """fields: list of (name, value) where value is str or {"filename": str, "content": bytes}."""
    boundary = "----testboundary1234"
    lines = []
    for name, value in fields:
        lines.append(f"--{boundary}".encode())
        if isinstance(value, dict):
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{value["filename"]}"'.encode()
            )
            lines.append(b"")
            lines.append(value["content"])
        else:
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(value.encode())
    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines) + b"\r\n"

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST", "/api/sync", body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def _parse_sse_events(raw: bytes):
    text = raw.decode("utf-8")
    return [
        json.loads(chunk[len("data: "):])
        for chunk in text.split("\n\n")
        if chunk.startswith("data: ")
    ]


class TestSyncFormRoute:
    def test_sync_form_route_returns_html_form(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/sync")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert b"<form" in body
        assert b'name="username"' in body
        assert b'name="csv_file"' in body
        assert b'href="/"' in body


class TestSyncEndpoint:
    def test_auth_failure_streams_error_event(self, running_server):
        port, _ = running_server
        with patch(
            "scouting_db.sync_pipeline.authenticate",
            side_effect=ScoutingAPIError(401, "bad creds"),
        ):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "T"),
            ])
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/event-stream"
        events = _parse_sse_events(body)
        assert any(e["type"] == "error" for e in events)

    def test_malformed_multipart_returns_400(self, running_server):
        port, _ = running_server
        body = b'{"username": "u", "password": "p"}'
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST", "/api/sync", body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400

    def test_successful_sync_with_no_scouts_streams_complete_event(self, running_server):
        port, _ = running_server
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "Test Troop"),
            ])
        events = _parse_sse_events(body)
        assert events[-1]["type"] == "complete"

    def test_csv_upload_is_imported_before_sync(self, running_server):
        port, _ = running_server
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks
            _mock_response({"program": []}),  # get_youth_ranks for U1
            _mock_response([]),  # get_youth_merit_badges for U1
            _mock_response({}),  # get_leadership_history for U1
            _mock_response({}),  # get_person_profile for U1
        ]
        csv_content = b"User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n"
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "Test Troop"),
                ("skip_reqs", "on"),
                ("csv_file", {"filename": "roster.csv", "content": csv_content}),
            ])
        events = _parse_sse_events(body)
        messages = " ".join(e.get("message", "") for e in events)
        assert "1 Scouts imported" in messages
        assert events[-1]["type"] == "complete"

    def test_blank_troop_name_does_not_clobber_existing_name(self, running_server):
        """Regression test: the sync form's troop name field is only for a
        brand-new database. Leaving it blank when re-syncing an existing
        database (which already has a real troop name set) must not
        overwrite that name.
        """
        port, db_path = running_server
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", ""),
            ])
        events = _parse_sse_events(body)
        assert events[-1]["type"] == "complete"

        conn = get_connection(str(db_path))
        row = conn.execute("SELECT value FROM settings WHERE key = 'troop_name'").fetchone()
        conn.close()
        assert row["value"] == "Test Troop"
