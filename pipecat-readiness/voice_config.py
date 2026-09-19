"""Configuration for the local modular voice route; never serialize credentials."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv

REQUIRED_VARIABLES = (
    "DEEPGRAM_API_KEY",
    "SAMBANOVA_API_KEY",
    "SAMBANOVA_MODEL",
    "HUME_API_KEY",
    "HUME_VOICE_ID",
)
GRADIUM_REQUIRED_VARIABLES = (
    "GENERALCOMPUTE_API_KEY", "GENERALCOMPUTE_MODEL", "GRADIUM_API_KEY", "GRADIUM_VOICE_ID",
)


class ConfigurationError(ValueError):
    """Contains variable names only, never their configured values."""

    def __init__(self, message: str, missing: tuple[str, ...] = ()):
        super().__init__(message)
        self.missing = missing


def load_practice_environment() -> None:
    practice = Path(__file__).resolve().parent.parent / "practice"
    load_dotenv(practice / ".env.local", override=False)
    load_dotenv(practice / ".env", override=False)


def missing_variables(environment: Mapping[str, str], required=REQUIRED_VARIABLES) -> tuple[str, ...]:
    return tuple(name for name in required if not environment.get(name, "").strip())


@dataclass(frozen=True)
class VoiceConfig:
    deepgram_key: str = field(repr=False)
    sambanova_key: str = field(repr=False)
    model: str
    hume_key: str = field(repr=False)
    voice_id: str
    base_url: str = "https://api.sambanova.ai/v1"
    timeout_seconds: float = 60
    deepgram_model: str = "nova-3-general"


@dataclass(frozen=True)
class GradiumVoiceConfig:
    generalcompute_key: str = field(repr=False)
    gradium_key: str = field(repr=False)
    model: str
    voice_id: str
    base_url: str = "https://api.generalcompute.com/v1"
    region: str = "auto"
    timeout_seconds: float = 60

    @property
    def stt_url(self):
        prefix = "" if self.region == "auto" else self.region + "."
        return f"wss://{prefix}api.gradium.ai/api/speech/asr"

    @property
    def tts_url(self):
        prefix = "" if self.region == "auto" else self.region + "."
        return f"wss://{prefix}api.gradium.ai/api/speech/tts"


def read_timeout(environment):
    raw_timeout = environment.get("PROVIDER_TIMEOUT_MS", "").strip() or "60000"
    try:
        timeout_ms = int(raw_timeout)
    except ValueError:
        raise ConfigurationError("PROVIDER_TIMEOUT_MS must be an integer from 100 to 120000.") from None
    if not 100 <= timeout_ms <= 120000:
        raise ConfigurationError("PROVIDER_TIMEOUT_MS must be an integer from 100 to 120000.")
    return timeout_ms / 1000


def read_base_url(environment, name, default):
    base_url = environment.get(name, "").strip() or default
    try:
        parsed = urlsplit(base_url)
        valid_url = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in base_url)
        )
        _ = parsed.port
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ConfigurationError(f"{name} must be an HTTPS URL without credentials, query, or fragment.")
    return base_url.rstrip("/")


def read_config(environment: Mapping[str, str]) -> VoiceConfig:
    missing = missing_variables(environment)
    if missing:
        raise ConfigurationError("Missing variables: " + ", ".join(missing), missing)

    return VoiceConfig(
        deepgram_key=environment["DEEPGRAM_API_KEY"].strip(),
        sambanova_key=environment["SAMBANOVA_API_KEY"].strip(),
        model=environment["SAMBANOVA_MODEL"].strip(),
        hume_key=environment["HUME_API_KEY"].strip(),
        voice_id=environment["HUME_VOICE_ID"].strip(),
        base_url=read_base_url(environment, "SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1"),
        timeout_seconds=read_timeout(environment),
        deepgram_model=environment.get("DEEPGRAM_MODEL", "").strip() or "nova-3-general",
    )


def read_gradium_config(environment: Mapping[str, str]) -> GradiumVoiceConfig:
    missing = missing_variables(environment, GRADIUM_REQUIRED_VARIABLES)
    if missing:
        raise ConfigurationError("Missing variables: " + ", ".join(missing), missing)
    region = environment.get("GRADIUM_REGION", "").strip().lower() or "auto"
    if region not in ("auto", "us", "eu"):
        raise ConfigurationError("GRADIUM_REGION must be auto, us, or eu.")
    return GradiumVoiceConfig(
        generalcompute_key=environment["GENERALCOMPUTE_API_KEY"].strip(),
        gradium_key=environment["GRADIUM_API_KEY"].strip(),
        model=environment["GENERALCOMPUTE_MODEL"].strip(),
        voice_id=environment["GRADIUM_VOICE_ID"].strip(),
        base_url=read_base_url(environment, "GENERALCOMPUTE_BASE_URL", "https://api.generalcompute.com/v1"),
        region=region,
        timeout_seconds=read_timeout(environment),
    )
