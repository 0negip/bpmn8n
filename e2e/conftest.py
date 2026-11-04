"""Playwright fixtures for the running stack (`docker compose up`). Run: pytest e2e"""
import csv
import io
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # bpmn8n and projects/ (the ACME processes)

WEB = os.environ.get("BPMN8N_URL", "http://localhost:8000")
N8N = os.environ.get("N8N_URL", "http://localhost:5678")
# n8n owner of the local instance; n8n only validates the password policy when it is set
OWNER = {"email": os.environ.get("N8N_EMAIL", "owner@bpmn8n.example"), "password": os.environ.get("N8N_PASSWORD", "Bpmn8n-e2e-Owner1")}
MANAGER = {"username": "e2e-manager", "password": "Bpmn8n-e2e-Passw0rd", "lane": "managers"}
MANAGE = os.environ.get("BPMN8N_MANAGE", "docker compose exec -T web python manage.py").split()
LAYA_TIMEOUT = int(os.environ.get("LAYA_TIMEOUT", 1800))  # first boot downloads torch + weights


@pytest.fixture(scope="session", autouse=True)
def n8n_test_ids(playwright):
    playwright.selectors.set_test_id_attribute("data-test-id")


@pytest.fixture(scope="session")
def web_api(playwright):
    token = os.environ.get("BPMN8N_API_TOKEN")
    api = playwright.request.new_context(
        base_url=WEB, extra_http_headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    yield api
    api.dispose()


@pytest.fixture(scope="session")
def n8n_api(playwright):
    """Logged-in n8n REST session; creates the owner on a fresh instance."""
    api = playwright.request.new_context(base_url=N8N)
    api.post("/rest/owner/setup", data={**OWNER, "firstName": "E2E", "lastName": "Test"})  # 400 once done
    login = api.post("/rest/login", data={"emailOrLdapLoginId": OWNER["email"], "password": OWNER["password"]})
    assert login.ok, login.text()
    yield api
    api.dispose()


@pytest.fixture(scope="session")
def credential(n8n_api):
    data = {"baseUrl": "http://web:8000", "apiToken": os.environ.get("BPMN8N_API_TOKEN", "")}
    r = n8n_api.post("/rest/credentials", data={"name": f"bpmn8n e2e {uuid.uuid4().hex[:6]}", "type": "bpmn8nApi",
                                                 "data": data})
    assert r.ok, r.text()
    cred = r.json()["data"]
    yield {"id": cred["id"], "name": cred["name"]}
    n8n_api.delete(f"/rest/credentials/{cred['id']}")


@pytest.fixture
def n8n_page(browser, n8n_api):
    context = browser.new_context(base_url=N8N, storage_state=n8n_api.storage_state(),
                                  viewport={"width": 1400, "height": 900})
    yield context.new_page()
    context.close()


def publish_workflow(n8n_api, workflow, timeout=60):
    """Creates and activates a Workflow, waiting for n8n 2.x's async publication
    (webhooks registered). Returns the n8n workflow dict."""
    r = n8n_api.post("/rest/workflows", data=workflow.as_json())
    assert r.ok, r.text()
    wf = r.json()["data"]
    try:
        r = n8n_api.post(f"/rest/workflows/{wf['id']}/activate", data={"versionId": wf["versionId"]})
        assert r.ok, r.text()
        deadline = time.monotonic() + timeout
        while not (status := n8n_api.get(f"/rest/workflows/{wf['id']}/publication-status").json()["data"])["liveVersionId"]:
            assert status["status"] == "in_progress" and time.monotonic() < deadline, status
            time.sleep(0.5)
    except AssertionError:
        delete_workflow(n8n_api, wf)  # a workflow that failed to publish must not be left behind
        raise
    return wf


def delete_workflow(n8n_api, wf):
    """Stops its waiting executions first (a pending timeout would wake up a deleted workflow)."""
    runs = n8n_api.get(f"/rest/executions?filter=%7B%22workflowId%22%3A%22{wf['id']}%22%2C%22status%22%3A%5B%22waiting%22%5D%7D").json()
    for run in (runs.get("data") or {}).get("results", []):
        n8n_api.post(f"/rest/executions/{run['id']}/stop")
    n8n_api.post(f"/rest/workflows/{wf['id']}/deactivate")
    n8n_api.post(f"/rest/workflows/{wf['id']}/archive")
    n8n_api.delete(f"/rest/workflows/{wf['id']}")


@pytest.fixture
def create_workflow(n8n_api):
    """create_workflow(Workflow, publish=False) -> n8n workflow dict; deleted after the test."""
    created = []

    def create(workflow, publish=False):
        if publish:
            created.append(publish_workflow(n8n_api, workflow))
        else:
            r = n8n_api.post("/rest/workflows", data=workflow.as_json())
            assert r.ok, r.text()
            created.append(r.json()["data"])
        return created[-1]

    yield create
    for wf in created:
        delete_workflow(n8n_api, wf)


@pytest.fixture(scope="session")
def laya_ready(web_api):
    """Waits until bpmn8n can reach Laya (502 while laya-serve is still loading)."""
    body = {"question": "Is this a test?", "state": "ping", "branches": {"yes": "yes", "no": "no"}}
    deadline = time.monotonic() + LAYA_TIMEOUT
    while (status := web_api.post("/api/gateways/exclusive", data=body).status) == 502:
        if time.monotonic() > deadline:
            pytest.fail(f"Laya not ready after {LAYA_TIMEOUT}s (docker compose logs laya)")
        time.sleep(10)
    assert status == 200


@pytest.fixture(scope="session")
def manager():
    """A Django user in the `managers` lane (BPMN lane = Django group), created in the web container."""
    script = (
        "from django.contrib.auth.models import Group, User; "
        f"u, _ = User.objects.get_or_create(username={MANAGER['username']!r}); "
        f"u.set_password({MANAGER['password']!r}); u.save(); "
        f"u.groups.add(Group.objects.get_or_create(name={MANAGER['lane']!r})[0])"
    )
    subprocess.run([*MANAGE, "shell", "-c", script], check=True, capture_output=True)
    return MANAGER


class EventLog:
    """Reads bpmn8n's process-mining log: the test oracle for which path each case took."""

    def __init__(self, web_api):
        self.web_api = web_api

    def cases(self):
        rows = csv.DictReader(io.StringIO(self.web_api.get("/api/eventlog.csv").text()))
        cases = defaultdict(list)
        for row in sorted(rows, key=lambda r: r["start_timestamp"]):
            cases[row["case_id"]].append(row)
        return cases

    def wait_for_case(self, known, until, timeout=90):
        """Waits for a case not in `known` whose activity list satisfies `until`; returns its rows."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for case_id, rows in self.cases().items():
                if case_id not in known and until([r["activity"] for r in rows]):
                    return rows
            time.sleep(0.5)
        raise AssertionError(f"no new case satisfied the condition within {timeout}s: {dict(self.cases())}")


@pytest.fixture
def event_log(web_api):
    return EventLog(web_api)


@pytest.fixture
def deploy(create_workflow, credential):
    """deploy(builder, **kwargs) -> webhook path of a published copy of the process."""
    def run(builder, **kwargs):
        path = f"e2e-{uuid.uuid4().hex[:8]}"
        create_workflow(builder(credential, path=path, **kwargs), publish=True)
        return path
    return run


@pytest.fixture
def start_case(n8n_api, event_log):
    """start_case(path, payload, until) -> event-log rows of the case the request started."""
    def run(path, payload, until):
        known = set(event_log.cases())
        r = n8n_api.post(f"{N8N}/webhook/{path}", data=payload)
        assert r.ok, r.text()
        return event_log.wait_for_case(known, until)
    return run


def activities(rows):
    return [r["activity"] for r in rows]


def wait_open(web_api, url, match, timeout=60):
    """Polls a bpmn8n list endpoint until an open item satisfies `match`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = [x for x in web_api.get(url).json() if match(x)]
        if items:
            return items[-1]
        time.sleep(0.5)
    raise AssertionError(f"nothing open at {url} matched")


def wait_user_task(web_api, activity, timeout=60):
    return wait_open(web_api, "/api/usertasks", lambda t: t["activity"] == activity, timeout)
