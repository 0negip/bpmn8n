"""Markdown as bpmn8n's pages show it: the README (the docs) and the texts an LLM writes (the brief)."""
import re

import markdown
from django.utils.html import escape

# a list right under a line of text, as GitHub reads it: Python-Markdown wants a blank line before it
LIST_AFTER_TEXT = re.compile(r"^((?![ \t]*(?:[-*+]|\d+\.)[ \t])[^\n|`].*)\n([ \t]*(?:[-*+]|\d+\.)[ \t])", re.M)
FENCES = re.compile(r"(^```.*?^```)", re.M | re.S)


def to_html(text, *, trusted=False, toc=False):
    """(html, table of contents). Untrusted text (an LLM's) has its HTML escaped first."""
    text = text if trusted else escape(text)
    text = "".join(part if part.startswith("```") else LIST_AFTER_TEXT.sub(r"\1\n\n\2", part)
                   for part in FENCES.split(text))  # code blocks stay as they are
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", *(["toc"] if toc else [])])
    return md.convert(text), getattr(md, "toc_tokens", [])
