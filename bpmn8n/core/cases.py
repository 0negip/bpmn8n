"""The case a request belongs to, with its process variables (rules in variables.py)."""
from ..models import Case
from .observability import Trace
from .variables import MISSING, Condition, bind, from_item, render


class CaseData:
    """The variables of the case a request belongs to, including the data of the n8n item that
    reached the node. A direct API call (no case) only has the data it brings."""

    def __init__(self, request, item=None):
        self.trace = Trace.of(request)
        brought = from_item(item or {})
        self.variables = self._merge(brought) if self.trace.case_id else brought

    def _merge(self, data):
        return Case.merge(self.trace.case_id, self.trace.process, data)

    def render(self, value):
        return render(value, self.variables)

    def text(self, value):
        """Like render, for a value that must be text: an unknown lone variable is ""."""
        rendered = self.render(value)
        return "" if rendered is MISSING else rendered

    def bind(self, schema, given, extracted=None):
        return bind(schema, given, self.variables, extracted)

    def holds(self, condition):
        return Condition.holds(condition, self.variables)

    def remember(self, data):
        """A step's result becomes process data."""
        if isinstance(data, dict) and data:
            self.variables = self._merge(data) if self.trace.case_id else {**self.variables, **data}
