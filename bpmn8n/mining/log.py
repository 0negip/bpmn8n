"""The event log as PM4Py reads it: one row per activity of each case, from the Event table."""
from datetime import timedelta

import pandas as pd
import pm4py
from django.utils import timezone

from ..models import Event, MessageSubscription, UserTask

# PM4Py's (XES) column names
CASE, ACTIVITY, TIMESTAMP, PROCESS = "case:concept:name", "concept:name", "time:timestamp", "case:process"
COLUMNS = {"case_id": CASE, "activity": ACTIVITY, "started": TIMESTAMP, "ended": "end_timestamp", "process": PROCESS,
           "resource": "org:resource", "status": "status", "duration_ms": "duration_ms", "data": "data"}
SETTLE = timedelta(minutes=1)  # a case with nothing open and no new event for this long has ended


class EventLog:
    """A PM4Py-formatted DataFrame of events, sorted by case and start time."""

    def __init__(self, df):
        self.df = df

    @classmethod
    def load(cls, since=None, process=None):
        """The events of the cases started at/after `since`, of one process or all.
        ponytail: the log is held in memory (~1 GB per 5M events); past that, mine time windows."""
        events = Event.objects.cases(since)
        if process:  # "": events from before cases knew their process (named below)
            events = events.filter(process__in=(process, ""))
        df = pd.DataFrame.from_records(events.values_list(*COLUMNS).iterator(chunk_size=5000),
                                       columns=list(COLUMNS.values()))
        if df.empty:
            return cls(df)
        # events recorded before cases knew their process: the case's first activity names it
        first = df.groupby(CASE)[ACTIVITY].transform("first")
        df[PROCESS] = df[PROCESS].where(df[PROCESS] != "", first)
        if process:
            df = df[df[PROCESS] == process]
        for column in (TIMESTAMP, "end_timestamp"):
            df[column] = pd.to_datetime(df[column], utc=True)
        return cls(pm4py.format_dataframe(df, case_id=CASE, activity_key=ACTIVITY, timestamp_key=TIMESTAMP))

    def __len__(self):
        return 0 if self.df.empty else self.df[CASE].nunique()

    def processes(self):
        return {} if self.df.empty else {name: EventLog(df) for name, df in self.df.groupby(PROCESS, sort=False)}

    def where(self, cases):
        return EventLog(self.df[self.df[CASE].isin(cases)])

    def closed_cases(self, now=None):
        """Cases that have ended: nothing open (form, message) and no event for SETTLE."""
        if self.df.empty:
            return set()
        waiting = {*UserTask.objects.waiting().values_list("case_id", flat=True),
                   *MessageSubscription.objects.waiting().values_list("case_id", flat=True)}
        last = self.df.groupby(CASE)["end_timestamp"].max()
        return set(last[last < (now or timezone.now()) - SETTLE].index) - waiting

    def outcomes(self):
        """case -> how it ended: its last activity, "(error)" if that failed (e.g. an Error End Event)."""
        if self.df.empty:
            return pd.Series(dtype=object)
        last = self.df.groupby(CASE).last()
        return last[ACTIVITY] + last.status.map(lambda s: " (error)" if s == "error" else "")

    def by_workflow(self):
        """Cases grouped by the n8n workflow that ran them (case id "<workflow id>:<execution id>")."""
        if self.df.empty:
            return {}
        workflow = self.df[CASE].str.split(":").str[0]
        return {wid: EventLog(df) for wid, df in self.df.groupby(workflow, sort=False)}
