"""Researches a bpmn8n Studio project's domain, then asks the interview's next question (what /studio/
starts): see bpmn8n/studio/research.py."""
from django.core.management.base import BaseCommand

from bpmn8n.api import discover
from bpmn8n.models import Project
from bpmn8n.studio.interview import Interview
from bpmn8n.studio.research import Research


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("topic", help="what to find out")

    def handle(self, slug, topic, **options):
        discover()  # the catalog of tasks the interview's prompt lists
        project = Project.objects.get(slug=slug)
        research = Research(project, topic)
        research.run(then=Interview(project, research.llm).ask)
