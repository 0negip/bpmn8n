"""The web, for bpmn8n Studio's domain research: searches through SearXNG (SEARCH_URL: its JSON API;
docker-compose.yml runs one) and the text of the pages they find. Pages come from anywhere: only public
addresses are read (never this server's own network), and what they say is data for the LLM."""
import ipaddress
import re
import socket
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from ..conf import settings
from .http import ServiceUnavailable, request_json

SKIP = {"script", "style", "noscript", "svg", "template", "nav", "header", "footer", "aside", "form", "button"}
MAX_BYTES = 3_000_000
AGENT = "Mozilla/5.0 (compatible; bpmn8n-studio-research)"


class WebError(Exception):
    pass


def available():
    return bool(settings.SEARCH_URL)


def search(query, count=5):
    """[{"title", "url", "snippet"}]: the first `count` web results for `query`."""
    url = f"{settings.SEARCH_URL.rstrip('/')}/search?{urlencode({'q': query, 'format': 'json'})}"
    try:
        reply = request_json("GET", url, headers={"Accept": "application/json"}, timeout=30)
    except ServiceUnavailable as e:
        raise WebError(f"the search failed: {e}") from e
    return [{"title": r.get("title") or r["url"], "url": r["url"], "snippet": r.get("content") or ""}
            for r in reply.get("results", []) if str(r.get("url", "")).startswith(("http://", "https://"))][:count]


def public(url):
    """`url`, if it is a public web address; else WebError (a private, loopback or link-local one)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError(f"{url}: not a web address")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError as e:
        raise WebError(f"{url}: {e}") from e
    # ponytail: checked before the request, so a DNS answer that changes in between is not; a proxy
    # with an allowlist closes that gap
    if not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise WebError(f"{url}: not a public address")
    return url


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, public(newurl))


class Text(HTMLParser):
    """The readable text of an HTML page: no scripts, styles, menus, headers or footers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipping = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skipping += 1

    def handle_endtag(self, tag):
        if tag in SKIP and self.skipping:
            self.skipping -= 1

    def handle_data(self, data):
        if not self.skipping and data.strip():
            self.parts.append(data.strip())


OPENER = urllib.request.build_opener(PublicRedirects)


def page_text(url, limit=6000, timeout=20):
    """The first `limit` characters of the page's text ("" for what is not HTML or text: a PDF, an image)."""
    request = urllib.request.Request(public(url), headers={"User-Agent": AGENT, "Accept": "text/html,text/plain"})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            kind = response.headers.get_content_type()
            if kind not in ("text/html", "text/plain", "application/xhtml+xml"):
                return ""
            body = response.read(MAX_BYTES).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except (OSError, ValueError) as e:  # refused, timed out, HTTP errors, a bad redirect
        raise WebError(f"{url}: {e}") from e
    if kind != "text/plain":
        parser = Text()
        parser.feed(body)
        body = " ".join(parser.parts)
    return re.sub(r"\s+", " ", body).strip()[:limit]

