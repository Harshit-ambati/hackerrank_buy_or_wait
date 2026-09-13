"""Local browser interface for the online Buy or Wait agent."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from buy_or_wait.ai_evidence import EvidenceAPIError, OnlineEvidenceResolver  # noqa: E402
from buy_or_wait.config import load_environment  # noqa: E402
from buy_or_wait.pipeline import run_pipeline  # noqa: E402
from buy_or_wait.runtime_logging import configure_logging  # noqa: E402


load_environment(PROJECT_ROOT / ".env")
LOGGER = configure_logging()


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Buy or Wait?</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #07140f; color: #edf8f2; }
    main { width: min(980px, calc(100% - 32px)); margin: 0 auto; padding: 52px 0; }
    .eyebrow { color: #83e6b2; font-size: 13px; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 12px 0 10px; font-size: clamp(42px, 8vw, 78px); line-height: .96; letter-spacing: -.055em; }
    .intro { color: #a9c2b5; max-width: 680px; font-size: 18px; line-height: 1.55; }
    .grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 18px; margin-top: 36px; }
    .card { background: #10231a; border: 1px solid #234532; border-radius: 20px; padding: 24px; box-shadow: 0 18px 45px #0006; }
    label { display: block; margin: 14px 0 7px; color: #bcd2c6; font-size: 13px; font-weight: 650; }
    input { width: 100%; padding: 13px 14px; border-radius: 11px; border: 1px solid #315b43; background: #091710; color: white; }
    button { width: 100%; margin-top: 20px; padding: 14px; border: 0; border-radius: 12px; background: #79efa9; color: #062012; font-weight: 800; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .status { display: flex; align-items: center; gap: 10px; margin-top: 18px; color: #bcd2c6; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: #6b7e73; }
    .dot.good { background: #79efa9; box-shadow: 0 0 16px #79efa999; }
    .dot.bad { background: #ff7c72; box-shadow: 0 0 16px #ff7c7299; }
    .metric { padding: 16px 0; border-bottom: 1px solid #234532; }
    .metric:last-child { border-bottom: 0; }
    .metric b { display: block; font-size: 27px; margin-top: 4px; }
    .muted { color: #91aa9c; font-size: 13px; }
    #result { margin-top: 18px; padding: 14px; border-radius: 12px; background: #091710; color: #bcd2c6; min-height: 52px; white-space: pre-wrap; }
    #result.error { color: #ffaaa4; border: 1px solid #7b322e; }
    #result.success { color: #9ef6c2; border: 1px solid #2b6a46; }
    @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body><main>
  <div class="eyebrow">Financial decision agent</div>
  <h1>Buy or wait?</h1>
  <p class="intro">Upload-ready decisions from structured profiles, cash-flow history, messages, documents, and seller payment plans. Gemini resolves unstructured evidence; deterministic rules protect essential commitments.</p>
  <section class="grid">
    <div class="card">
      <h2>Run a dataset</h2>
      <label for="dataset">Dataset folder</label>
      <input id="dataset" value="dataset" autocomplete="off">
      <label for="requests">Requests file</label>
      <input id="requests" value="requests.csv" autocomplete="off">
      <label for="output">Output file</label>
      <input id="output" value="output.csv" autocomplete="off">
      <button id="run">Run agent</button>
      <div id="result">Ready to validate configuration.</div>
    </div>
    <aside class="card">
      <h2>Runtime</h2>
      <div class="status"><span id="dot" class="dot"></span><span id="api">Checking Gemini…</span></div>
      <div class="metric"><span class="muted">Evidence mode</span><b>Online only</b></div>
      <div class="metric"><span class="muted">Provider</span><b>Gemini</b></div>
      <div class="metric"><span class="muted">Planner</span><b>Deterministic</b></div>
    </aside>
  </section>
</main>
<script>
  const result = document.querySelector('#result');
  const button = document.querySelector('#run');
  fetch('/api/status').then(r => r.json()).then(data => {
    document.querySelector('#api').textContent = data.gemini_configured ? 'Gemini configured' : 'Gemini key required';
    document.querySelector('#dot').className = 'dot ' + (data.gemini_configured ? 'good' : 'bad');
  });
  button.addEventListener('click', async () => {
    button.disabled = true;
    result.className = '';
    result.textContent = 'Reading evidence and evaluating requests…';
    try {
      const response = await fetch('/api/run', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          dataset: document.querySelector('#dataset').value,
          requests: document.querySelector('#requests').value,
          output: document.querySelector('#output').value
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Agent run failed');
      result.className = 'success';
      result.textContent = `Created ${data.output}\n${data.rows} decisions\n${JSON.stringify(data.statuses)}`;
    } catch (error) {
      result.className = 'error';
      result.textContent = error.message;
    } finally { button.disabled = false; }
  });
</script></body></html>"""


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, value: dict[str, object]) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            import os
            self._json(200, {"gemini_configured": bool(os.getenv("GEMINI_API_KEY"))})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/run":
            self._json(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 100_000:
                raise ValueError("Invalid request body size")
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            dataset = _resolve(str(payload.get("dataset", "dataset")))
            output = _resolve(str(payload.get("output", "output.csv")))
            requests_name = str(payload.get("requests", "requests.csv"))
            if Path(requests_name).name != requests_name:
                raise ValueError("Requests must be a filename inside the dataset folder")
            resolver = OnlineEvidenceResolver.from_environment()
            decisions = run_pipeline(
                dataset, requests_name, output,
                CODE_DIR / "evaluation" / "usage_report.md", resolver, LOGGER,
            )
            statuses = Counter(item.affordability_status for item in decisions)
            self._json(200, {
                "rows": len(decisions), "output": str(output), "statuses": dict(statuses)
            })
        except (EvidenceAPIError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, message: str, *args: object) -> None:
        LOGGER.debug("browser: %s", message % args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Buy or Wait browser interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOGGER.info("browser interface ready: http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
