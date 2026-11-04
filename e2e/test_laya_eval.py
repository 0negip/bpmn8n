"""H2: Laya decides BPMN gateways well enough for business processes, zero-shot.

Every gateway wording variant is run on a labeled dataset through bpmn8n's gateway API (the
production path: n8n node -> Django -> laya-serve). Results: reports/laya_eval.{json,md}."""
import json
import os
import statistics
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import pytest

from conftest import WEB
from projects.acme.processes import EXPENSE_PURPOSES, INCIDENT_ACTIONS, TICKET_TEAMS

DATA = Path(__file__).parent / "datasets"
REPORTS = Path(__file__).resolve().parent.parent / "reports"
THRESHOLDS = (0.0, 0.5, 0.7, 0.9)

VARIANTS = {
    "tickets": {
        "question": "Which team should handle this customer ticket?",
        "keywords": {"billing": "payments, invoices, charges, refunds, subscription fees",
                     "technical": "bugs, errors, crashes, outages, login or app problems",
                     "sales": "prices, quotes, buying new products, upgrades, demos"},
        "intents": TICKET_TEAMS,
    },
    "expenses": {
        "question": "What is the purpose of this expense?",
        "keywords": {"business": "client, meeting, conference, travel, work",
                     "personal": "family, friends, holiday, gifts, shopping"},
        "intents": EXPENSE_PURPOSES,
    },
    "incidents": {
        "suffix": ("Does this security alert", {
            "isolate_host": "show a compromised, infected or attacker-controlled computer?",
            "reset_credentials": "show stolen, leaked, phished or misused user passwords or accounts?",
            "notify_dpo": "show that personal or customer data was exposed, leaked or exfiltrated?"}),
        "full": ("", {
            "isolate_host": "Is a computer infected, compromised or controlled by an attacker?",
            "reset_credentials": "Were a user's password or account credentials stolen, phished or misused?",
            "notify_dpo": "Did personal data of customers or employees leave the company or become exposed?"}),
        "short": ("", INCIDENT_ACTIONS),
    },
}


def percentile(values, q):
    return statistics.quantiles(values, n=100)[q - 1] if len(values) > 1 else values[0]


class GatewayEvaluation:
    """Calls the gateways with a plain HTTP client: Playwright's request API adds ~50 ms of IPC
    per call, which would be measured as gateway latency."""

    def __init__(self, base_url=WEB, token=os.environ.get("BPMN8N_API_TOKEN")):
        self.base_url = base_url
        self.headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}

    def _call(self, kind, body):
        req = urllib.request.Request(f"{self.base_url}/api/gateways/{kind}", json.dumps(body).encode(), self.headers)
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=120) as r:
            reply = json.loads(r.read())
        return reply, (time.perf_counter() - t0) * 1000

    def exclusive(self, question, branches, items):
        rows = []
        for item in items:
            reply, ms = self._call("exclusive", {"question": question, "branches": branches, "state": item["text"]})
            (choice, confidence), = reply["scores"].items()
            rows.append({**item, "predicted": choice, "confidence": confidence, "ms": ms})
        by_lang, by_label = defaultdict(list), defaultdict(list)
        for r in rows:
            by_lang[r["lang"]].append(r["predicted"] == r["label"])
            by_label[r["label"]].append(r["predicted"] == r["label"])
        selective = {}
        for t in THRESHOLDS:
            accepted = [r for r in rows if r["confidence"] >= t]
            selective[t] = {"coverage": len(accepted) / len(rows),
                            "accuracy": sum(r["predicted"] == r["label"] for r in accepted) / len(accepted)
                            if accepted else None}
        return {
            "accuracy": sum(r["predicted"] == r["label"] for r in rows) / len(rows),
            "by_language": {k: sum(v) / len(v) for k, v in sorted(by_lang.items())},
            "recall_by_label": {k: sum(v) / len(v) for k, v in sorted(by_label.items())},
            "selective": selective,
            "latency_ms": {"p50": percentile([r["ms"] for r in rows], 50), "p95": percentile([r["ms"] for r in rows], 95)},
            "errors": [{"text": r["text"], "expected": r["label"], "got": r["predicted"],
                        "confidence": r["confidence"]} for r in rows if r["predicted"] != r["label"]],
        }

    def inclusive(self, question, branches, items, threshold=0.5):
        tp = fp = fn = exact = 0
        latencies, errors = [], []
        for item in items:
            reply, ms = self._call("inclusive", {"question": question, "branches": branches, "state": item["text"],
                                                 "min_confidence": threshold})
            latencies.append(ms)
            got, want = set(reply["branches"]), set(item["labels"])
            tp, fp, fn = tp + len(got & want), fp + len(got - want), fn + len(want - got)
            exact += got == want
            if got != want:
                errors.append({"text": item["text"], "expected": sorted(want), "got": sorted(got),
                               "scores": {k: round(v, 2) for k, v in reply["scores"].items()}})
        precision, recall = tp / ((tp + fp) or 1), tp / ((tp + fn) or 1)
        return {
            "exact_match": exact / len(items), "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / ((precision + recall) or 1),
            "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
            "errors": errors,
        }


@pytest.fixture(scope="module")
def results(laya_ready):
    ev, out = GatewayEvaluation(), {}
    for dataset in ("tickets", "expenses"):
        items = json.loads((DATA / f"{dataset}.json").read_text())
        v = VARIANTS[dataset]
        out[dataset] = {name: ev.exclusive(v["question"], v[name], items) for name in ("keywords", "intents")}
    items = json.loads((DATA / "incidents.json").read_text())
    out["incidents"] = {name: ev.inclusive(q, b, items) for name, (q, b) in VARIANTS["incidents"].items()}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "laya_eval.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    (REPORTS / "laya_eval.md").write_text(markdown(out))
    return out


def markdown(out):
    lines = ["# Laya gateway evaluation", ""]
    for dataset in ("tickets", "expenses"):
        lines += [f"## {dataset} (exclusive)", "", "| variant | accuracy | p50 ms | p95 ms | acc@0.7 | coverage@0.7 |",
                  "|---|---|---|---|---|---|"]
        for name, m in out[dataset].items():
            s = m["selective"][0.7]
            lines.append(f"| {name} | {m['accuracy']:.2f} | {m['latency_ms']['p50']:.0f} | {m['latency_ms']['p95']:.0f} "
                         f"| {s['accuracy'] or 0:.2f} | {s['coverage']:.2f} |")
        lines.append("")
    lines += ["## incidents (inclusive, threshold 0.5)", "", "| variant | exact match | precision | recall | F1 |",
              "|---|---|---|---|---|"]
    for name, m in out["incidents"].items():
        lines.append(f"| {name} | {m['exact_match']:.2f} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} |")
    return "\n".join(lines) + "\n"


def test_h2a_ticket_routing_is_accurate(results):
    assert results["tickets"]["intents"]["accuracy"] >= 0.85, results["tickets"]["intents"]["errors"]


def test_h2a_expense_screening_is_accurate(results):
    assert results["expenses"]["intents"]["accuracy"] >= 0.85, results["expenses"]["intents"]["errors"]


def test_h2b_intent_descriptions_beat_keyword_lists(results):
    for dataset in ("tickets", "expenses"):
        assert results[dataset]["intents"]["accuracy"] >= results[dataset]["keywords"]["accuracy"], dataset


def test_h2c_short_yes_no_questions_work_best(results):
    f1 = {name: m["f1"] for name, m in results["incidents"].items()}
    assert f1["short"] == max(f1.values()), f1


def test_h2d_confidence_is_useful_for_abstention(results):
    """Answers above 0.7 confidence are more accurate than all answers: low confidence -> person."""
    for dataset in ("tickets", "expenses"):
        m = results[dataset]["intents"]
        assert m["selective"][0.7]["accuracy"] >= m["accuracy"], (dataset, m["selective"])
