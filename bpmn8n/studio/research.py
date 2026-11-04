"""bpmn8n Studio's domain research. Before the interview's first question, and again whenever the
interview needs to know more, the LLM researches the process's domain on the web: it plans searches
(the laws and standards, the usual steps, roles and documents, the deadlines and amounts, what goes
wrong), reads the pages they find, looks for what is still missing, then writes notes with their
sources. The notes join the project's local context: the interview, the design and the code read them.

The searches go through SearXNG (SEARCH_URL) and name the domain, never the company or a person; the
pages are data the LLM summarises, never instructions. The research runs in its own process (manage.py
research_project), its steps are cards, and whatever fails the interview goes on with what is known."""
from contextlib import suppress

from ..clients import web
from ..models import Project, Settings
from .jobs import Board, background
from .prompts import Prompts

ROUNDS = 2  # search and read, look for what is missing, search and read again
QUERIES = 3  # per round
PER_QUERY = 2  # pages read per query
MAX_RESEARCH = 3  # per project: the first and two the interview asks for


def queries(reply):
    return [q.strip() for q in reply.get("queries", []) if isinstance(q, str) and q.strip()][:QUERIES]


class Research:
    def __init__(self, project, topic, llm=None):
        self.project, self.topic, self.llm = project, topic, llm or Settings.llm_client()
        self.prompts = Prompts(project)
        self.queries, self.done, self.seen, self.pages = [], [], set(), []  # pages: [{"title", "url", "notes"}]

    @staticmethod
    def allowed(project):
        return web.available() and project.research.get("count", 0) < MAX_RESEARCH

    @classmethod
    def start(cls, project, topic):
        """Runs it in its own process; the interview's next question comes when it ends."""
        project.status = Project.RESEARCH
        project.research = {**project.research, "count": project.research.get("count", 0) + 1}
        project.save(update_fields=["status", "research", "messages", "updated"])
        background("research_project", project, topic)

    def run(self, then=None):
        """The research, then `then` (the interview's next question, which returns its card's detail)."""
        board = Board(self.project)
        with suppress(Exception):  # the card says why: the interview goes on with what is known
            board.step("Plan the research", self.plan)
            for round_ in range(1, ROUNDS + 1):
                for query in self.queries:
                    with suppress(Exception):  # the card says why; the other searches go on
                        board.step(f"Search: {query}", lambda q=query: self.search(q))
                if round_ == ROUNDS or not self.pages:  # the last round, or the web gave nothing
                    break
                with suppress(Exception):  # the card says why; the notes come from what was read
                    board.step("Look for what is missing", self.more)
                if not self.queries:  # enough to go on
                    break
            board.step("Write the domain notes", self.write)
        self.project.status = Project.INTERVIEW
        self.project.save(update_fields=["status", "updated"])
        if then:
            with suppress(Exception):  # the card says why; the person can answer again
                board.step("Ask the next question", then)

    # --- steps ------------------------------------------------------------------------

    def plan(self):
        self.queries = queries(self.llm.ask(self.prompts.research_plan(self.topic, QUERIES),
                                            [{"role": "user", "content": "Plan the searches."}]))
        if not self.queries:
            raise ValueError("no search query")
        return "; ".join(self.queries)

    def search(self, query):
        """The query's first unread results, each page summarised for the research."""
        self.done.append(query)
        results = [r for r in web.search(query) if r["url"] not in self.seen][:PER_QUERY]
        read = []
        for r in results:
            self.seen.add(r["url"])
            try:
                text = web.page_text(r["url"])
            except web.WebError:
                continue
            notes = self.llm.text(self.prompts.research_read(self.topic, r, text or r["snippet"]),
                                  [{"role": "user", "content": "Write the notes."}]) if text or r["snippet"] else ""
            if notes and not notes.upper().startswith("NOTHING"):
                self.pages.append({"title": r["title"], "url": r["url"], "notes": notes})
                read.append(r["url"])
        return f"{len(read)} of {len(results)} pages useful" + "".join(f"\n{url}" for url in read)

    def more(self):
        self.queries = []  # none if it fails
        self.queries = queries(self.llm.ask(self.prompts.research_more(self.topic, self.done, self.digest(), QUERIES),
                                            [{"role": "user", "content": "What is still missing?"}]))
        return "; ".join(self.queries) or "enough to go on"

    def write(self):
        if not self.pages:
            raise web.WebError("no page could be read: the interview goes on without notes")
        notes = self.llm.text(self.prompts.research_notes(self.topic, self.digest()),
                              [{"role": "user", "content": "Write the domain notes."}])
        sources = [{"title": p["title"], "url": p["url"]} for p in self.pages]
        self.project.research = {**self.project.research, "topics": [
            *self.project.research_topics, {"topic": self.topic, "notes": notes, "sources": sources}]}
        self.project.save(update_fields=["research", "updated"])
        return f"{len(notes.split())} words from {len(sources)} sources"

    def digest(self):
        """What the pages said, numbered as their sources."""
        return "\n\n".join(f"[{i}] {p['title']} ({p['url']})\n{p['notes']}" for i, p in enumerate(self.pages, 1)) \
            or "nothing yet"
