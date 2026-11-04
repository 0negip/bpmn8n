"""bpmn8n models server: the small models bpmn8n uses, behind one HTTP/1.1 keep-alive API.

    POST /v1/systemone   Laya decisions (laya-serve compatible), on the Apple GPU via laya-mlx
    POST /v1/extract     GLiNER2.5 structured extraction: {"items": [{"text", "fields"}], "threshold"}
    POST /v1/ocr         text in a photo or scan, with macOS's Vision: {"image": base64 or data URL}
    GET  /health         {"status": "ok", "backends": [...]}

Concurrent extraction requests are micro-batched into one GLiNER forward pass (2.3x the
throughput of one-by-one on CPU, measured on an M5). GLiNER runs on CPU: for a 74M model the
Apple GPU was ~9x slower (175 vs 20 ms). Backends load lazily, so a host without laya-mlx (Linux)
serves extraction only, and only a Mac reads images (Vision is part of macOS).

    .venv-models/bin/python tools/models_server.py [--host 127.0.0.1] [--port 8001] [--no-laya]
"""
import argparse
import base64
import json
import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GLINER_MODEL = os.environ.get("GLINER_MODEL", "fastino/gliner2.5-small-v1")
MAX_BODY = 1_000_000
MAX_IMAGE = 20_000_000  # a phone photo, base64-encoded


class MicroBatcher:
    """Collects concurrent submissions for up to `max_wait` seconds (or `max_batch` items) and
    runs them through `run_batch(items) -> results` in one call; each caller gets its result."""

    def __init__(self, run_batch, max_batch=16, max_wait=0.004):
        self.run_batch, self.max_batch, self.max_wait = run_batch, max_batch, max_wait
        self._queue = deque()
        self._ready = threading.Condition()
        threading.Thread(target=self._loop, daemon=True, name="micro-batcher").start()

    def submit(self, item):
        future = Future()
        with self._ready:
            self._queue.append((item, future))
            self._ready.notify()
        return future.result()

    def _loop(self):
        while True:
            with self._ready:
                self._ready.wait_for(lambda: self._queue)
                deadline = time.monotonic() + self.max_wait
                while len(self._queue) < self.max_batch and (left := deadline - time.monotonic()) > 0:
                    self._ready.wait(left)
                batch = [self._queue.popleft() for _ in range(min(self.max_batch, len(self._queue)))]
            try:
                for (_, future), result in zip(batch, self.run_batch([item for item, _ in batch]), strict=True):
                    future.set_result(result)
            except Exception as e:  # one bad batch must not kill the loop: fail its callers
                for _, future in batch:
                    if not future.done():
                        future.set_exception(e)


class Gliner:
    """Schema-driven extraction. A request's `fields` are [{name, description, choices}] and are
    extracted as one record; results come back as {name: {"value", "confidence"}}."""

    RECORD = "record"

    def __init__(self):
        from gliner2 import AutoExtractor  # lazy: heavy import, and optional on some hosts

        self.model = AutoExtractor.from_pretrained(GLINER_MODEL, map_location="cpu")
        self.batcher = MicroBatcher(self._run)

    @lru_cache(maxsize=256)  # one schema object per distinct field list (per task, in practice)
    def schema(self, fields_json):
        schema = self.model.create_schema()
        structure = schema.structure(self.RECORD)
        for f in json.loads(fields_json):
            structure.field(f["name"], dtype="str", description=f.get("description") or None,
                            choices=f.get("choices") or None)
        return schema

    def _run(self, items):
        threshold = min(item["threshold"] for item in items)
        out = self.model.batch_extract([i["text"] for i in items], [self.schema(i["fields_json"]) for i in items],
                                       batch_size=len(items), threshold=threshold, include_confidence=True)
        return [self._flatten(result, item["threshold"]) for result, item in zip(out, items)]

    def _flatten(self, result, threshold):
        records = result.get(self.RECORD) or [{}]
        fields = {}
        for name, hit in records[0].items():
            hit = hit[0] if isinstance(hit, list) and hit else hit
            if isinstance(hit, dict) and hit.get("text") is not None and hit.get("confidence", 1) >= threshold:
                fields[name] = {"value": hit["text"], "confidence": round(hit.get("confidence", 1.0), 4)}
        return fields

    def extract(self, text, fields, threshold=0.5):
        fields_json = json.dumps(fields, sort_keys=True)
        return self.batcher.submit({"text": text, "fields_json": fields_json, "threshold": threshold})


class Laya:
    def __init__(self):
        import laya_mlx  # lazy: Apple Silicon only

        self.router = laya_mlx.Router(preload=True)
        self.lock = threading.Lock()  # the GPU runs one forward pass at a time anyway

    def predict(self, state, questions):
        with self.lock:
            result = self.router.predict(state, questions)
        return {"model": result["routing"]["model"], "answers": result["answers"]}


class Ocr:
    """Reads the text of a photographed or scanned document with Apple's Vision framework: on this Mac
    (Neural Engine), nothing to download, and the image never leaves the host. JPEG, PNG, HEIC, TIFF."""

    LANGUAGES = ["it-IT", "en-US", "fr-FR", "de-DE", "es-ES"]

    def __init__(self):
        import objc  # lazy: macOS only (pyobjc-framework-Vision)
        import Vision
        from Foundation import NSData

        self.objc, self.vision, self.nsdata = objc, Vision, NSData

    def read(self, image):
        """{"text": the lines top to bottom, "lines": [{"text", "confidence"}], "confidence": their mean}."""
        with self.objc.autorelease_pool():  # a long-running server: free each request's objects
            request = self.vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(0)  # accurate
            request.setRecognitionLanguages_(self.LANGUAGES)
            request.setUsesLanguageCorrection_(True)
            data = self.nsdata.dataWithBytes_length_(image, len(image))
            done = self.vision.VNImageRequestHandler.alloc().initWithData_options_(data, None) \
                .performRequests_error_([request], None)
            if not (done[0] if isinstance(done, tuple) else done):
                raise ValueError("not an image Vision can read (JPEG, PNG, HEIC, TIFF)")
            box = lambda r: r.boundingBox().origin  # noqa: E731 (Vision's origin is bottom-left)
            lines = [(r.topCandidates_(1)[0].string(), r.confidence())
                     for r in sorted(request.results(), key=lambda r: (-round(box(r).y, 2), box(r).x))]
        return {"text": "\n".join(text for text, _ in lines),
                "lines": [{"text": text, "confidence": round(c, 3)} for text, c in lines],
                "confidence": round(sum(c for _, c in lines) / len(lines), 3) if lines else 0.0}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: no connection storm when a burst of cases arrives
    backends = {}
    api_key = ""

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._reply(200, {"status": "ok", "backends": sorted(self.backends)})
        self._reply(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        limit = MAX_IMAGE if self.path == "/v1/ocr" else MAX_BODY
        body = self.rfile.read(length) if 0 < length <= limit else None  # always drain: keep-alive
        route = {"/v1/systemone": "laya", "/v1/extract": "gliner", "/v1/ocr": "ocr"}.get(self.path)
        if route not in self.backends:
            return self._reply(404, {"detail": f"no backend for {self.path}"})
        if self.api_key and self.headers.get("Authorization") != f"Bearer {self.api_key}":
            return self._reply(401, {"detail": "unauthorized"})
        if body is None:
            self.close_connection = bool(length)  # the unread body would corrupt the next request on it
            return self._reply(413 if length else 400, {"detail": f"body required, at most {limit // 1_000_000} MB"})
        try:
            request = json.loads(body)
            if route == "laya":
                return self._reply(200, self.backends["laya"].predict(request["state"], request["questions"]))
            if route == "ocr":
                image = base64.b64decode(request["image"].split("base64,")[-1])  # base64 or a data URL
                return self._reply(200, self.backends["ocr"].read(image))
            gliner, threshold = self.backends["gliner"], float(request.get("threshold", 0.5))
            return self._reply(200, {"results": [gliner.extract(i["text"], i["fields"], threshold)
                                                 for i in request["items"]]})
        except (ValueError, KeyError, TypeError) as e:
            self._reply(422, {"detail": f"{type(e).__name__}: {e}"})

    def log_message(self, *args):  # quiet; bpmn8n records timings itself
        pass


class Server(ThreadingHTTPServer):
    request_queue_size = 256  # socketserver's default backlog of 5 overflows on bursts
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="bpmn8n models server (Laya + GLiNER + OCR)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--no-laya", action="store_true", help="extraction only (hosts without laya-mlx)")
    args = parser.parse_args()
    Handler.api_key = os.environ.get("MODELS_API_KEY", "")
    Handler.backends["gliner"] = Gliner()
    if not args.no_laya:
        Handler.backends["laya"] = Laya()
    try:
        Handler.backends["ocr"] = Ocr()
    except ImportError:  # not a Mac: no OCR
        pass
    print(f"models server on http://{args.host}:{args.port} with {sorted(Handler.backends)}", flush=True)
    Server((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
