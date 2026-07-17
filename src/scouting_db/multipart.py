"""Minimal multipart/form-data request body parser (stdlib only).

Written by hand because Python's cgi module (the historical way to parse
multipart bodies) is deprecated since 3.11 and removed in 3.13.
"""


def parse_multipart(body: bytes, content_type: str) -> dict:
    """Parse a multipart/form-data request body.

    Returns a dict mapping field name -> str value for text fields, or
    field name -> {"filename": str, "content": bytes} for file fields.
    Raises ValueError if content_type has no multipart/form-data boundary.
    """
    boundary = _extract_boundary(content_type)
    if boundary is None:
        raise ValueError("Content-Type is not multipart/form-data with a boundary")

    delimiter = b"--" + boundary
    fields = {}
    for part in body.split(delimiter):
        # Remove leading and trailing CRLF, but be careful not to strip content's newlines
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        headers = _parse_headers(header_blob)
        disposition = headers.get("content-disposition", "")
        name = _extract_param(disposition, "name")
        if name is None:
            continue
        filename = _extract_param(disposition, "filename")
        if filename is not None:
            fields[name] = {"filename": filename, "content": content}
        else:
            fields[name] = content.decode("utf-8")
    return fields


def _extract_boundary(content_type: str):
    if "multipart/form-data" not in content_type:
        return None
    for piece in content_type.split(";"):
        piece = piece.strip()
        if piece.startswith("boundary="):
            return piece[len("boundary="):].strip('"').encode("utf-8")
    return None


def _parse_headers(header_blob: bytes) -> dict:
    headers = {}
    for line in header_blob.split(b"\r\n"):
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.strip().lower().decode("utf-8")] = value.strip().decode("utf-8")
    return headers


def _extract_param(header_value: str, param_name: str):
    prefix = f"{param_name}="
    for piece in header_value.split(";"):
        piece = piece.strip()
        if piece.startswith(prefix):
            return piece[len(prefix):].strip('"')
    return None
