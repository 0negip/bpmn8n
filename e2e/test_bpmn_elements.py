"""BPMN elements beyond tasks, run in n8n: event-based gateway (message race and timeout), error
end event, call activity (sub-process) and the inclusive join (n8n's Merge after an OR split)."""
import time
import uuid

from conftest import N8N, activities, wait_open
from projects.acme.processes import Workflow, library_lending


def on_loan_request(deploy, n8n_api, web_api, **timeouts):
    """Starts a library case whose book is on loan; returns its request id once it waits."""
    path, request_id = deploy(library_lending, **timeouts), f"REQ-{uuid.uuid4().hex[:6]}"
    assert n8n_api.post(f"{N8N}/webhook/{path}", data={"request_id": request_id, "reader": "r@acme.test",
                                                        "book": "The Name of the Rose"}).ok
    wait_open(web_api, "/api/messages/subscriptions", lambda s: s["correlation_key"] == request_id)
    return request_id


def test_event_based_gateway_decline_wins(deploy, n8n_api, web_api, event_log):
    known = set(event_log.cases())
    request_id = on_loan_request(deploy, n8n_api, web_api)
    assert web_api.post("/api/messages/decline-hold", data={"correlation_key": request_id}).ok
    rows = event_log.wait_for_case(known, until=lambda acts: acts[-1] == "Cancel Request")
    assert activities(rows) == ["Get Book Status", "Is Book Available?", "Send On-Loan Reply", "Wait for Reader", "Cancel Request"]


def test_event_based_gateway_times_out(deploy, n8n_api, web_api, event_log):
    """No answer: the gateway leaves on "timeout" (n8n's wait tracker resumes it, within ~1 min)."""
    known = set(event_log.cases())
    request_id = on_loan_request(deploy, n8n_api, web_api, answer_wait=(3, "seconds"))
    rows = event_log.wait_for_case(known, until=lambda acts: acts[-1] == "Cancel Request", timeout=150)
    assert activities(rows) == ["Get Book Status", "Is Book Available?", "Send On-Loan Reply", "Cancel Request"]
    late = web_api.post("/api/messages/hold-book", data={"correlation_key": request_id})
    assert late.status == 404  # expired: a late message cannot resume a case that moved on


def test_error_end_event_fails_the_case_and_is_logged(create_workflow, credential, n8n_api, event_log):
    path = f"e2e-error-{uuid.uuid4().hex[:6]}"
    wf = create_workflow(Workflow("e2e error end", credential).start("Start", path)
                         .error_end("Partner Failure", "PARTNER_FAILURE", "No acknowledgment within four days")
                         .flow("Start", "Partner Failure"), publish=True)
    known = set(event_log.cases())
    assert n8n_api.post(f"{N8N}/webhook/{path}", data={}).ok
    rows = event_log.wait_for_case(known, until=lambda acts: acts == ["Partner Failure"])
    assert (rows[0]["endpoint"], rows[0]["status"]) == ("event", "error")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        runs = n8n_api.get(f"/rest/executions?filter=%7B%22workflowId%22%3A%22{wf['id']}%22%7D").json()["data"]
        runs = runs.get("results", runs)
        if runs and runs[0]["status"] == "error":
            break
        time.sleep(0.5)
    assert runs[0]["status"] == "error"


def test_call_activity_runs_a_sub_process(create_workflow, credential, n8n_api):
    sub = create_workflow(Workflow("e2e sub-process", credential)
                          .add("When Called", "n8n-nodes-base.executeWorkflowTrigger", {"inputSource": "passthrough"},
                               bpmn=False, version=1.1)
                          .task("Normalize Alert", "scriptTask", "normalize_alert", source="sub")  # raw: by name
                          .flow("When Called", "Normalize Alert"), publish=True)
    path = f"e2e-call-{uuid.uuid4().hex[:6]}"
    create_workflow(Workflow("e2e call activity", credential).start("Start", path, respond="lastNode")
                    .add("Prepare", "n8n-nodes-base.set", {"mode": "raw", "jsonOutput": "={{ JSON.stringify({ raw: $json.body.raw }) }}"},
                         bpmn=False, version=3.4)
                    .call_activity("Normalize via Sub-Process", sub["id"])
                    .flow("Start", "Prepare", "Normalize via Sub-Process"), publish=True)
    items = n8n_api.post(f"{N8N}/webhook/{path}", data={"raw": "  beacon   from host-9 "}).json()
    assert items == [{"summary": "beacon from host-9", "hosts": ["host-9"], "ips": []}]


def test_inclusive_join_with_merge_waits_only_for_active_branches(create_workflow, credential, n8n_api):
    """OR split by conditions (2 of 3 branches true) -> n8n Merge with 3 inputs: it must run once,
    with the 2 tokens that exist, instead of waiting forever for the third (the lesson's deadlock).
    Holds with executionOrder v1 (n8n's editor default); legacy v0 ran the skipped branch too."""
    path = f"e2e-join-{uuid.uuid4().hex[:6]}"
    wf = (Workflow("e2e inclusive join", credential).start("Start", path, respond="lastNode")
          .condition_gateway("Which Checks?", "inclusive", {"a": "={{ true }}", "b": "={{ false }}", "c": "={{ true }}"})
          .task("Check A", "scriptTask", "normalize_alert", row=-1, source="a", raw="check a")
          .task("Check B", "scriptTask", "normalize_alert", same_column=True, source="b", raw="check b")
          .task("Check C", "scriptTask", "normalize_alert", row=1, same_column=True, source="c", raw="check c")
          .add("Join", "n8n-nodes-base.merge", {"numberInputs": 3}, bpmn=False, version=3.2)
          .flow("Start", "Which Checks?")
          .flow("Which Checks?", "Check A", output=0).flow("Which Checks?", "Check B", output=1)
          .flow("Which Checks?", "Check C", output=2))
    wf.connections["Check A"] = {"main": [[{"node": "Join", "type": "main", "index": 0}]]}
    wf.connections["Check B"] = {"main": [[{"node": "Join", "type": "main", "index": 1}]]}
    wf.connections["Check C"] = {"main": [[{"node": "Join", "type": "main", "index": 2}]]}
    create_workflow(wf, publish=True)
    r = n8n_api.post(f"{N8N}/webhook/{path}", data={}, timeout=30000)
    assert r.ok, r.text()
    assert sorted(i["summary"] for i in r.json()) == ["check a", "check c"]  # once, with both tokens
