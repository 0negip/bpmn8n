"""Throughput of a bpmn8n endpoint under concurrent clients. Requests carry no case, so they
are recorded as metrics only and stay out of the process-mining event log.

    .venv/bin/python tools/bench.py [--url http://localhost:8000/api/tasks/normalize_alert] [--clients 64] [--requests 2000]
"""
import argparse
import http.client
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

BODY = json.dumps({"source": "bench", "raw": "beacon from host-7 to 10.0.0.9"}).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/api/tasks/normalize_alert")
    parser.add_argument("--clients", type=int, default=64)
    parser.add_argument("--requests", type=int, default=2000)
    args = parser.parse_args()
    url, local = urlsplit(args.url), threading.local()

    def call(i):
        local.conn = getattr(local, "conn", None) or http.client.HTTPConnection(url.netloc, timeout=30)
        t0 = time.perf_counter()
        try:
            local.conn.request("POST", url.path, BODY, {"Content-Type": "application/json"})
            response = local.conn.getresponse()
            response.read()
            ok = response.status == 200
        except OSError:
            ok = False
        finally:
            local.conn.close()  # the server does not keep connections alive
            local.conn = None
        return ok, (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.clients) as pool:
        results = list(pool.map(call, range(args.requests)))
    elapsed = time.perf_counter() - t0
    ms = sorted(m for _, m in results)
    print(f"{args.requests / elapsed:.0f} req/s · errors {sum(not ok for ok, _ in results)} · "
          f"p50 {statistics.median(ms):.0f} ms · p95 {ms[int(len(ms) * 0.95)]:.0f} ms")


if __name__ == "__main__":
    main()
