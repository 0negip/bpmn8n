"""Imports a CSV event log (case_id, activity, endpoint, start_timestamp, end_timestamp, status,
resource): bpmn8n's own export, an older file-based log, or a log from another system."""
import csv
from datetime import datetime

from django.core.management.base import BaseCommand

from bpmn8n.models import Event


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, path, **options):
        with open(path, newline="") as f:
            events = [self.event(row) for row in csv.DictReader(f) if row.get("case_id")]
        Event.objects.bulk_create(events, batch_size=2000)
        self.stdout.write(f"imported {len(events)} events")

    @staticmethod
    def event(row):
        started, ended = (datetime.fromisoformat(row[k]) for k in ("start_timestamp", "end_timestamp"))
        return Event(case_id=row["case_id"], activity=row["activity"], endpoint=row.get("endpoint") or row["activity"],
                     started=started, ended=ended, duration_ms=(ended - started).total_seconds() * 1000,
                     status=row.get("status") or "complete", resource=row.get("resource") or "system")
