"""Mines the event log into a folder: report.json (per process), <process>.bpmn (discovered model),
card.json and the training datasets <name>.<split>.jsonl. Same as the /api/processmining and
/api/datasets endpoints, without HTTP time limits."""
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from bpmn8n.mining import Mining, TrainingData


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--out", default="mining", type=Path)
        parser.add_argument("--since", type=datetime.fromisoformat)
        parser.add_argument("--process")

    def handle(self, out, since, process, **options):
        out.mkdir(parents=True, exist_ok=True)
        mining = Mining(since, process)
        self.write(out / "report.json", mining.report())
        for name, analysis in mining.processes.items():
            (out / f"{slugify(name)}.bpmn").write_text(analysis.discovered_bpmn())
        self.write(out / "card.json", mining.card())
        training = mining.training()
        for name in TrainingData.DATASETS:
            for split in ("train", "val", "test"):
                with open(out / f"{name}.{split}.jsonl", "w") as f:
                    f.writelines(json.dumps(row, default=str) + "\n" for row in getattr(training, name)(split))
        self.stdout.write(f"mined {len(mining.log)} cases of {len(mining.processes)} processes into {out}/")

    @staticmethod
    def write(path, data):
        path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
