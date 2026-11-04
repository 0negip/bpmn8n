"""bpmn8n's own activities: the LLM agent's prompt (the workflow builder's llm_agent step) and OCR."""
from ninja import Schema
from pydantic import Field

from .api import task
from .api.errors import upstream
from .clients.http import ModelClient
from .conf import settings


class PromptInput(Schema):
    prompt: str = Field(description="What the LLM agent is asked, with the {{variables}} it needs filled in")


class PromptResult(Schema):
    prompt: str = Field(description="The prompt as the LLM agent receives it")


@task("scriptTask")
def compose_prompt(request, data: PromptInput) -> PromptResult:
    """Fills an LLM agent's prompt with the case's variables (the llm_agent step's first node): only the
    ones it names reach the LLM, and the event log keeps what it was sent."""
    return PromptResult(prompt=data.prompt)


class DocumentImage(Schema):
    # exclude: the event log does not keep the image (a referral, an ID card: personal, often health data)
    image: str = Field(description="Photo or scan of the document (JPEG, PNG or HEIC), base64 or a data URL",
                       exclude=True)


class DocumentText(Schema):
    document_text: str = Field(description="The text read from the document, line by line, top to bottom")
    ocr_confidence: float = Field(description="How sure the reading is, 0 to 1: low for a blurred or dark photo")


@task("serviceTask")
def read_document_text(request, data: DocumentImage) -> DocumentText:
    """Reads the text of a photographed or scanned document (OCR, with macOS's Vision on this server: the
    image never leaves it). A following task extracts its fields with Input From: Text, "{{document_text}}"."""
    with upstream():
        reading = ModelClient(settings.OCR_URL, settings.MODELS_API_KEY, timeout=30).call({"image": data.image})
    return DocumentText(document_text=reading["text"], ocr_confidence=reading["confidence"])
