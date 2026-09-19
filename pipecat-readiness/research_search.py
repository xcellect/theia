"""Bounded Exa discovery/extraction; only returned source text becomes evidence."""

import asyncio
from hashlib import sha256
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

import httpx

EXA_BASE = "https://api.exa.ai"
MAX_SOURCES = 8
MAX_EVIDENCE_CHARS = 16000
MAX_SOURCE_CHARS = 3200
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_TIMEOUT = 20.0
TOTAL_TIMEOUT = 30.0


class ExaSearchError(RuntimeError):
    """Safe public failure: never includes a provider body, URL, or API key."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def public_url(value):
    """Validate URLs before sending them to Exa; never resolve/fetch them locally."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ExaSearchError("invalid_url", "Use a public HTTP or HTTPS paper URL without credentials.")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
        if (parsed.scheme not in ("http", "https") or parsed.username is not None
                or parsed.password is not None or port not in (None, 80, 443)):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        host = host.encode("idna").decode("ascii")
        if (not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}", host)
                or host.rsplit(".", 1)[-1] in {"localhost", "local", "internal", "home", "lan", "test", "invalid", "onion"}
                or host in {"localhost.localdomain", "metadata.google.internal"}):
            raise ValueError
        netloc = host + (f":{port}" if port is not None else "")
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        raise ExaSearchError("invalid_url", "Use a public HTTP or HTTPS paper URL without credentials.") from None


def _label(value, limit):
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit] if isinstance(value, str) else None


def _source_text(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 120 or len(re.findall(r"\w+", text)) < 20:
        return None
    if re.match(r"(?is)(?:%PDF|<!doctype\s+html|<html\b|<\?xml)", text):
        return None
    if "\x00" in text or text.count("\ufffd") > max(3, len(text) // 100):
        return None
    if re.match(r"(?is)^(?:access denied|just a moment|checking your browser|captcha|403 forbidden)\b", text):
        return None
    return text


async def _request(client, endpoint, payload, api_key):
    # Streaming bounds the raw provider response as well as the eventual excerpts.
    async with client.stream("POST", f"{EXA_BASE}/{endpoint}", json=payload,
                             headers={"x-api-key": api_key, "Content-Type": "application/json"},
                             timeout=REQUEST_TIMEOUT, follow_redirects=False) as response:
        status = response.status_code
        if status in (401, 403):
            raise ExaSearchError("authentication", "Exa rejected the API key. Check EXA_API_KEY on the server.")
        if status == 402:
            raise ExaSearchError("quota", "Exa search credits are unavailable. Check the Exa account balance.")
        if status == 429:
            raise ExaSearchError("rate_limit", "Exa is rate limited. Try the research question again shortly.")
        if status < 200 or status >= 300:
            raise ExaSearchError("provider_error", "Exa could not retrieve papers. Try again or paste a paper excerpt.")
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ExaSearchError("response_too_large", "Exa returned too much content. Try a more specific paper query.")
            chunks.append(chunk)
    try:
        data = json.loads(b"".join(chunks))
    except (ValueError, UnicodeError):
        raise ExaSearchError("invalid_response", "Exa returned unreadable results. Try the research question again.") from None
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ExaSearchError("invalid_response", "Exa returned unreadable results. Try the research question again.")
    return data["results"]


def result_links(result):
    """Keep bounded public links before excerpt truncation, including Exa extras."""
    values = []

    def collect(value):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value[:64]:
                collect(item)
        elif isinstance(value, dict):
            for key in ("url", "href", "link"):
                collect(value.get(key))

    extras = result.get("extras")
    if isinstance(extras, dict):
        collect(extras.get("links"))
    collect(result.get("links"))
    subpages = result.get("subpages")
    for child in (subpages[:16] if isinstance(subpages, list) else []):
        if isinstance(child, dict):
            collect(child.get("url"))
    # Exa's complete response is already capped at 2 MB. Scan the complete
    # returned text so references beyond the displayed 3.2k excerpt survive.
    text = result.get("text")
    if isinstance(text, str):
        values.extend(re.findall(r"https?://[^\s<>\"']+", text)[:128])
    output = []
    for value in values:
        try:
            url = public_url(value.rstrip(").,;]}"))
        except ExaSearchError:
            continue
        if url not in output:
            output.append(url)
        if len(output) == 64:
            break
    return output


async def acquire_sources(question, api_key, emit, *, urls=None, http=None,
                          candidates=None, allow_empty=False, include_domains=None):
    """Search publications or extract supplied URLs, returning at most 16k evidence chars.

    Search/extraction is one Exa request, so discoveries become visible when its
    response arrives. No summaries, highlights, or metadata are substituted for
    missing extracted text. Caller-owned clients stay open; cancellation propagates.
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ExaSearchError("not_configured", "Paper search needs EXA_API_KEY on the server. You can also paste a paper excerpt.")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ExaSearchError("invalid_query", "Enter a research question of 1 to 4000 characters.")
    requested = None
    if urls is not None:
        if not isinstance(urls, (list, tuple)) or not 1 <= len(urls) <= MAX_SOURCES:
            raise ExaSearchError("invalid_url", "Provide between one and eight public paper URLs.")
        requested = list(dict.fromkeys(public_url(value) for value in urls))
    endpoint = "contents" if requested else "search"
    payload = {"urls": requested, "text": True} if requested else {
        "query": question.strip(), "category": "publication", "numResults": 5,
        "contents": {"text": True},
    }
    if candidates is not None:
        # Metadata is kept separately from evidence; a PDF can be prepared even
        # when Exa cannot extract text from its landing page.
        if requested:
            payload["extras"] = {"links": 32}
        else:
            payload["contents"]["extras"] = {"links": 32}
    if include_domains and not requested:
        if not isinstance(include_domains, (list, tuple)) or any(
                not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9.-]+", domain)
                for domain in include_domains):
            raise ExaSearchError("invalid_query", "Use a valid publication domain filter.")
        payload["includeDomains"] = list(include_domains)[:8]
    emit("search.started", query=question.strip(), provider="Exa", mode="url" if requested else "search")
    if requested:
        for url in requested:
            emit("source.fetch.started", url=url, provider="Exa")
    else:
        emit("source.fetch.started", provider="Exa", message="Searching papers and retrieving text excerpts.")

    owned_client = http is None
    client = http if http is not None else httpx.AsyncClient()
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            results = await _request(client, endpoint, payload, api_key.strip())
    except (TimeoutError, httpx.TimeoutException):
        raise ExaSearchError("timeout", "Paper retrieval timed out. Try a narrower question or paste the paper excerpt.") from None
    except httpx.HTTPError:
        raise ExaSearchError("network", "Exa could not be reached. Try again or paste a paper excerpt.") from None
    finally:
        if owned_client:
            await client.aclose()

    sources, seen, remaining, discovered = [], set(), MAX_EVIDENCE_CHARS, 0
    for result in results[:MAX_SOURCES]:
        if not isinstance(result, dict):
            continue
        try:
            url = public_url(result.get("url"))
        except ExaSearchError:
            continue
        if url in seen:
            continue
        seen.add(url)
        discovered += 1
        title = _label(result.get("title"), 300) or urlsplit(url).hostname
        author = _label(result.get("author"), 300)
        date = _label(result.get("publishedDate"), 64)
        emit("search.result", result={"title": title, "url": url, "author": author,
                                      "publishedDate": date, "status": "discovered"})
        text = _source_text(result.get("text"))
        candidate = None
        if candidates is not None:
            candidate = {"candidateId": "C" + sha256(url.encode()).hexdigest()[:12],
                         "originResultId": _label(result.get("id"), 2048) or url,
                         "url": url, "title": title, "author": author,
                         "publishedDate": date, "links": result_links(result),
                         "textStatus": "available" if text is not None else "unavailable",
                         "sourceId": None}
            candidates.append(candidate)
        if text is None or remaining < 120:
            emit("source.fetch.completed", url=url, title=title, status="unavailable",
                 message="No usable extracted text was returned.")
            continue
        content = text[:min(MAX_SOURCE_CHARS, remaining)]
        remaining -= len(content)
        abstract_only = (bool(re.match(r"(?is)^(?:#+\s*)?abstract\b", text)) and len(text) < 3000
                         and not re.search(r"(?im)^\s*(?:#+\s*|\d[. ]+)?(?:introduction|methods|results|discussion)\b", text))
        if urlsplit(url).hostname in {"arxiv.org", "export.arxiv.org"} and urlsplit(url).path.startswith("/abs/"):
            abstract_only = True
        coverage = "Abstract only; full paper not retrieved." if abstract_only else "Extracted text excerpt; full paper coverage not verified."
        source = {"id": f"S{len(sources) + 1}", "packId": "exa", "title": title,
                  "section": "Abstract excerpt" if abstract_only else "Retrieved text excerpt",
                  "text": content, "url": url, "path": None, "startLine": None, "endLine": None,
                  "author": author, "publishedDate": date, "coverage": coverage,
                  "sha256": sha256(content.encode()).hexdigest()}
        sources.append(source)
        if candidate is not None:
            candidate["sourceId"] = source["id"]
        emit("source.fetch.completed", url=url, title=title, sourceId=source["id"],
             status="ready", coverage=coverage, characters=len(content))
    emit("search.completed", count=discovered, usableCount=len(sources), provider="Exa")
    if not sources and not allow_empty:
        raise ExaSearchError("no_content", "No readable paper text was found. Try a specific title, an open-access paper URL, or paste an excerpt.")
    return sources
