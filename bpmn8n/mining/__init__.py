"""Process mining on bpmn8n's event log with PM4Py (AGPL-3.0: see README), from analysis to the
training data of a neural network. Mining(...).report() per process, .training() datasets."""
from .analysis import ProcessAnalysis
from .log import EventLog
from .model import WorkflowModel
from .training import TrainingData


class Mining:
    """One pass over the event log: the analysis of each process, then the training data from the
    closed cases that conform to their model. `models`: workflow id -> WorkflowModel, else fetched
    from n8n."""

    def __init__(self, since=None, process=None, models=None):
        self.log = EventLog.load(since, process)
        self.closed, models = self.log.closed_cases(), {} if models is None else models
        self.processes = {name: ProcessAnalysis(log, models, self.closed) for name, log in self.log.processes().items()}

    def report(self):
        return {name: analysis.as_dict() for name, analysis in self.processes.items()}

    def training(self):
        return TrainingData(self.log, set().union(*(a.deviating for a in self.processes.values())), self.closed)

    def card(self):
        """The training card, warned about processes that changed: train on cases after the change."""
        card = self.training().card()
        for name, analysis in self.processes.items():
            if changes := analysis.drift.get("change_points"):
                card["warnings"].append(f"{name} changed at {', '.join(changes)}: prefer cases after {changes[-1]}")
        return card


__all__ = ["EventLog", "Mining", "ProcessAnalysis", "TrainingData", "WorkflowModel"]
