"""Review server — stdlib only, servable over Tailscale.

Web rather than CLI on purpose. `review_tags.py` and `review_edges.py` are dead in
guru not because the practice stopped but because the web tool over Tailscale from
other devices is easier; a CLI grader would repeat the mistake that killed them.

No framework, no Node, no build step: `http.server` plus one static page. DESIGN §6
asks for a thin runtime, and a grading queue that needs `npm install` is a grading
queue that rots.

    python -m claimbase review [--port 8760] [--host 0.0.0.0]
"""

from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .queue import Decision, DecisionLog, Item, sample_segments, to_gold_jsonl

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parent.parent.parent.parent


class State:
    """Items are regenerated from the same seed each start, so ids are stable and a
    part-finished session resumes rather than reshuffling."""

    def __init__(self, limit: int, log_path: Path) -> None:
        self.items: dict[str, Item] = {}
        self.order: list[str] = []
        self.log = DecisionLog(log_path)
        for it in sample_segments(limit):
            self.items[it.id] = it
            self.order.append(it.id)

    def pending(self) -> list[Item]:
        done = self.log.decided_ids()
        return [self.items[i] for i in self.order if i not in done]

    def progress(self) -> dict:
        done = len(self.log.decided_ids())
        return {"done": done, "total": len(self.order), "pending": len(self.order) - done}


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def log_message(self, *a) -> None:  # quiet; the terminal is for progress
            pass

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/queue"):
                self._json(
                    {
                        "items": [asdict(i) for i in state.pending()[:50]],
                        "progress": state.progress(),
                        "kinds": list(__import__("claimbase.review.queue", fromlist=["KINDS"]).KINDS),
                    }
                )
            elif self.path.startswith("/api/progress"):
                self._json(state.progress())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/decision":
                d = Decision(
                    item_id=body["item_id"],
                    verdict=body.get("verdict", "graded"),
                    payload=body.get("payload", {}),
                )
                state.log.append(d)
                self._json({"ok": True, "progress": state.progress()})
            elif self.path == "/api/export":
                out = ROOT / "eval" / "gold_extract.jsonl"
                n = to_gold_jsonl(state.log, state.items, out)
                self._json({"ok": True, "written": n, "path": str(out)})
            else:
                self._json({"error": "not found"}, 404)

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8760, limit: int = 60) -> int:
    log_path = ROOT / "eval" / "decisions.jsonl"
    state = State(limit, log_path)
    p = state.progress()
    print(f"  review queue: {p['pending']} pending of {p['total']}")
    print(f"  decisions →  {log_path}")
    print(f"  http://localhost:{port}/   (bind {host} — reachable over Tailscale)")
    ThreadingHTTPServer((host, port), make_handler(state)).serve_forever()
    return 0
