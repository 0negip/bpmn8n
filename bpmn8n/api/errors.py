"""How a model server failure (Laya, GLiNER) reaches the n8n node as an HTTP answer."""
from contextlib import contextmanager

from ninja.errors import HttpError

from ..clients.http import ServiceUnavailable


@contextmanager
def upstream():
    """503 while the model is still busy after its retries (try again later), else 502."""
    try:
        yield
    except ServiceUnavailable as e:
        raise HttpError(503 if e.busy else 502, str(e)) from e
