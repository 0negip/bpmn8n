"""bpmn8n Studio's interview: the LLM asks one question at a time until it can write the brief. The
research on the process's domain (research.py) comes first, from the person's description, and again
whenever the LLM needs to know more."""
from ..clients.llm import LLMError
from ..models import Settings
from .prompts import MAX_QUESTIONS, Prompts
from .research import Research


class Interview:
    def __init__(self, project, llm=None):
        self.project, self.llm = project, llm or Settings.llm_client()

    @property
    def answers(self):
        return sum(m["role"] == "user" for m in self.project.messages)

    def answer(self, text):
        """The person's answer (the first one describes the process): then the research on its domain, the
        first time, else the next question or the brief."""
        self.project.messages.append({"role": "user", "content": text})
        if self.answers == 1 and Research.allowed(self.project):
            return Research.start(self.project, f"{self.project.name}: {text}")  # it asks the first question
        self.ask()

    def ask(self):
        """The next question, the brief, or a research when the LLM must know more about the domain (the
        question comes when it ends). Returns what it did."""
        messages = self.project.messages
        last = self.answers > MAX_QUESTIONS  # enough: no more questions
        if last:
            messages = [*messages, {"role": "user", "content": "That is all I can tell you: write the brief now."}]
        can_research = not last and Research.allowed(self.project)
        reply = self.llm.ask(Prompts(self.project).interview(can_research), messages)
        if can_research and isinstance(topic := reply.get("research"), str) and topic.strip():
            Research.start(self.project, topic.strip())
            return f"research: {topic.strip()}"
        if reply.get("done") or not reply.get("question"):
            if not (brief := reply.get("brief") or reply.get("question")):
                raise LLMError(f"the interview ended without a brief: {reply}")  # nothing saved: answer again
            self.project.brief = brief
            self.project.messages.append({"role": "assistant", "content": brief})
        else:
            self.project.messages.append({"role": "assistant", "content": reply["question"]})
        self.project.save(update_fields=["messages", "brief", "updated"])
        return self.project.messages[-1]["content"]
