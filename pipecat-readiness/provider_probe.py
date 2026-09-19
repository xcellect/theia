"""Small real-provider probes, without microphone capture or secret-bearing logs."""
import argparse
import asyncio
import base64
import json
import os
import sys

from server import configure_safe_logging
from voice_config import ConfigurationError, load_practice_environment, read_config, read_gradium_config
from provider_errors import ProviderEventError

configure_safe_logging()


class GradiumProtocolError(ValueError):
    """Fixed diagnostic codes, never raw provider message contents."""

    def __init__(self, reason, expected_rate=None, actual_rate=None):
        super().__init__("Gradium returned an unexpected protocol response")
        self.reason = reason
        self.expected_rate = expected_rate
        self.actual_rate = actual_rate if isinstance(actual_rate, int) else None


def failure(provider, error):
    # Report only fixed categories and numeric HTTP status. Never serialize an
    # exception, provider body, request headers, key, voice ID, or audio data.
    if isinstance(error, GradiumProtocolError):
        return {"provider": provider, "ok": False, "category": "PROTOCOL", "reason": error.reason,
                **({"expectedSampleRate": error.expected_rate} if error.expected_rate is not None else {}),
                **({"actualSampleRate": error.actual_rate} if error.actual_rate is not None else {})}
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    message = (str(error) + " " + str(getattr(error, "message", ""))).lower()
    billing_reason = (
        "PAYMENT_METHOD_REQUIRED" if "payment method" in message else
        "CREDITS_EXHAUSTED" if "credits_exhausted" in message or "out of credits" in message or "insufficient credit" in message else
        "PAYMENT_REQUIRED" if status == 402 else None
    )
    category = (
        "AUTH" if status in (401, 403) or any(term in message for term in (
            "invalid api key", "api key is revoked", "api key is expired", "unauthorized",
        )) else
        "QUOTA" if status in (402, 429) else
        "QUOTA" if any(term in message for term in ("credits_exhausted", "insufficient credit", "out of credits", "quota", "rate limit")) else
        "VOICE" if provider in ("hume", "gradium-tts") and (status == 404 or "voice" in message) else
        "MODEL" if status == 404 or "model" in message else
        "REQUEST" if status in (400, 422) else
        "TIMEOUT" if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower() else
        "NETWORK" if isinstance(error, OSError) or "connect" in type(error).__name__.lower() or "dns" in message else
        "UNKNOWN"
    )
    return {"provider": provider, "ok": False, "category": category,
            **({"billingReason": billing_reason} if billing_reason else {}),
            **({"httpStatus": status} if isinstance(status, int) else {})}


async def sambanova(config):
    from pipecat.services.sambanova.llm import SambaNovaLLMService
    from voice_pipeline import BoundedSambaNovaLLMService

    llm = BoundedSambaNovaLLMService(
        api_key=config.sambanova_key, base_url=config.base_url,
        settings=SambaNovaLLMService.Settings(model=config.model, max_tokens=256,
            system_instruction="Answer briefly in one short sentence."),
        request_timeout=config.timeout_seconds,
    )
    return await llm_reply(llm, "sambanova")


async def generalcompute(config):
    from pipecat.services.openai.llm import OpenAILLMService
    from voice_pipeline import BoundedGeneralComputeLLMService, GC_MAX_TOKENS

    llm = BoundedGeneralComputeLLMService(
        api_key=config.generalcompute_key, base_url=config.base_url,
        settings=OpenAILLMService.Settings(model=config.model, max_tokens=GC_MAX_TOKENS,
            system_instruction="Answer briefly in one short sentence."),
        request_timeout=config.timeout_seconds,
    )
    return await llm_reply(llm, "generalcompute")


async def llm_reply(llm, provider):
    from pipecat.processors.aggregators.llm_context import LLMContext

    chars, reasoning_chars, finish = 0, 0, None
    try:
        stream = await llm.get_chat_completions(LLMContext(messages=[{"role": "user", "content": "Say hello."}]))
        async with stream:
            async for chunk in stream:
                for choice in chunk.choices or []:
                    chars += len(choice.delta.content or "")
                    reasoning_chars += len(getattr(choice.delta, "reasoning_content", "") or "")
                    if choice.finish_reason in ("stop", "length", "tool_calls", "content_filter"):
                        finish = choice.finish_reason
        return {"provider": provider, "ok": chars > 0, "textCharacters": chars,
                "reasoningCharacters": reasoning_chars, "finishReason": finish,
                **({"category": "NO_SPOKEN_TEXT"} if not chars else {})}
    finally:
        await llm._client.close()


async def hume(config):
    import httpx
    from hume import AsyncHumeClient
    from hume.tts import FormatPcm, PostedUtterance, PostedUtteranceVoiceWithId

    size = 0
    async with httpx.AsyncClient(timeout=config.timeout_seconds) as http_client:
        client = AsyncHumeClient(api_key=config.hume_key, httpx_client=http_client)
        async for chunk in client.tts.synthesize_json_streaming(
            utterances=[PostedUtterance(text="Hello.", voice=PostedUtteranceVoiceWithId(id=config.voice_id))],
            format=FormatPcm(type="pcm"), instant_mode=True, version="2",
            include_timestamp_types=["word"], request_options={"max_retries": 0},
        ):
            if getattr(chunk, "audio", None):
                size += len(base64.b64decode(chunk.audio))
    return {"provider": "hume", "ok": size > 0, "audioBytes": size}


async def deepgram(config):
    from deepgram import AsyncDeepgramClient

    client = AsyncDeepgramClient(api_key=config.deepgram_key)
    async with client.listen.v1.connect(model=config.deepgram_model, encoding="linear16", sample_rate="16000", channels="1") as connection:
        # 100 ms of silence checks the stream without recording the user.
        await connection.send_media(bytes(3200))
        await connection.send_close_stream()
    return {"provider": "deepgram", "ok": True, "websocketOpened": True,
            "note": "Connection check only; no spoken transcription tested."}


async def gradium_message(connection):
    message = json.loads(await connection.recv())
    if not isinstance(message, dict):
        raise GradiumProtocolError("INVALID_MESSAGE_SHAPE")
    if message.get("type") == "error":
        raise ProviderEventError(message)
    return message


async def gradium_ready(connection, sample_rate=None):
    while True:
        message = await gradium_message(connection)
        if message.get("type") == "ready":
            if sample_rate is not None and message.get("sample_rate") != sample_rate:
                raise GradiumProtocolError("UNEXPECTED_SAMPLE_RATE", sample_rate, message.get("sample_rate"))
            return message
        if message.get("type") == "end_of_stream":
            raise GradiumProtocolError("STREAM_ENDED_BEFORE_READY")


async def gradium_stt(config):
    from websockets.asyncio.client import connect

    async with connect(config.stt_url, additional_headers={"x-api-key": config.gradium_key},
                       open_timeout=config.timeout_seconds, close_timeout=2) as connection:
        await connection.send(json.dumps({"type": "setup", "model_name": "default",
            "input_format": "pcm_16000", "json_config": {"language": "en", "delay_in_frames": 12}}))
        # The accepted input format declares 16 kHz PCM. Gradium can report
        # 24 kHz in its ready metadata; the native Pipecat STT service also
        # accepts that setup without changing the input audio rate.
        ready = await gradium_ready(connection)
        await connection.send(json.dumps({"type": "audio", "audio": base64.b64encode(bytes(3200)).decode("ascii")}))
        await connection.send(json.dumps({"type": "end_of_stream"}))
        while (await gradium_message(connection)).get("type") != "end_of_stream":
            pass
    return {"provider": "gradium-stt", "ok": True, "websocketOpened": True,
            "inputSampleRate": 16000,
            **({"reportedSampleRate": ready["sample_rate"]} if isinstance(ready.get("sample_rate"), int) else {}),
            "note": "Setup and 100 ms silence accepted; no spoken transcription tested."}


async def gradium_tts(config):
    from websockets.asyncio.client import connect

    size = 0
    async with connect(config.tts_url, additional_headers={"x-api-key": config.gradium_key},
                       open_timeout=config.timeout_seconds, close_timeout=2) as connection:
        await connection.send(json.dumps({"type": "setup", "model_name": "default",
            "output_format": "pcm", "voice_id": config.voice_id}))
        await gradium_ready(connection, 48000)
        await connection.send(json.dumps({"type": "text", "text": "Hello."}))
        await connection.send(json.dumps({"type": "end_of_stream"}))
        while True:
            message = await gradium_message(connection)
            if message.get("type") == "end_of_stream":
                break
            if message.get("type") == "audio":
                size += len(base64.b64decode(message["audio"], validate=True))
    return {"provider": "gradium-tts", "ok": size > 0, "audioBytes": size,
            "sampleRate": 48000, "note": "Audio generation only; browser playback not tested."}


STACK_PROVIDERS = {"pipecat": ("deepgram", "sambanova", "hume"),
                   "gradium": ("gradium-stt", "generalcompute", "gradium-tts")}


async def run(selected, stack="pipecat"):
    allowed = STACK_PROVIDERS[stack]
    if selected != "all" and selected not in allowed:
        print("The selected provider is not part of this stack. Use --stack gradium for the new route.")
        return 1
    load_practice_environment()
    config = (read_gradium_config if stack == "gradium" else read_config)(os.environ)
    names = [selected] if selected != "all" else allowed
    print("REAL REQUESTS: one STT connection, short text reply, and/or 'Hello.' synthesis for the selected providers. No retries.", flush=True)
    failed = False
    for name in names:
        try:
            async with asyncio.timeout(min(config.timeout_seconds, 60)):
                result = await {"deepgram": deepgram, "sambanova": sambanova, "hume": hume,
                                "generalcompute": generalcompute, "gradium-stt": gradium_stt,
                                "gradium-tts": gradium_tts}[name](config)
        except Exception as error:
            result = failure(name, error)
        print(json.dumps(result), flush=True)
        failed |= not result["ok"]
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", choices=list(STACK_PROVIDERS), default="pipecat")
    parser.add_argument("--provider", choices=["all", *STACK_PROVIDERS["pipecat"], *STACK_PROVIDERS["gradium"]], default="all")
    try:
        args = parser.parse_args()
        sys.exit(asyncio.run(run(args.provider, args.stack)))
    except KeyboardInterrupt:
        print("Provider probe cancelled.")
        sys.exit(130)
    except ConfigurationError as error:
        print(str(error))  # ConfigurationError contains only fixed instructions and variable names.
        sys.exit(1)
    except Exception:
        print("Provider probe could not start. Check the required Pipecat settings and installed dependencies.")
        sys.exit(1)
