"""Process mining and training datasets. PM4Py loads on the first request, not in every worker at boot."""
import json
from datetime import datetime
from typing import Literal

from django.http import HttpResponse, StreamingHttpResponse
from ninja import Router

router = Router(tags=["process mining"])


@router.get("/processmining")
def get_process_mining(request, since: datetime | None = None, process: str | None = None):
    """Per process (n8n workflow), of the cases started at/after `since`: variants, directly-follows
    graph with branch probabilities, performance, conformance to the n8n workflow, decisions, drift."""
    from ..mining import Mining
    return Mining(since, process).report()


@router.get("/processmining/discovered.bpmn", response={200: None, 404: dict})
def get_discovered_model(request, process: str, since: datetime | None = None):
    """The process as it really runs, as BPMN 2.0 XML (inductive miner), for bpmn.io or Camunda."""
    from ..mining import Mining
    if not (analysis := Mining(since, process).processes.get(process)):
        return 404, {"detail": f"no cases of {process!r}"}
    return HttpResponse(analysis.discovered_bpmn(), content_type="application/xml")


@router.get("/datasets/card")
def get_training_card(request, since: datetime | None = None, process: str | None = None):
    """Before training: cases per split, label balance per target, warnings (rare or unseen labels, drift)."""
    from ..mining import Mining
    return Mining(since, process).card()


@router.get("/datasets/{name}")
def get_dataset(request, name: Literal["prefixes", "decisions"], split: Literal["train", "val", "test"] | None = None,
                since: datetime | None = None, process: str | None = None):
    """A training dataset as JSON Lines (see bpmn8n/mining/training.py), streamed."""
    from ..mining import Mining
    rows = getattr(Mining(since, process).training(), name)(split)
    return StreamingHttpResponse((json.dumps(row, default=str) + "\n" for row in rows), content_type="application/x-ndjson")
