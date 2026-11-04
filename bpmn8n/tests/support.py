"""What several test modules share: a fake Laya, a fake LLM, event fixtures and a local HTTP server."""
import json
from datetime import datetime, timedelta, timezone

from ..clients.llm import LLM
from ..models import Event


def fake_laya(self, state, questions):
    """Stands in for laya-serve: picks `billing`, and says yes to every noul whose text mentions refund."""
    answers = {}
    for qid, q in questions.items():
        if q["type"] == "choice":
            answers[qid] = {"type": "choice", "choice": "billing", "answer_confidence": 0.8}
        else:
            answers[qid] = {"type": "noul", "noul": 0.9 if "refund" in q["instructions"] else 0.1}
    return answers


class Text(str):
    """A FakeLLM reply given as it is (prose), not as code."""


class FakeLLM(LLM):
    """Replies with the given objects (as JSON), code (a str) or Text, in order, and remembers what it was asked."""

    def __init__(self, *replies):
        super().__init__("http://llm", "", "fake")
        self.replies, self.calls = list(replies), []

    def complete(self, system, messages):
        self.calls.append((system, messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Text):
            return f"<think>Let me see.</think>{reply}"
        return f"Sure! ```python\n{reply}\n```" if isinstance(reply, str) else f"Sure! ```json\n{json.dumps(reply)}\n```"


def add_events(*cases, at=None):
    """Events of closed cases: case id -> [(activity, minutes after `at`, duration ms, status, resource, data)]."""
    at = at or datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    Event.objects.bulk_create(
        Event(case_id=case_id, process=process, activity=a, endpoint=a.lower(), started=at + timedelta(minutes=m),
              ended=at + timedelta(minutes=m, milliseconds=ms), duration_ms=ms, status=st, resource=res, data=data)
        for case_id, process, steps in cases for a, m, ms, st, res, data in steps)


def step(activity, minute, ms=1000, status="complete", resource="system", data=None):
    return activity, minute, ms, status, resource, data or {}


class LocalServer:
    """A real HTTP/1.1 server on a free port; replies with `body`, counts connections and keeps the
    requests it got as (path, headers, body)."""

    def __init__(self, body=b'{"ok": true}', status=200):
        import http.server
        import threading

        outer = self
        self.connections, self.requests = 0, []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                outer.connections += 1
                super().setup()

            def do_POST(self):
                outer.requests.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
