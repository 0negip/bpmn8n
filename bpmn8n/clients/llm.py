"""Chat models behind an API (admin → Settings → LLM providers). bpmn8n Studio uses them to
interview, design workflows and write activities. One interface, two protocols:
- OpenAI-compatible chat completions: Google Gemini, OpenAI, Mistral, Groq, OpenRouter, and local
  models served by LM Studio, Ollama, vLLM...;
- Anthropic's Messages API, through the official SDK."""
import ast
import json
import re

from .http import ModelClient, ServiceUnavailable


class LLMError(Exception):
    pass


FENCE = re.compile(r"```[\w+-]*[ \t]*\n(.*?)```", re.S)


def answer(text):
    """The reply without the reasoning models write first: <think>...</think>, often only its closing
    tag (Qwen, DeepSeek: the chat template opens it), whose braces would pass for the JSON."""
    return text.rpartition("</think>")[2]


def json_object(text):
    """The JSON object in a reply: in a ``` fence, or between the first { and the last }."""
    for candidate in (*FENCE.findall(text), text):
        try:
            value = json.loads(candidate[candidate.index("{"):candidate.rindex("}") + 1])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("not one valid JSON object")


def python_code(text):
    """The Python code in a reply: its longest ``` block, else all of it; it must parse."""
    code = max(FENCE.findall(text), key=len, default=text).strip()
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"the code does not parse: {e}") from e
    return code


class LLM:
    """`messages`: [{"role": "user" | "assistant", "content": text}]; `timeout`: seconds per reply."""

    def __init__(self, base_url, api_key, model, timeout=120):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    def complete(self, system, messages):
        """The reply's text."""
        raise NotImplementedError

    def ask(self, system, messages):
        """The reply as a JSON object."""
        return self._read(f"{system}\n\nReply with one JSON object and nothing else.", messages, json_object, "JSON")

    def text(self, system, messages):
        """The reply as plain text."""
        return answer(self.complete(system, messages)).strip()

    def code(self, system, messages):
        """The reply as Python code, in a fenced block: code inside a JSON string is the escaping small
        models get wrong."""
        return self._read(f"{system}\n\nReply with the code in one ```python block.", messages, python_code,
                          "Python code")

    def _read(self, system, messages, parse, what):
        """`parse` the reply. Models wrap it in prose now and then, and small local ones sometimes
        break it: they get one more try, told what was wrong."""
        for _ in range(2):
            text = answer(self.complete(system, messages))
            try:
                return parse(text)
            except ValueError as e:
                messages = [*messages, {"role": "assistant", "content": text},
                            {"role": "user", "content": f"That was not valid ({e}): reply again, as asked."}]
        raise LLMError(f"{self.model} did not reply with {what}: {text[:300]!r}")


class ChatEndpoint(ModelClient):
    def retryable(self, error):
        """A used-up quota (Google's free tier: 20 requests a day per model) does not clear in seconds."""
        return super().retryable(error) and "quota" not in str(error).lower()


class OpenAICompatible(LLM):
    def complete(self, system, messages):
        # an attempt that hangs (a provider out of capacity) is tried again, for up to three replies' time
        client = ChatEndpoint(f"{self.base_url}/chat/completions", self.api_key, self.timeout, 3 * self.timeout)
        try:
            reply = client.call({"model": self.model, "messages": [{"role": "system", "content": system}, *messages]})
        except ServiceUnavailable as e:
            raise LLMError(str(e)) from e
        return reply["choices"][0]["message"]["content"] or ""


class Anthropic(LLM):
    # models with server-side fallbacks and effort ("default" picks the fallback by refusal category)
    CURRENT = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")

    def complete(self, system, messages):
        import anthropic  # only this provider needs the SDK

        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        current = self.model in self.CURRENT
        try:
            response = client.beta.messages.create(
                model=self.model, max_tokens=16000, system=system, messages=messages,
                **({"output_config": {"effort": "high"}, "betas": ["server-side-fallback-2026-07-01"],
                    "fallbacks": "default"} if current else {}))
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e
        if response.stop_reason == "refusal":
            raise LLMError(f"{self.model} declined the request")
        return "".join(block.text for block in response.content if block.type == "text")


PROTOCOLS = {"openai": OpenAICompatible, "anthropic": Anthropic}
