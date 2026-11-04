"""BPMN User and Manual Tasks: the n8n node creates one per item and waits; people work them in
the inbox (/inbox/) or a system completes them through this API."""
from datetime import datetime
from typing import Any, Literal

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from ninja import Body, Router, Schema
from ninja.errors import HttpError

from ..clients.http import ServiceUnavailable
from ..core.cases import CaseData
from ..models import Cancelled, TransitionError, UserTask

router = Router(tags=["userTask"])


class FormField(Schema):
    name: str
    label: str = ""
    type: Literal["string", "number", "boolean"] = "string"


class UserTaskIn(Schema):
    kind: Literal["userTask", "manualTask"] = "userTask"
    title: str  # {{variable}} templates allowed, as in description and context
    description: str = ""
    lane: str = ""
    form: list[FormField] = []
    context: dict = {}  # shown to the person; empty: all the process variables
    resume_url: str
    items: list[dict[str, Any]] = [{}]  # the n8n items that reached the node: one task each


class UserTaskOut(Schema):
    id: int
    kind: str
    title: str
    activity: str
    description: str
    lane: str
    case_id: str
    form: list[FormField]
    context: dict
    status: str
    reason: str
    result: dict | None
    instance: int
    created: datetime
    completed: datetime | None


@router.post("", response={201: list[UserTaskOut]})
def create_user_tasks(request, data: UserTaskIn):
    """One task per item (BPMN multi-instance); the execution resumes when all are completed."""
    cases = [CaseData(request, item) for item in data.items or [{}]]
    instances = [dict(kind=data.kind, title=case.text(data.title), description=case.text(data.description),
                      lane=data.lane, form=[f.dict() for f in data.form], case_id=case.trace.case_id,
                      process=case.trace.process,
                      context=case.render(data.context) if data.context else case.variables)
                 for case in cases]
    return 201, UserTask.register(data.resume_url, cases[0].trace.activity or data.title, instances)


@router.get("", response=list[UserTaskOut])
def list_user_tasks(request, status: str | None = None, lane: str | None = None):
    """Waiting tasks (open or claimed), or those in `status`."""
    tasks = UserTask.objects.filter(status=status) if status else UserTask.objects.waiting()
    return tasks.filter(lane=lane) if lane is not None else tasks


@router.post("/{task_id}/complete", response=UserTaskOut)
def complete_user_task(request, task_id: int, result: dict = Body(...)):
    task = get_object_or_404(UserTask, pk=task_id)
    try:
        task.complete(None, task.clean_result(result))
    except ValidationError as e:
        raise HttpError(422, str(e.message_dict))
    except Cancelled as e:
        raise HttpError(410, str(e))
    except TransitionError as e:
        raise HttpError(409, str(e))
    except ServiceUnavailable as e:
        raise HttpError(502, f"n8n unreachable, task left open: {e}")
    return task
