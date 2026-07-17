"""Tests for scouting_db.multipart."""

import pytest

from scouting_db.multipart import parse_multipart


def _build_body(boundary, fields):
    """fields: list of (name, value) where value is str or {"filename": str, "content": bytes}."""
    lines = []
    for name, value in fields:
        lines.append(f"--{boundary}".encode())
        if isinstance(value, dict):
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{value["filename"]}"'.encode()
            )
            lines.append(b"Content-Type: text/csv")
            lines.append(b"")
            lines.append(value["content"])
        else:
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(value.encode())
    lines.append(f"--{boundary}--".encode())
    return b"\r\n".join(lines) + b"\r\n"


class TestParseMultipart:
    def test_parses_text_fields(self):
        body = _build_body("B1", [("username", "alice"), ("password", "s3cret")])
        fields = parse_multipart(body, "multipart/form-data; boundary=B1")
        assert fields["username"] == "alice"
        assert fields["password"] == "s3cret"

    def test_parses_file_field(self):
        body = _build_body("B2", [
            ("username", "alice"),
            ("csv_file", {"filename": "roster.csv", "content": b"User ID\nU1\n"}),
        ])
        fields = parse_multipart(body, "multipart/form-data; boundary=B2")
        assert fields["csv_file"]["filename"] == "roster.csv"
        assert fields["csv_file"]["content"] == b"User ID\nU1\n"

    def test_empty_file_field_has_empty_filename(self):
        body = _build_body("B3", [("csv_file", {"filename": "", "content": b""})])
        fields = parse_multipart(body, "multipart/form-data; boundary=B3")
        assert fields["csv_file"]["filename"] == ""

    def test_quoted_boundary_is_handled(self):
        body = _build_body("B4", [("username", "bob")])
        fields = parse_multipart(body, 'multipart/form-data; boundary="B4"')
        assert fields["username"] == "bob"

    def test_missing_boundary_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_multipart(b"irrelevant", "multipart/form-data")

    def test_non_multipart_content_type_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_multipart(b"irrelevant", "application/json")

    def test_file_content_with_leading_trailing_and_embedded_crlf(self):
        """Test that file content starting/ending with CRLF and containing CRLF\r\nCRLF is preserved."""
        content = b"\r\nline1\r\n\r\nline2\r\n"
        body = _build_body("B5", [("csv_file", {"filename": "data.csv", "content": content})])
        fields = parse_multipart(body, "multipart/form-data; boundary=B5")
        assert fields["csv_file"]["content"] == content
