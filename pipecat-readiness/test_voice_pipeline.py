"""Exercise the real worker, aggregators, and RTVI protocol with offline services."""

import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from openai import APIStatusError

from server import configure_safe_logging
from test_voice_server import FakeConnection, FIXTURE_ENV
from voice_config import read_config

configure_safe_logging()

from pipecat.frames.frames import (
    AggregatedTextFrame,
    AggregationType,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame,
    TTSTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.base_output import BaseOutputTransport
import voice_pipeline


class PassThrough(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class MemoryOutput(BaseOutputTransport):
    """Run Pipecat's real audio/text timing, recording instead of opening a device."""

    def __init__(self, params):
        super().__init__(params)
        self.messages = []
        self.audio = []
        self.bot_ready = asyncio.Event()
        self.audio_ready = asyncio.Event()
        self.bot_text_ready = asyncio.Event()
        self.bot_output_ready = asyncio.Event()

    async def start(self, frame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def send_message(self, frame):
        self.messages.append(frame.message)
        if frame.message.get("type") == "bot-ready":
            self.bot_ready.set()
        if frame.message.get("type") == "bot-llm-text":
            self.bot_text_ready.set()
        if frame.message.get("type") == "bot-output":
            self.bot_output_ready.set()

    async def write_audio_frame(self, frame):
        self.audio.append(frame)
        self.audio_ready.set()
        return True


class MemoryTransport:
    def __init__(self, connection, params):
        self.input_processor = PassThrough()
        self.output_processor = MemoryOutput(params)
        self.events = {}

    def input(self):
        return self.input_processor

    def output(self):
        return self.output_processor

    def event_handler(self, name):
        def register(callback):
            self.events[name] = callback
            return callback
        return register


class FixtureSTT(PassThrough):
    Settings = voice_pipeline.DeepgramSTTService.Settings

    def __init__(self, **kwargs):
        super().__init__()
        self.audio_seen = False

    async def process_frame(self, frame, direction):
        if isinstance(frame, InputAudioRawFrame):
            self.audio_seen = True
            # Model a streaming STT final result. Turn-end timing and context
            # aggregation below remain the application's actual Pipecat logic.
            await self.push_frame(TranscriptionFrame(
                text="Hello pipeline", user_id="fixture-user",
                timestamp="2026-09-18T12:00:00Z", finalized=True,
            ))
        else:
            await super().process_frame(frame, direction)


class FixtureLLM(PassThrough):
    def __init__(self, **kwargs):
        super().__init__()
        self._client = SimpleNamespace(close=AsyncMock())
        self.context_seen = None
        self.fail = False
        self.failure_exception = None

    async def process_frame(self, frame, direction):
        if isinstance(frame, LLMContextFrame):
            self.context_seen = copy.deepcopy(frame.context.get_messages())
            if self.fail:
                await self.push_error(error_msg="fixture-secret from a provider response", exception=self.failure_exception)
            else:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(LLMTextFrame(text="Hello from the offline pipeline."))
                await self.push_frame(LLMFullResponseEndFrame())
        else:
            await super().process_frame(frame, direction)


class FixtureTTS(PassThrough):
    def __init__(self, **kwargs):
        super().__init__()
        self._http_client = SimpleNamespace(aclose=AsyncMock())
        self.text_seen = []
        self.segment = None

    async def process_frame(self, frame, direction):
        if isinstance(frame, LLMTextFrame):
            self.text_seen.append(frame.text)
            # Hume uses Pipecat's word-timestamp path: emit a sentence segment
            # before audio, then word text as playback progresses.
            self.segment = AggregatedTextFrame(text=frame.text, aggregated_by=AggregationType.SENTENCE)
            self.segment.will_be_spoken = True
            await self.push_frame(self.segment)
            await self.push_frame(TTSAudioRawFrame(audio=bytes(9600), sample_rate=48000, num_channels=1))
            await self.push_frame(TTSTextFrame(text=frame.text, aggregated_by=AggregationType.WORD))
        else:
            await super().process_frame(frame, direction)


class WorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(voice_pipeline, "SmallWebRTCTransport", MemoryTransport),
            patch.object(voice_pipeline, "DiagnosticDeepgramSTTService", FixtureSTT),
            patch.object(voice_pipeline, "BoundedSambaNovaLLMService", FixtureLLM),
            patch.object(voice_pipeline, "BoundedHumeTTSService", FixtureTTS),
        ]
        for replacement in self.patches:
            replacement.start()
        self.session = voice_pipeline.VoiceSession(FakeConnection(), read_config(FIXTURE_ENV))
        self.reported_errors = []
        self.session.reporter.sink = self.reported_errors.append
        self.started = asyncio.Event()

        @self.session.worker.event_handler("on_pipeline_started")
        async def started(worker, frame):
            self.started.set()

        self.task = asyncio.create_task(self.session.run())
        await asyncio.wait_for(self.started.wait(), timeout=3)

    async def asyncTearDown(self):
        await self.session.close()
        await asyncio.wait_for(self.task, timeout=5)
        for replacement in reversed(self.patches):
            replacement.stop()

    async def ready(self):
        await self.session.worker.queue_frame(InputTransportMessageFrame(message={
            "label": "rtvi-ai", "type": "client-ready", "id": "fixture-ready",
            "data": {"version": "2.1.0", "about": {"library": "offline-test"}},
        }))
        await asyncio.wait_for(self.session.transport.output().bot_ready.wait(), timeout=2)

    async def speak(self):
        await self.session.worker.queue_frame(InputAudioRawFrame(
            audio=bytes(640), sample_rate=16000, num_channels=1,
        ))

    async def test_rtvi_handshake_and_user_audio_reach_llm_tts_and_browser_output(self):
        await self.ready()
        await self.speak()
        output = self.session.transport.output()
        await asyncio.wait_for(output.audio_ready.wait(), timeout=3)
        await asyncio.wait_for(output.bot_text_ready.wait(), timeout=2)
        await asyncio.wait_for(output.bot_output_ready.wait(), timeout=2)
        self.assertTrue(self.session.stt.audio_seen)
        self.assertIn({"role": "user", "content": "Hello pipeline"}, self.session.llm.context_seen)
        self.assertEqual(self.session.tts.text_seen, ["Hello from the offline pipeline."])
        self.assertEqual(output.audio[0].sample_rate, 48000)
        self.assertEqual(output.audio[0].num_channels, 1)
        message_types = [message["type"] for message in output.messages]
        self.assertIn("bot-ready", message_types)
        self.assertIn("user-transcription", message_types)
        self.assertIn("bot-llm-text", message_types)
        segment = next(message["data"] for message in output.messages if message["type"] == "bot-output")
        self.assertEqual(segment["text"], "Hello from the offline pipeline.")
        self.assertEqual(segment["segment_id"], self.session.tts.segment.id)
        self.assertEqual(segment["aggregated_by"], "sentence")
        self.assertTrue(segment["will_be_spoken"])
        self.assertEqual(segment["spoken_status"], "new")
        self.assertEqual(segment["spoken_progress"], {
            "accumulated_text": "", "remaining_text": "Hello from the offline pipeline.",
        })

    async def test_provider_error_cancels_worker_and_never_relays_raw_error(self):
        await self.ready()
        self.session.llm.fail = True
        self.session.llm.failure_exception = APIStatusError(
            "private fixture-secret provider response",
            response=httpx.Response(402, request=httpx.Request("POST", "https://provider.invalid/v1")),
            body={"message": "fixture-secret billing body"},
        )
        await self.speak()
        await asyncio.wait_for(asyncio.shield(self.task), timeout=3)
        self.assertTrue(self.session.connection.closed)
        self.session.llm._client.close.assert_awaited()
        self.session.tts._http_client.aclose.assert_awaited()
        messages = self.session.transport.output().messages
        self.assertNotIn("fixture-secret", str(messages))
        errors = [message for message in messages if message["type"] == "error"]
        self.assertTrue(errors)
        self.assertTrue(errors[0]["data"]["error"].startswith("[PIPECAT:SAMBANOVA:QUOTA] "))
        self.assertEqual(self.reported_errors, [errors[0]["data"]["error"]])


if __name__ == "__main__":
    unittest.main()
