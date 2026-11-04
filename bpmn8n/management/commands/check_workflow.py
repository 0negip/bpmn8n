"""Checks n8n workflow files (JSON, as exported) before they run; exits with 1 if any has errors.
Imports every app's tasks.py first, so a task that fails to import fails here too."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from bpmn8n.api import discover
from bpmn8n.workflows.check import WorkflowCheck


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=Path)
        parser.add_argument("--json", dest="as_json", action="store_true", help="{path: [problems]} on stdout")
        parser.add_argument("--start-data", type=lambda text: [f for f in text.split(",") if f],
                            help="the fields of the data that starts a case, comma-separated: checks every variable")

    def handle(self, paths, as_json, start_data, **options):
        if failed := discover():
            raise CommandError("tasks that do not import:\n" + "\n".join(f"{m}:\n{e}" for m, e in failed.items()))
        report = {str(path): WorkflowCheck(json.loads(path.read_text()), start_data=start_data).problems
                  for path in paths}
        if as_json:
            self.stdout.write(json.dumps({path: [p.as_dict() for p in problems] for path, problems in report.items()}))
        else:
            for path, problems in report.items():
                self.stdout.write(f"{path}: {'ok' if not problems else ''}")
                for p in problems:
                    self.stdout.write(f"  {p.level:7} {p.node or '(workflow)'}: {p.message}")
        if any(p.level == "error" for problems in report.values() for p in problems):
            raise CommandError("errors found")

