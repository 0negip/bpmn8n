"""H4: the event log supports process mining. H5: the stack handles concurrent cases.

All 30 labelled tickets hit the published UC1 process at once; people complete the triage
tasks; then the mined process map (built with PM4Py) is checked against the dataset and the raw PM4Py DFG."""
import io
import json
import time
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import N8N, EventLog, delete_workflow, publish_workflow
from projects.acme.processes import ticket_triage

TICKETS = json.loads((Path(__file__).parent / "datasets" / "tickets.json").read_text())
TEAM_TASKS = {"Calculate Refund", "Open Bug Report", "Notify Sales", "Triage Ticket"}
REPORTS = Path(__file__).resolve().parent.parent / "reports"


def post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


@pytest.fixture(scope="module")
def burst(web_api, n8n_api, credential, laya_ready):
    """Starts every ticket concurrently; returns (new case rows, seconds until all completed)."""
    path = f"e2e-burst-{uuid.uuid4().hex[:6]}"
    wf = publish_workflow(n8n_api, ticket_triage(credential, path=path))

    log = EventLog(web_api)
    known = set(log.cases())
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    payloads = [{"customer": f"c{i}", "message": t["text"], "amount": 10, "duplicate_charge": False}
                for i, t in enumerate(TICKETS)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert set(pool.map(lambda p: post(f"{N8N}/webhook/{path}", p), payloads)) == {200}

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        for task in web_api.get("/api/usertasks").json():  # people triage what Laya was unsure about
            if task["activity"] == "Triage Ticket":
                web_api.post(f"/api/usertasks/{task['id']}/complete", data={"team": "sales"})
        new = {c: rows for c, rows in log.cases().items() if c not in known}
        if len(new) == len(TICKETS) and all(rows[-1]["activity"] in TEAM_TASKS for rows in new.values()):
            elapsed = time.monotonic() - t0
            break
        time.sleep(1)
    else:
        pytest.fail(f"only {len(new)} of {len(TICKETS)} cases completed")

    delete_workflow(n8n_api, wf)
    return new, elapsed, started


def test_h5_concurrent_cases_all_complete(burst):
    cases, elapsed, _ = burst
    assert len(cases) == len(TICKETS)
    for rows in cases.values():
        assert [r["activity"] for r in rows][:2] == ["Register Ticket", "Route Ticket"]
        assert all(r["status"] == "complete" for r in rows)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "load.json").write_text(json.dumps(
        {"cases": len(cases), "seconds": round(elapsed, 1), "cases_per_minute": round(len(cases) / elapsed * 60, 1)}))


def test_h4_mined_map_matches_what_happened(burst, web_api):
    cases, _, started = burst
    process = web_api.get("/api/processmining", params={"since": started}).json()[ticket_triage().name]
    assert process["cases"] == len(cases)
    routed = {e["to"]: e for e in process["directly_follows"] if e["from"] == "Route Ticket"}
    assert set(routed) <= TEAM_TASKS
    assert abs(sum(e["probability"] for e in routed.values()) - 1) < 0.01
    assert process["activities"]["Route Ticket"]["errors"] == 0
    if "Triage Ticket" in process["activities"]:  # human work is attributed to who did it
        assert set(process["activities"]["Triage Ticket"]["resources"]) == {"api"}
    (REPORTS / "process_map_ticket_triage.json").write_text(json.dumps(process, indent=2))


def test_h4_same_directly_follows_graph_as_pm4py(burst, web_api):
    pm4py = pytest.importorskip("pm4py")
    import pandas as pd

    log = pd.read_csv(io.StringIO(web_api.get("/api/eventlog.csv").text()), dtype={"case_id": str})
    log = pm4py.format_dataframe(log, case_id="case_id", activity_key="activity", timestamp_key="start_timestamp")
    dfg, starts, ends = pm4py.discover_dfg(log)
    ours = web_api.get("/api/processmining").json()
    mined = Counter()  # PM4Py mines the whole log: add up the edges of every process
    for process in ours.values():
        mined.update({(e["from"], e["to"]): e["cases"] for e in process["directly_follows"]})
    assert {k: v for k, v in mined.items() if "▶" not in k and "■" not in k} == dict(dfg)
    assert {k[1]: v for k, v in mined.items() if k[0] == "▶"} == dict(starts)
    assert {k[0]: v for k, v in mined.items() if k[1] == "■"} == dict(ends)
