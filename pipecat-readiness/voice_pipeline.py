"""Two modular voice stacks over a shared local SmallWebRTC transport."""

import asyncio
from contextlib import suppress
import json

import httpx
from openai import AsyncOpenAI
from websockets.protocol import State
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import ErrorFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIObserverParams, RTVIProcessor
from pipecat.processors.frameworks.rtvi import models as RTVI
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.hume.tts import HumeTTSService
from pipecat.services.gradium.stt import GradiumSTTService
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sambanova.llm import SambaNovaLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies, UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from voice_config import GradiumVoiceConfig, VoiceConfig
from provider_errors import FailureReporter, MESSAGES, ProviderEventError

SAFE_PIPELINE_ERROR = "[PIPECAT:PIPELINE:UNKNOWN] " + MESSAGES["PIPELINE:UNKNOWN"]
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant in a practice conversation. "
    "Answer naturally in one or two short sentences. "
    "Avoid markdown, tables, and long lists because your answers are spoken aloud."
)
MAX_SESSION_SECONDS = 600
IDLE_TIMEOUT_SECONDS = 120
GC_MAX_TOKENS = 1024


class SafeRTVIProcessor(RTVIProcessor):
    """RTVI must not forward provider exception text, bodies, or credentials."""

    def __init__(self, *, reporter=None, **kwargs):
        super().__init__(**kwargs)
        self.reporter = reporter or FailureReporter()

    async def _send_error_frame(self, frame: ErrorFrame):
        failure = self.reporter.report(frame)
        await self.push_transport_message(RTVI.Error(data=RTVI.ErrorData(error=failure.wire_message, fatal=True)))

    async def _send_error_response(self, id: str, error: str):
        await super()._send_error_response(id, "The client message could not be processed.")


class DiagnosticDeepgramSTTService(DeepgramSTTService):
    """Preserve websocket error metadata that the base callback drops."""

    async def _on_error(self, error):
        # Error frames carry this object only inside the Python process. The
        # reporter translates its fields to fixed, credential-free messages.
        exception = error if isinstance(error, Exception) else ProviderEventError(error)
        await self.push_error(error_msg="Deepgram streaming failed", exception=exception)
        await self.stop_all_metrics()


class BoundedLLMRequests:
    """Apply an actual request deadline and disable the SDK's automatic retries."""

    def __init__(self, *, request_timeout: float, **kwargs):
        self._request_timeout = request_timeout
        super().__init__(**kwargs)

    def create_client(self, api_key=None, base_url=None, **kwargs):
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(self._request_timeout),
            max_retries=0,
        )

    async def _process_context(self, context):
        async with asyncio.timeout(self._request_timeout):
            await super()._process_context(context)

    async def cleanup(self):
        try:
            await super().cleanup()
        finally:
            await self._client.close()


class BoundedSambaNovaLLMService(BoundedLLMRequests, SambaNovaLLMService):
    """The existing SambaNova route retains its native provider implementation."""


class BoundedGeneralComputeLLMService(BoundedLLMRequests, OpenAILLMService):
    """General Compute uses the documented OpenAI-compatible chat endpoint."""

    supports_developer_role = False

    def build_chat_completion_params(self, params_from_context):
        params = super().build_chat_completion_params(params_from_context)
        # These OpenAI-specific options are absent from General Compute's
        # published request schema. The standard content stream is sufficient.
        for key in ("stream_options", "service_tier", "seed", "max_completion_tokens"):
            params.pop(key, None)
        return params


class BoundedHumeTTSService(HumeTTSService):
    """Bound a synthesis stream, including providers that stop yielding audio."""

    def __init__(self, *, request_timeout: float, **kwargs):
        super().__init__(**kwargs)
        self._request_timeout = request_timeout
        self._http_client.timeout = httpx.Timeout(request_timeout)

    async def run_tts(self, text: str, context_id: str):
        try:
            async with asyncio.timeout(self._request_timeout):
                async for frame in super().run_tts(text, context_id):
                    if isinstance(frame, ErrorFrame) and frame.processor is None:
                        frame.processor = self
                    yield frame
        except TimeoutError as error:
            yield ErrorFrame(error="Hume TTS request timed out.", processor=self, exception=error)


class BoundedGradiumSTTService(GradiumSTTService):
    """Bound the websocket setup handshake and close rejected sockets."""

    def __init__(self, *, request_timeout, **kwargs):
        self._request_timeout = request_timeout
        self._opened_socket = None
        super().__init__(**kwargs)

    async def _websocket_connect(self, *args, **kwargs):
        socket = await super()._websocket_connect(*args, **kwargs)
        self._opened_socket = socket
        return socket

    async def _send_flush(self):
        # Gradium's documented schema requires an integer. Pipecat 1.11 turns
        # this counter into a string; keep the existing behavior otherwise.
        if not self._websocket or self._websocket.state is not State.OPEN:
            return False
        self._flush_counter += 1
        try:
            await self._websocket.send(json.dumps({"type": "flush", "flush_id": self._flush_counter}))
            return True
        except Exception as error:
            await self.push_error("Gradium STT could not flush the utterance", exception=error)
            return False

    async def _connect_websocket(self):
        completed = False
        try:
            async with asyncio.timeout(self._request_timeout):
                await super()._connect_websocket()
            completed = True
        except TimeoutError as error:
            self._websocket = None
            await self.push_error("Gradium STT setup timed out", exception=error)
        finally:
            if not completed:
                self._websocket = None
            if self._websocket is None and self._opened_socket is not None:
                with suppress(Exception):
                    await self._opened_socket.close()
                self._opened_socket = None


class BoundedGradiumTTSService(GradiumTTSService):
    """Watch each synthesis context until completion or interruption."""

    def __init__(self, *, request_timeout, **kwargs):
        self._request_timeout = request_timeout
        self._deadlines = {}
        super().__init__(**kwargs)

    async def _connect_websocket(self):
        try:
            async with asyncio.timeout(self._request_timeout):
                await super()._connect_websocket()
        except TimeoutError as error:
            await self.push_error("Gradium TTS setup timed out", exception=error)

    async def _watch_context(self, context_id):
        await asyncio.sleep(self._request_timeout)
        if self.audio_context_available(context_id):
            await self.push_error("Gradium TTS request timed out", exception=TimeoutError())

    async def run_tts(self, text, context_id):
        if context_id not in self._deadlines:
            self._deadlines[context_id] = self.create_task(self._watch_context(context_id), "gradium-tts-deadline")
        async for frame in super().run_tts(text, context_id):
            if isinstance(frame, ErrorFrame) and frame.processor is None:
                frame.processor = self
            yield frame

    async def _cancel_deadline(self, context_id):
        task = self._deadlines.pop(context_id, None)
        if task is not None and task is not asyncio.current_task():
            await self.cancel_task(task)

    async def on_audio_context_completed(self, context_id):
        await self._cancel_deadline(context_id)
        await super().on_audio_context_completed(context_id)

    async def on_audio_context_interrupted(self, context_id):
        await self._cancel_deadline(context_id)
        await super().on_audio_context_interrupted(context_id)

    async def _disconnect(self):
        for context_id in list(self._deadlines):
            await self._cancel_deadline(context_id)
        await super()._disconnect()


class VoiceSession:
    """Own one worker, its clients, and the lifetime of the peer connection."""

    def __init__(self, connection, config: VoiceConfig | GradiumVoiceConfig, *, research=None):
        self.connection = connection
        self._closed = False
        self.transport = SmallWebRTCTransport(
            connection,
            TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        )
        if isinstance(config, GradiumVoiceConfig):
            self.stt = BoundedGradiumSTTService(
                api_key=config.gradium_key, api_endpoint_base_url=config.stt_url,
                enable_turn_detection=True, request_timeout=config.timeout_seconds,
            )
            if research is not None:
                from research_bridge import ResearchTurnProcessor
                self.llm = ResearchTurnProcessor(research)
            else:
                self.llm = BoundedGeneralComputeLLMService(
                    api_key=config.generalcompute_key, base_url=config.base_url,
                    settings=OpenAILLMService.Settings(model=config.model, max_tokens=GC_MAX_TOKENS, system_instruction=SYSTEM_INSTRUCTION),
                    request_timeout=config.timeout_seconds,
                )
            self.tts = BoundedGradiumTTSService(
                api_key=config.gradium_key, url=config.tts_url,
                settings=GradiumTTSService.Settings(voice=config.voice_id),
                request_timeout=config.timeout_seconds,
            )
            provider_names = ("GRADIUM_STT", "GENERALCOMPUTE", "GRADIUM_TTS")
            user_params = LLMUserAggregatorParams(user_turn_strategies=ExternalUserTurnStrategies())
        else:
            self.stt = DiagnosticDeepgramSTTService(
                api_key=config.deepgram_key,
                settings=DeepgramSTTService.Settings(model=config.deepgram_model),
            )
            self.llm = BoundedSambaNovaLLMService(
                api_key=config.sambanova_key,
                base_url=config.base_url,
                settings=SambaNovaLLMService.Settings(model=config.model, max_tokens=256, system_instruction=SYSTEM_INSTRUCTION),
                request_timeout=config.timeout_seconds,
            )
            self.tts = BoundedHumeTTSService(
                api_key=config.hume_key,
                settings=HumeTTSService.Settings(voice=config.voice_id),
                sample_rate=48000,
                request_timeout=config.timeout_seconds,
            )
            provider_names = ("DEEPGRAM", "SAMBANOVA", "HUME")
            user_params = LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                # Use bundled Silero rather than downloading Smart Turn.
                user_turn_strategies=UserTurnStrategies(
                    stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)],
                ),
            )
        self.context = LLMContext()
        self.reporter = FailureReporter({
            id(service): name for service, name in zip((self.stt, self.llm, self.tts), provider_names)
        })
        self.aggregators = LLMContextAggregatorPair(
            self.context,
            user_params=user_params,
        )
        research_processors = []
        if research is not None:
            from research_bridge import ResearchTranscriptObserver
            research_processors.append(ResearchTranscriptObserver(self.llm))
        self.pipeline = Pipeline([
            self.transport.input(),
            self.stt,
            *research_processors,
            self.aggregators.user(),
            self.llm,
            self.tts,
            self.transport.output(),
            self.aggregators.assistant(),
        ])
        self.rtvi = SafeRTVIProcessor(reporter=self.reporter)
        self.worker = PipelineWorker(
            self.pipeline,
            params=PipelineParams(
                audio_in_sample_rate=16000,
                audio_out_sample_rate=48000,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            rtvi_processor=self.rtvi,
            rtvi_observer_params=RTVIObserverParams(system_logs_enabled=False),
            idle_timeout_secs=IDLE_TIMEOUT_SECONDS,
            cancel_timeout_secs=5,
            setup_timeout_secs=30,
            start_timeout_secs=30,
        )
        self.runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        self.research_bridge = self.llm if research is not None else None
        if self.research_bridge is not None:
            self.research_bridge.worker = self.worker
            self.research_bridge.rtvi = self.rtvi

            @self.rtvi.event_handler("on_client_ready")
            async def on_research_ready(processor):
                await self.research_bridge.ready()

            @self.aggregators.user().event_handler("on_user_turn_stopped")
            async def on_research_turn(aggregator, strategy, message):
                self.research_bridge.submit(message.content, message.timestamp)

        @self.transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            await self.runner.cancel("Browser disconnected")

        @self.worker.event_handler("on_pipeline_error")
        async def on_pipeline_error(worker, frame):
            self.reporter.report(frame)
            await self.runner.cancel("Voice provider failed")

    async def run(self):
        if self._closed:
            return
        try:
            await self.runner.add_workers(self.worker)
            async with asyncio.timeout(MAX_SESSION_SECONDS):
                await self.runner.run()
        except TimeoutError:
            await self.runner.cancel("Practice session time limit reached")
        except Exception as error:
            self.reporter.report(ErrorFrame(error="Pipeline stopped", exception=error))
            raise
        finally:
            await self.close()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self.research_bridge is not None:
            await self.research_bridge.close()
        await self.runner.cancel("Session ended")
        # Disconnect even if setup never reached the input/output processors.
        with suppress(Exception):
            await self.connection.disconnect()
        # Both are idempotent and cover failures before worker setup completed.
        if self.research_bridge is None:
            with suppress(Exception):
                await self.llm._client.close()
        with suppress(Exception):
            await self.tts._http_client.aclose()
        if isinstance(self.stt, GradiumSTTService):
            with suppress(Exception):
                await self.stt._disconnect()
        if isinstance(self.tts, GradiumTTSService):
            with suppress(Exception):
                await self.tts._disconnect()
