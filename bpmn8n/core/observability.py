"""Observability for tasks, gateways and waits. Every measured call becomes an Event row: with a
case id it is a step of the process-mining log, and all rows feed the metrics (SQL aggregates,
so they hold across worker processes). @profiled adds on-demand cProfile/tracemalloc."""
import cProfile
import io
import logging
import pstats
import threading
import time
import tracemalloc
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from urllib.parse import unquote

from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from ..models import Event

log = logging.getLogger("bpmn8n")

PROFILE_HEADER = "X-Bpmn8n-Profile"  # "1" -> run the call under Profiler
CASE_HEADER = "X-Bpmn8n-Case"  # n8n execution id = process instance (case) id
ACTIVITY_HEADER = "X-Bpmn8n-Activity"  # n8n node name = activity label
PROCESS_HEADER = "X-Bpmn8n-Process"  # n8n workflow name = the process the case belongs to


@dataclass(frozen=True)
class Trace:
    """Which process (workflow), case (execution) and activity (node) a request belongs to;
    empty for a direct API call. The n8n nodes URI-encode the values (names need not be ASCII)."""

    case_id: str = ""
    activity: str = ""
    process: str = ""

    @classmethod
    def of(cls, request):
        h = request.headers
        return cls(*(unquote(h.get(name, "")) for name in (CASE_HEADER, ACTIVITY_HEADER, PROCESS_HEADER)))

_profiles = {}  # endpoint -> last profile report (a debugging aid: kept per worker process)
_current = ContextVar("span", default=None)


class Span:
    """One measured call: start/end time, duration, error and optional profile report."""

    def __init__(self):
        self.started, self.error, self.profile, self.data = timezone.now(), None, None, {}
        self._t0 = time.perf_counter()

    def close(self):
        self.ended, self.ms = timezone.now(), (time.perf_counter() - self._t0) * 1000


@contextmanager
def measure(name, trace=Trace(), resource="system"):
    """Times the block and stores it as an Event (endpoint `name`) of `trace`, errors included."""
    span = Span()
    token = _current.set(span)
    try:
        yield span
    except Exception as e:
        span.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        _current.reset(token)
        span.close()
        Event.objects.create(case_id=trace.case_id, activity=trace.activity or name, process=trace.process,
                             endpoint=name, started=span.started,
                             ended=span.ended, duration_ms=span.ms, status="error" if span.error else "complete",
                             resource=resource, error=span.error or "", data=span.data)
        if span.profile:
            _profiles[name] = span.profile
        log.info("%s %.1fms%s", name, span.ms, f" ERROR {span.error}" if span.error else "")


def record(**data):
    """Adds `data` to the Event of the call being measured (see Event.data)."""
    if span := _current.get():
        span.data.update(data)


class Profiler:
    """cProfile + tracemalloc around one call. tracemalloc is process-global, so profiled
    calls run one at a time."""

    _lock = threading.Lock()

    def run(self, fn, *args, **kwargs):
        with self._lock:
            profiler = cProfile.Profile()
            tracemalloc.start()
            try:
                return profiler.runcall(fn, *args, **kwargs)
            finally:
                peak_kb = round(tracemalloc.get_traced_memory()[1] / 1024, 1)
                tracemalloc.stop()
                out = io.StringIO()
                pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(15)
                self.report = {"peak_kb": peak_kb, "cprofile": out.getvalue()}


def profiled(fn):
    """Measures every call (GET /api/metrics); with the X-Bpmn8n-Case header it is also a step
    of that case in the event log. `X-Bpmn8n-Profile: 1` also runs it under Profiler."""

    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        profiler = Profiler() if request.headers.get(PROFILE_HEADER) == "1" else None
        with measure(fn.__name__, Trace.of(request)) as span:
            if not profiler:
                return fn(request, *args, **kwargs)
            try:
                return profiler.run(fn, request, *args, **kwargs)
            finally:
                span.profile = profiler.report

    return wrapper


def metrics_snapshot():
    """Calls, errors and timings per endpoint, over every worker process."""
    rows = Event.objects.values("endpoint").annotate(
        calls=Count("id"), errors=Count("id", filter=Q(status="error")), avg_ms=Avg("duration_ms"),
        max_ms=Max("duration_ms"), last_at=Max("ended"))
    return {r["endpoint"]: {"calls": r["calls"], "errors": r["errors"], "avg_ms": round(r["avg_ms"], 2),
                            "max_ms": round(r["max_ms"], 2), "last_at": r["last_at"],
                            **({"last_profile": _profiles[r["endpoint"]]} if r["endpoint"] in _profiles else {})}
            for r in rows}
