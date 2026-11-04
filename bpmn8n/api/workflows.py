"""Workflows checked before they run (bpmn8n/workflows/check.py)."""
from ninja import Body, Router

from ..workflows import check  # the module: check.py imports this package too

router = Router(tags=["workflows"])


@router.post("/check")
def check_workflow(request, workflow: dict = Body(...), start_data: str | None = None):
    """Checks an n8n workflow (as exported or built) of bpmn8n nodes: `errors` will fail when a case
    gets there, `warnings` are probably not what was meant. `start_data` (comma-separated): the fields
    of the data that starts a case; then every variable is checked."""
    fields = None if start_data is None else [f for f in start_data.split(",") if f]
    checked = check.WorkflowCheck(workflow, start_data=fields)
    return {"ok": not checked.errors, "problems": [p.as_dict() for p in checked.problems]}
