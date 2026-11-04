"""JSON over HTTP for bpmn8n's outbound calls: n8n (resumes, its API) and the model servers (Laya, GLiNER).

Model calls reuse one keep-alive connection per thread and host: no connection set-up per
decision, and no burst of new connections (which Docker Desktop's host proxy sometimes left
hanging). They are pure functions, so ModelClient retries them while the server is busy or an
attempt times out."""
import http.client
import json
import threading
import time
from urllib.parse import urlsplit

BUSY = (429, 503)
STALE = (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError)


class ServiceUnavailable(Exception):
    """The remote service could not be reached or failed. `busy` means it asked us to retry;
    `timed_out` means no answer in time (the request may or may not have been processed)."""

    def __init__(self, message, status=None, retry_after=None, timed_out=False):
        super().__init__(message)
        self.status, self.retry_after, self.timed_out = status, retry_after, timed_out

    @property
    def busy(self):
        return self.status in BUSY


_pool = threading.local()  # (scheme, host) -> HTTPConnection, per thread


def _connection(parts, timeout, keep_alive):
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    if not keep_alive:
        return cls(parts.netloc, timeout=timeout)
    conns = _pool.__dict__.setdefault("conns", {})
    conn = conns.setdefault((parts.scheme, parts.netloc), None) or cls(parts.netloc, timeout=timeout)
    conns[(parts.scheme, parts.netloc)] = conn
    conn.timeout = timeout
    if conn.sock:
        conn.sock.settimeout(timeout)
    return conn


def _drop(parts):
    conn = getattr(_pool, "conns", {}).pop((parts.scheme, parts.netloc), None)
    if conn:
        conn.close()


def post_json(url, payload, headers=None, timeout=60, keep_alive=False):
    return request_json("POST", url, payload, headers, timeout, keep_alive)


def request_json(method, url, payload=None, headers=None, timeout=60, keep_alive=False):
    """Sends JSON (none when `payload` is None) and returns the decoded reply ({"text": ...} for a
    non-JSON 2xx body). keep_alive reuses a pooled connection: only for idempotent calls, because a
    request sent on a connection the server had just closed is sent again on a fresh one."""
    parts = urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", **(headers or {})}
    for attempt in (1, 2):
        conn = _connection(parts, timeout, keep_alive)
        try:
            conn.request(method, target, body, headers)
            response = conn.getresponse()
            data = response.read()
            break
        except STALE as e:
            _drop(parts)
            if not keep_alive or attempt == 2:
                raise ServiceUnavailable(f"{url}: {e!r}") from e
        except TimeoutError as e:
            _drop(parts)
            raise ServiceUnavailable(f"{url}: timed out", timed_out=True) from e
        except OSError as e:  # refused, unreachable, DNS
            _drop(parts)
            raise ServiceUnavailable(f"{url}: {e}") from e
        finally:
            if not keep_alive:
                conn.close()
    if response.status >= 400:
        retry_after = response.headers.get("Retry-After", "")
        raise ServiceUnavailable(f"{url}: HTTP {response.status} {data[:200]!r}", response.status,
                                 float(retry_after) if retry_after.isdigit() else None)
    try:
        return json.loads(data) if data else {}
    except json.JSONDecodeError:  # a 2xx with a text body still succeeded
        return {"text": data.decode(errors="replace")}


class ModelClient:
    """A model server endpoint. Retries while it is busy (503/429) or an attempt times out, for
    up to `busy_timeout` seconds, honouring Retry-After (one beyond that budget fails at once); then
    raises `error`."""

    MAX_BACKOFF = 5.0
    error = ServiceUnavailable

    def __init__(self, url, api_key="", timeout=10.0, busy_timeout=60.0):
        self.url, self.timeout, self.busy_timeout = url, timeout, busy_timeout
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def call(self, payload):
        deadline, attempt = time.monotonic() + self.busy_timeout, 0
        while True:
            try:
                return post_json(self.url, payload, self.headers, self.timeout, keep_alive=True)
            except ServiceUnavailable as e:
                wait = e.retry_after if e.retry_after is not None else min(0.5 * 2 ** attempt, self.MAX_BACKOFF)
                if not self.retryable(e) or time.monotonic() + wait > deadline:
                    state = "busy" if e.busy else "timed out" if e.timed_out else "unreachable"
                    raise self.error(f"{type(self).__name__} {state}: {e}", e.status, e.retry_after,
                                     e.timed_out) from e
                time.sleep(wait)
                attempt += 1

    def retryable(self, error):
        return error.busy or error.timed_out
