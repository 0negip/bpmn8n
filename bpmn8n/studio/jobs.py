"""bpmn8n Studio's jobs, the domain research and the build: each runs in its own process (it outlives the
request and any web worker restart) and shows its steps as cards (the kanban)."""
import subprocess
import sys
import threading
import time
from pathlib import Path

from django.conf import settings as django_settings
from django.utils import timezone

from ..models import Card, Project

ROOT = Path(django_settings.BASE_DIR)


class Skip(Exception):
    """An optional step that cannot run here; the detail says what to do instead."""


def background(command, project, *args):
    """manage.py <command> <slug> <args> in its own process, its output appended to .logs/studio-<slug>.log."""
    (ROOT / ".logs").mkdir(exist_ok=True)
    log = open(ROOT / ".logs" / f"studio-{project.slug}.log", "a")  # noqa: SIM115 (the child owns it)
    subprocess.Popen([sys.executable, "manage.py", command, project.slug, *args], cwd=ROOT, stdout=log,
                     stderr=subprocess.STDOUT, start_new_session=True)


def heartbeat(project, every=30):
    """While the job's process lives, it says so: Project.settle ends a job that went quiet (killed, or
    its container restarted), which would otherwise stay busy for ever."""
    def beat():
        while True:
            time.sleep(every)
            Project.objects.filter(pk=project.pk).update(updated=timezone.now())

    threading.Thread(target=beat, daemon=True).start()


class Board:
    """A job's cards, in place of the previous job's: each step is a card, to do, in progress, then done,
    skipped or failed, with what it did or why it failed."""

    def __init__(self, project):
        project.cards.all().delete()
        self.project, self.positions = project, iter(range(0, 100_000, 10))

    def step(self, title, do):
        """Runs `do`, which returns the card's detail; a failure fails the card and is raised."""
        card = Card.objects.create(project=self.project, title=title, position=next(self.positions), status=Card.DOING)
        try:
            detail = do() or ""
        except Skip as e:
            return card.move(Card.SKIPPED, str(e))
        except Exception as e:
            card.move(Card.FAILED, f"{type(e).__name__}: {e}")
            raise
        card.move(Card.DONE, detail)
