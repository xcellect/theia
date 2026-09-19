"""Classify provider failures without returning any provider-supplied text.

Only fixed messages in MESSAGES may reach the browser or terminal. This module
uses the standard library so the web client's matching messages can be checked
without importing providers, loading environment files, or making requests.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

PROVIDERS = ("DEEPGRAM", "SAMBANOVA", "HUME", "GENERALCOMPUTE", "GRADIUM_STT", "GRADIUM_TTS", "PIPELINE")
CATEGORIES = ("AUTH", "QUOTA", "MODEL", "VOICE", "TIMEOUT", "NETWORK", "UNKNOWN")
MESSAGES = json.loads((
    Path(__file__).resolve().parent.parent / "practice/components/pipecat-error-messages.json"
).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    category: str

    @property
    def message(self):
        return MESSAGES[f"{self.provider}:{self.category}"]

    @property
    def wire_message(self):
        return f"[PIPECAT:{self.provider}:{self.category}] {self.message}"


def _get(value, name):
    try:
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    except Exception:
        return None


def _exception_metadata(exception):
    """Read bounded diagnostic fields for classification only; never print them."""
    status, parts = None, []
    current, seen = exception, set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        status_value = _get(current, "status_code") or _get(_get(current, "response"), "status_code")
        if isinstance(status_value, int) and 100 <= status_value <= 599:
            status = status_value
        parts.append(type(current).__name__)
        for value in (current, _get(current, "body"), _get(_get(current, "body"), "error")):
            for name in ("code", "type", "message", "description"):
                text = _get(value, name)
                if isinstance(text, (str, int)):
                    parts.append(str(text)[:1024])
        # Some websocket SDKs expose no fields, only an exception message.
        try:
            parts.append(str(current)[:2048])
        except Exception:
            pass
        current = _get(current, "__cause__") or _get(current, "__context__")
    return status, " ".join(parts).lower()


class ProviderEventError(Exception):
    """Give non-exception websocket events the metadata/traceback shape Pipecat expects."""

    def __init__(self, event):
        super().__init__("Provider streaming event reported a failure")
        self.status_code = _get(event, "status_code")
        self.code = _get(event, "code")
        self.message = _get(event, "message") or _get(event, "description")
        if isinstance(event, str):
            self.message = event[:4096]
        self.body = _get(event, "body")


def classify_failure(frame, providers=None):
    processor = _get(frame, "processor")
    provider = (providers or {}).get(id(processor))
    if provider not in PROVIDERS:
        source = type(processor).__name__.lower()
        provider = next((name for name in PROVIDERS[:-1] if name.lower() in source), "PIPELINE")
        if "gradium" in source:
            provider = "GRADIUM_STT" if "stt" in source else "GRADIUM_TTS" if "tts" in source else "PIPELINE"

    exception = _get(frame, "exception")
    status, metadata = _exception_metadata(exception)
    # Native SDK errors occasionally arrive without an exception. Their text is
    # examined only to select one of our fixed categories; it is never relayed.
    error = _get(frame, "error")
    if isinstance(error, str):
        metadata += " " + error[:4096].lower()
    native_category = str(_get(_get(frame, "category"), "value") or "").lower()

    if status in (402, 429):
        category = "QUOTA"
    elif status in (401, 403):
        category = "AUTH"
    elif isinstance(exception, TimeoutError) or any(term in metadata for term in (
        "timeout", "timed out", "deadline_exceeded", "deadline exceeded",
    )):
        category = "TIMEOUT"
    elif status in (402, 429) or any(term in metadata for term in (
        "insufficient_quota", "insufficient credits", "insufficient balance", "credit balance",
        "payment_required", "payment required", "rate_limit", "rate limit", "out of credits", "quota_exceeded", "credits_exhausted",
        "credits exhausted", "not enough credit", "insufficient credit", "quota exceeded",
    )) or native_category in ("rate_limit", "quota"):
        category = "QUOTA"
    elif provider in ("HUME", "GRADIUM_TTS") and (status == 404 or any(term in metadata for term in (
        "voice_not_found", "invalid_voice", "invalid voice", "voice does not exist", "voice not found",
        "voice must be specified", "voice id is invalid",
    )) or re.search(r"voice.{0,160}(not found|not exist|invalid|not available|not accessible)", metadata)):
        category = "VOICE"
    elif any(term in metadata for term in (
        "model_not_found", "invalid_model", "model not found", "model does not exist",
        "unknown model", "unsupported model", "model_not_available", "model is not supported",
    )) or (provider in ("SAMBANOVA", "GENERALCOMPUTE") and status == 404):
        category = "MODEL"
    elif status in (401, 403) or any(term in metadata for term in (
        "invalid_api_key", "invalid api key", "authenticationerror", "unauthorized", "forbidden",
        "authentication failed", "authentication_error",
        "api key is revoked", "api key is expired", "api key is invalid", "missing api key", "api key not found",
    )) or native_category in ("authentication", "authorization", "permission"):
        category = "AUTH"
    elif isinstance(exception, ConnectionError) or status is not None and status >= 500 or any(term in metadata for term in (
        "connectionerror", "connecterror", "networkerror", "connection reset", "connection refused",
        "name or service not known", "nodename nor servname", "websocket", "net-0001",
        "sslerror", "certificate verify failed", "remoteprotocolerror",
        "internal server error",
    )) or native_category in ("connectivity", "server", "connection", "unavailable"):
        category = "NETWORK"
    else:
        category = "UNKNOWN"
    return ProviderFailure(provider, category)


class FailureReporter:
    """Keep the first actionable failure and print it once for each session."""

    def __init__(self, providers=None, sink=None):
        self.providers = providers or {}
        self.failure = None
        self.sink = sink or (lambda message: print(message, file=sys.stderr, flush=True))

    def report(self, frame):
        if self.failure is None:
            self.failure = classify_failure(frame, self.providers)
            self.sink(self.failure.wire_message)
        return self.failure
