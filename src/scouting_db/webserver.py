"""Local web server: serves the dashboard and the synced database.

Binds to 127.0.0.1 only. Started via `uv run scouting serve`.
"""

import http.server
import json
import os
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from scouting_db.multipart import parse_multipart
from scouting_db.sync_pipeline import run_sync

DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "dashboard.html"

SYNC_FORM_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sync — Scouting Stats</title>
<style>
  :root {
    --gold: #FDB927; --gold-dark: #92400e;
    --olive: #4a5e28; --olive-dark: #344219; --bg: #e8ead8;
  }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         background: var(--bg); margin: 0; padding: 0; }
  header { background: var(--olive); color: white; padding: 16px 24px;
           font-size: 20px; font-weight: bold; }
  main { max-width: 480px; margin: 32px auto; padding: 0 16px; }
  label { display: block; margin: 16px 0 4px; font-weight: 600; color: var(--olive-dark); }
  input[type=text], input[type=password] {
    width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #ccc;
    border-radius: 4px; font-size: 14px;
  }
  .checkbox-row { display: flex; align-items: center; gap: 8px; margin-top: 16px; }
  .checkbox-row label { margin: 0; }
  button { margin-top: 24px; background: var(--gold); color: var(--olive-dark);
           border: none; border-radius: 4px; padding: 10px 20px; font-size: 15px;
           font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.6; cursor: default; }
  #log { white-space: pre-wrap; background: #fff; border: 1px solid #ccc;
         border-radius: 4px; padding: 12px; margin-top: 20px; min-height: 60px;
         font-family: ui-monospace, monospace; font-size: 13px; }
  #log a { color: var(--olive); font-weight: 600; }
  .back-link { display: inline-block; margin-top: 16px; color: var(--olive); font-weight: 600; text-decoration: none; }
  .back-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<header>Scouting Stats — Sync</header>
<main>
  <a href="/" class="back-link">&larr; Back to dashboard</a>
  <form id="sync-form">
    <label for="username">my.scouting.org username</label>
    <input type="text" id="username" name="username" required>

    <label for="password">Password</label>
    <input type="password" id="password" name="password" required>

    <label for="troop_name">Troop name (only needed the first time, for a brand-new database)</label>
    <input type="text" id="troop_name" name="troop_name" placeholder="e.g. Troop 42">

    <label for="csv_file">Roster CSV (optional)</label>
    <input type="file" id="csv_file" name="csv_file" accept=".csv">

    <div class="checkbox-row">
      <input type="checkbox" id="skip_reqs" name="skip_reqs">
      <label for="skip_reqs">Skip per-requirement detail (faster)</label>
    </div>

    <button type="submit" id="submit-btn">Sign In &amp; Sync</button>
  </form>
  <div id="log"></div>
</main>
<script>
document.getElementById('sync-form').addEventListener('submit', async function (e) {
  e.preventDefault();
  const log = document.getElementById('log');
  const btn = document.getElementById('submit-btn');
  log.textContent = '';
  btn.disabled = true;
  const formData = new FormData(e.target);
  try {
    const resp = await fetch('/api/sync', { method: 'POST', body: formData });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let done = false;
    while (!done) {
      const result = await reader.read();
      done = result.done;
      if (result.value) buf += decoder.decode(result.value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\\n\\n')) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!chunk.startsWith('data: ')) continue;
        const event = JSON.parse(chunk.slice(6));
        if (event.type === 'complete') {
          log.textContent += '\\n\\u2713 Done!\\n';
          const link = document.createElement('a');
          link.href = '/';
          link.textContent = 'Open dashboard \\u2192';
          log.appendChild(link);
        } else {
          log.textContent += (event.type === 'error' ? '\\u26a0 ' : '') + (event.message || '') + '\\n';
        }
      }
    }
  } catch (err) {
    log.textContent += '\\n\\u26a0 ' + err.message;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet console; errors still surface via HTTP status codes

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file(DASHBOARD_PATH, "text/html")
        elif path == "/scouting_troop.db":
            self._serve_file(Path(self.server.db_path), "application/octet-stream")
        elif path == "/sync":
            self._serve_html(SYNC_FORM_HTML)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path == "/api/sync":
            self._handle_sync()
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404, f"{path.name} not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_html(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_sync(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        try:
            fields = parse_multipart(body, content_type)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return

        username = fields.get("username", "")
        password = fields.get("password", "")
        troop_name = fields.get("troop_name") or None
        skip_reqs = fields.get("skip_reqs") == "on"

        csv_path = None
        tmp_csv_name = None
        csv_field = fields.get("csv_file")
        if isinstance(csv_field, dict) and csv_field.get("filename"):
            tmp_csv = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
            tmp_csv.write(csv_field["content"])
            tmp_csv.close()
            csv_path = tmp_csv.name
            tmp_csv_name = tmp_csv.name

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def on_progress(kind, data):
            payload = json.dumps({"type": kind, **data})
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        config_path = os.path.join(os.getcwd(), "config.json")
        try:
            run_sync(
                username, password, troop_name,
                self.server.db_path, config_path,
                csv_path=csv_path, skip_reqs=skip_reqs,
                on_progress=on_progress,
            )
        except Exception as exc:
            on_progress("error", {"message": f"Unexpected error: {exc}"})
        finally:
            if tmp_csv_name:
                os.unlink(tmp_csv_name)


def build_server(db_path: str, port: int = 8765) -> http.server.ThreadingHTTPServer:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.db_path = db_path
    return httpd


def serve(db_path: str, port: int = 8765, open_browser: bool = True) -> None:
    httpd = build_server(db_path, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Serving at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        httpd.server_close()
