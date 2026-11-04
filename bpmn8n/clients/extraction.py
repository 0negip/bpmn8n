"""Fills a task's input from free text.

Two small models, each where it is reliable (measured, see docs/GUIDE.md):
- GLiNER2.5 (fastino/gliner2.5-small-v1) reads the *values written in the text*: names, codes,
  amounts, counts (str / int / float fields);
- Laya *judges* yes/no and pick-one fields (bool / Literal): GLiNER answered "yes" with 0.99
  confidence even to "Hi", Laya's calibrated P(yes) was 0.05.
The field description (or name) is what both models are asked; they run in parallel. Optionally
Laya double-checks each value GLiNER read, all in one forward pass, and vetoes the ones it is
nearly sure are wrong (off by default: on the evaluation set it lost right values and stopped
no wrong one, see reports/extraction_eval.md)."""
import re
import types
import typing
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from ..conf import settings
from pydantic import BaseModel

from .http import ModelClient, ServiceUnavailable
from .laya import LayaClient

NUMBER = re.compile(r"[-+]?\d[\d.,' ]*")
# Laya vetoes a value only when it is nearly sure it is not the one asked for: on the evaluation
# set a 0.2 cut lost 2 of 47 right values, a 0.5 cut lost 4 (reports/extraction_eval.md)
VETO_BELOW = 0.2
_parallel = ThreadPoolExecutor(max_workers=16, thread_name_prefix="extract")


def to_number(text):
    """First number in text, Italian or English notation: "1.299,50 €" and "1,299.50" -> 1299.5;
    "12,000" (3 digits after a single separator) is read as thousands."""
    match = NUMBER.search(text or "")
    if not match:
        return None
    raw = re.sub(r"[' ]", "", match.group()).rstrip(".,")
    if "." in raw and "," in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif raw.count(",") + raw.count(".") == 1 and len(re.split(r"[.,]", raw)[1]) != 3:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "").replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


class FieldSpec:
    """One Schema field: how it is asked (a GLiNER span or a Laya judgment) and converted back."""

    def __init__(self, name, field):
        self.name, self.required = name, field.is_required()
        self.description = field.description or field.title or name.replace("_", " ")
        kind = self._unwrap(field.annotation)
        self.choices = [str(c) for c in typing.get_args(kind)] if typing.get_origin(kind) is typing.Literal else None
        self.kind = "choice" if self.choices else kind.__name__ if kind in (bool, int, float) else "str"
        self.judged = self.kind in ("bool", "choice")

    @staticmethod
    def _unwrap(annotation):  # Optional[X] / X | None -> X
        if typing.get_origin(annotation) in (typing.Union, types.UnionType):
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            return args[0] if len(args) == 1 else annotation
        return annotation

    # --- span fields (GLiNER) ---
    @property
    def span_request(self):
        return {"name": self.name, "description": self.description}

    def verification(self, raw):
        """Laya yes/no question checking a value GLiNER read. At the same 0.5 cut this phrasing lost
        4 of 47 right values, 'is "X" the D?' lost 17 (reports/extraction_eval.md)."""
        return {"type": "noul",
                "instructions": f'Does the text say that the {self.description[0].lower()}{self.description[1:]} is "{raw}"?'}

    def from_span(self, text):
        if self.kind == "str":
            return text.strip()
        number = to_number(text)
        return None if number is None else round(number) if self.kind == "int" else number

    # --- judged fields (Laya) ---
    @property
    def question(self):
        if self.kind == "bool":
            return {"type": "noul", "instructions": self.description}
        return {"type": "choice", "instructions": self.description, "criteria": self.choices}

    def from_answer(self, answer):
        """(value, confidence) from a Laya answer."""
        if self.kind == "bool":
            p = answer["noul"]
            return p >= 0.5, max(p, 1 - p)
        return answer["choice"], answer.get("answer_confidence", answer.get("confidence", 0))


@lru_cache(maxsize=None)
def field_specs(schema: type[BaseModel]):
    return tuple(FieldSpec(name, field) for name, field in schema.model_fields.items())


class ExtractorError(ServiceUnavailable):
    pass


class Gliner(ModelClient):
    """The models server's /v1/extract (micro-batched GLiNER2.5)."""

    error = ExtractorError

    def __init__(self):
        super().__init__(settings.EXTRACTOR_URL, settings.MODELS_API_KEY, settings.LAYA_TIMEOUT,
                         settings.LAYA_BUSY_TIMEOUT)

    def spans(self, text, specs, threshold):
        """{field: (raw text, confidence)}"""
        found = self.call({"threshold": threshold,
                           "items": [{"text": text, "fields": [s.span_request for s in specs]}]})["results"][0]
        return {s.name: (found[s.name]["value"], found[s.name]["confidence"]) for s in specs if s.name in found}


class Extractor:
    """{field: {"value": typed value, "confidence", "verified"?}} for the fields of `schema` found
    in `text`. Fields below `threshold` (or that Laya does not confirm) are left out: their default
    applies, or validation reports them as missing."""

    def __init__(self):
        self.gliner, self.laya = Gliner(), LayaClient()

    def extract(self, schema, text, threshold=0.5, verify=False):
        specs = {s.name: s for s in field_specs(schema)}
        spans = [s for s in specs.values() if not s.judged]
        judged = [s for s in specs.values() if s.judged]
        read = _parallel.submit(self._read, text, spans, threshold, verify) if spans else None
        hits = self._judge(text, judged) if judged else {}
        hits |= read.result() if read else {}
        return {name: hit for name, hit in hits.items() if hit["value"] is not None and hit["confidence"] >= threshold}

    def _read(self, text, specs, threshold, verify):
        found = self.gliner.spans(text, specs, threshold)
        hits = {s.name: {"value": s.from_span(found[s.name][0]), "confidence": round(found[s.name][1], 4)}
                for s in specs if s.name in found}
        if verify and found:
            by_name = {s.name: s for s in specs}
            checks = self.laya.ask(text, {n: by_name[n].verification(raw) for n, (raw, _) in found.items()})
            for name, hit in hits.items():
                hit["verified"] = round(checks[name]["noul"], 4)
                if hit["verified"] < VETO_BELOW:  # Laya is nearly sure this is not the value asked for
                    hit["value"] = None
        return hits

    def _judge(self, text, specs):
        answers = self.laya.ask(text, {s.name: s.question for s in specs})
        hits = {}
        for s in specs:
            value, confidence = s.from_answer(answers[s.name])
            hits[s.name] = {"value": value, "confidence": round(confidence, 4)}
        return hits
