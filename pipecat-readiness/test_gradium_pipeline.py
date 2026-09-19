"""Offline Gradium/General Compute integration and route isolation checks."""

import asyncio
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from openai import APIStatusError
from websockets.protocol import State

from server import create_app
from test_voice_server import FakeConnection, FakeHandler, FakeSession, FIXTURE_ENV, HEADERS, OFFER
from test_voice_pipeline import FixtureLLM, FixtureTTS, MemoryTransport
import test_voice_pipeline as pipeline_fixtures
from voice_config import ConfigurationError, GRADIUM_REQUIRED_VARIABLES, read_gradium_config
from pipecat.frames.frames import LLMTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.websocket_service import WebsocketService
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
import voice_pipeline

GRADIUM_ENV = {
    "GENERALCOMPUTE_API_KEY": "fixture-compute-secret",
    "GENERALCOMPUTE_MODEL": "fixture-compute-model",
    "GRADIUM_API_KEY": "fixture-gradium-secret",
    "GRADIUM_VOICE_ID": "fixture-gradium-voice",
}


class GradiumConfigTests(unittest.TestCase):
    def test_only_the_four_new_variables_are_required(self):
        config = read_gradium_config(GRADIUM_ENV)
        self.assertEqual(config.base_url, "https://api.generalcompute.com/v1")
        self.assertEqual(config.region, "auto")
        self.assertEqual(config.stt_url, "wss://api.gradium.ai/api/speech/asr")
        self.assertEqual(config.tts_url, "wss://api.gradium.ai/api/speech/tts")
        self.assertNotIn("fixture-compute-secret", repr(config))
        self.assertNotIn("fixture-gradium-secret", repr(config))
        with self.assertRaises(ConfigurationError) as result:
            read_gradium_config(FIXTURE_ENV)
        self.assertEqual(result.exception.missing, GRADIUM_REQUIRED_VARIABLES)

    def test_region_is_allowlisted_and_optional_base_url_is_validated(self):
        for region in ("us", "eu"):
            config = read_gradium_config(GRADIUM_ENV | {"GRADIUM_REGION": region})
            self.assertEqual(config.stt_url, f"wss://{region}.api.gradium.ai/api/speech/asr")
        for update in (
            {"GRADIUM_REGION": "fixture-secret.invalid"},
            {"GENERALCOMPUTE_BASE_URL": "https://fixture-secret@provider.invalid/v1"},
            {"GENERALCOMPUTE_BASE_URL": "http://provider.invalid/v1"},
            {"PROVIDER_TIMEOUT_MS": "fixture-secret"},
        ):
            with self.subTest(variable=tuple(update)):
                with self.assertRaises(ConfigurationError) as result:
                    read_gradium_config(GRADIUM_ENV | update)
                self.assertNotIn("fixture-secret", str(result.exception))


class GradiumServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.environment = FIXTURE_ENV | GRADIUM_ENV
        self.app = create_app(environment=self.environment, handler=FakeHandler(), session_factory=FakeSession)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 1234)),
            base_url="http://127.0.0.1:7860", headers=HEADERS,
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.app.state.sessions.close()

    async def test_each_route_reports_only_its_own_missing_configuration(self):
        for name in GRADIUM_REQUIRED_VARIABLES:
            self.environment.pop(name)
        old = await self.client.get("/health")
        new = await self.client.get("/gradium/health")
        self.assertTrue(old.json()["configured"])
        self.assertEqual(new.json()["missing"], list(GRADIUM_REQUIRED_VARIABLES))
        response = await self.client.post("/api/gradium/offer", json=OFFER)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["missing"], list(GRADIUM_REQUIRED_VARIABLES))
        self.environment.clear()
        self.environment.update(GRADIUM_ENV)
        self.assertTrue((await self.client.get("/gradium/health")).json()["configured"])
        self.assertFalse((await self.client.get("/health")).json()["configured"])

    async def test_one_total_session_and_no_cross_route_peer_reuse(self):
        response = await self.client.post("/api/gradium/offer", json=OFFER)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.app.state.sessions.active_route, "gradium")
        for path in ("/health", "/gradium/health"):
            self.assertEqual((await self.client.get(path)).json()["activeSessions"], 1)
        other = await self.client.post("/api/offer", json=OFFER | {"pc_id": "fixture-peer"})
        self.assertEqual(other.status_code, 409)
        patch_body = {"pc_id": "fixture-peer", "candidates": []}
        self.assertEqual((await self.client.patch("/api/offer", json=patch_body)).status_code, 404)
        self.assertEqual((await self.client.patch("/api/gradium/offer", json=patch_body)).status_code, 200)
        self.assertEqual((await self.client.post("/api/gradium/offer", json=OFFER | {"pc_id": "fixture-peer"})).status_code, 200)
        await self.app.state.sessions.close()
        self.assertEqual((await self.client.post("/api/offer", json=OFFER)).status_code, 200)
        self.assertEqual(self.app.state.sessions.active_route, "pipecat")

    async def test_simultaneous_requests_to_different_routes_cannot_open_two_sessions(self):
        responses = await asyncio.gather(
            self.client.post("/api/offer", json=OFFER),
            self.client.post("/api/gradium/offer", json=OFFER),
        )
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(self.app.state.sessions.active_sessions, 1)


class GradiumServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_gradium_flush_ids_follow_the_documented_integer_schema(self):
        stt = voice_pipeline.BoundedGradiumSTTService(api_key="fixture-secret", request_timeout=1)
        stt._websocket = SimpleNamespace(state=State.OPEN, send=AsyncMock())
        self.assertTrue(await stt._send_flush())
        self.assertTrue(await stt._send_flush())
        messages = [json.loads(call.args[0]) for call in stt._websocket.send.call_args_list]
        self.assertEqual(messages, [{"type": "flush", "flush_id": 1}, {"type": "flush", "flush_id": 2}])
    async def test_stt_rejected_setup_closes_the_already_opened_socket(self):
        stt = voice_pipeline.BoundedGradiumSTTService(api_key="fixture-secret", request_timeout=1)
        socket = SimpleNamespace(
            state=State.OPEN, send=AsyncMock(), close=AsyncMock(),
            recv=AsyncMock(return_value=json.dumps({"type": "error", "message": "API key is revoked or expired"})),
        )
        stt.push_error = AsyncMock()
        with patch.object(WebsocketService, "_websocket_connect", AsyncMock(return_value=socket)):
            await stt._connect_websocket()
        socket.close.assert_awaited_once()
        self.assertIsNone(stt._websocket)
        self.assertIsNone(stt._opened_socket)
        stt.push_error.assert_awaited_once()

    async def test_stt_cancelled_setup_closes_the_pending_socket(self):
        stt = voice_pipeline.BoundedGradiumSTTService(api_key="fixture-secret", request_timeout=1)
        waiting = asyncio.Event()

        async def wait_for_ready():
            waiting.set()
            await asyncio.Event().wait()

        socket = SimpleNamespace(state=State.OPEN, send=AsyncMock(), close=AsyncMock(), recv=wait_for_ready)
        with patch.object(WebsocketService, "_websocket_connect", AsyncMock(return_value=socket)):
            task = asyncio.create_task(stt._connect_websocket())
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        socket.close.assert_awaited_once()
        self.assertIsNone(stt._websocket)

    async def test_tts_interruption_cancels_the_request_deadline(self):
        tts = voice_pipeline.BoundedGradiumTTSService(api_key="fixture-secret", request_timeout=0.02)
        tts.audio_context_available = lambda context_id: True
        tts.push_error = AsyncMock()
        task = asyncio.create_task(tts._watch_context("interrupted"))
        tts._deadlines["interrupted"] = task

        async def cancel_task(task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        tts.cancel_task = cancel_task
        with patch.object(GradiumTTSService, "on_audio_context_interrupted", AsyncMock()):
            await tts.on_audio_context_interrupted("interrupted")
        self.assertTrue(task.cancelled())
        self.assertEqual(tts._deadlines, {})
        tts.push_error.assert_not_awaited()

    async def test_real_services_use_explicit_voice_semantic_turns_and_correct_sample_rates(self):
        from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

        with (
            patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Network forbidden")),
            patch.object(voice_pipeline, "SileroVADAnalyzer", side_effect=AssertionError("Gradium uses semantic turns")),
        ):
            session = voice_pipeline.VoiceSession(SmallWebRTCConnection(), read_gradium_config(GRADIUM_ENV))
            self.assertTrue(session.stt._enable_turn_detection)
            self.assertEqual(session.tts._settings.voice, "fixture-gradium-voice")
            self.assertEqual(session.llm._settings.model, "fixture-compute-model")
            self.assertEqual(session.llm._settings.max_tokens, 1024)
            self.assertEqual(session.llm._client.max_retries, 0)
            self.assertEqual(session.worker._params.audio_in_sample_rate, 16000)
            self.assertEqual(session.worker._params.audio_out_sample_rate, 48000)
            self.assertIsInstance(session.aggregators.user()._params.user_turn_strategies, ExternalUserTurnStrategies)
            self.assertIsNone(session.aggregators.user()._params.vad_analyzer)
            await session.close()
            self.assertTrue(session.llm._client.is_closed())

    async def test_general_compute_sends_documented_options_and_ignores_reasoning_deltas(self):
        llm = voice_pipeline.BoundedGeneralComputeLLMService(
            api_key="fixture-secret", base_url="https://api.generalcompute.com/v1", request_timeout=1,
            settings=OpenAILLMService.Settings(model="fixture-model", max_tokens=256),
        )

        class Stream:
            async def __aiter__(self):
                for text, reasoning in [(None, "private reasoning"), ("Visible reply.", None)]:
                    yield SimpleNamespace(usage=None, model=None, choices=[SimpleNamespace(
                        delta=SimpleNamespace(tool_calls=None, content=text, reasoning_content=reasoning),
                    )])
            async def close(self):
                pass

        try:
            params = llm.build_chat_completion_params({"messages": [{"role": "user", "content": "Hello"}]})
            self.assertTrue(params["stream"])
            self.assertEqual(params["max_tokens"], 256)
            self.assertFalse(set(params) & {"stream_options", "seed", "service_tier", "max_completion_tokens"})
            llm.get_chat_completions = AsyncMock(return_value=Stream())
            llm.start_ttfb_metrics = AsyncMock()
            llm.stop_ttfb_metrics = AsyncMock()
            llm.stop_ttfat_metrics = AsyncMock()
            llm.push_frame = AsyncMock()
            await llm._process_context(LLMContext())
            texts = [call.args[0].text for call in llm.push_frame.call_args_list if isinstance(call.args[0], LLMTextFrame)]
            self.assertEqual(texts, ["Visible reply."])
        finally:
            await llm._client.close()

    async def test_gradium_tts_drops_audio_and_words_from_interrupted_contexts(self):
        tts = voice_pipeline.BoundedGradiumTTSService(
            api_key="fixture-secret", request_timeout=1,
            settings=GradiumTTSService.Settings(voice="fixture-voice"),
        )

        class Socket:
            state = State.OPEN
            async def __aiter__(self):
                for context_id in ("interrupted", "active"):
                    yield json.dumps({"type": "audio", "client_req_id": context_id, "audio": base64.b64encode(bytes(480)).decode()})
                    yield json.dumps({"type": "text", "client_req_id": context_id, "text": "Hello", "start_s": 0.0})

        tts._websocket = Socket()
        tts.audio_context_available = lambda context_id: context_id == "active"
        tts.append_to_audio_context = AsyncMock()
        tts.add_word_timestamps = AsyncMock()
        await tts._receive_messages()
        self.assertEqual(tts.append_to_audio_context.await_count, 1)
        self.assertEqual(tts.append_to_audio_context.call_args.args[0], "active")
        self.assertEqual(tts.add_word_timestamps.call_args.args[1], "active")
        tts._websocket = None


class OfflineGradiumSTT(voice_pipeline.BoundedGradiumSTTService):
    """Drive the native Gradium semantic-turn handlers with recorded-shaped events."""

    async def _connect(self):
        pass

    async def _send_flush(self):
        self.flush_sent = True
        return True

    async def run_stt(self, audio):
        self.audio_seen = True
        for inactivity in (0.9, 0.1):
            await self._handle_step({"vad": [{"horizon_s": 3.0, "inactivity_prob": inactivity}]})
        await self._handle_text("Hello pipeline")
        await self._handle_step({"vad": [{"horizon_s": 3.0, "inactivity_prob": 0.9}]})
        # Model the server's flush acknowledgement. The native handler waits
        # briefly for trailing words before producing the final transcript.
        self._turn_phase = type(self._turn_phase).IDLE
        self.confirm_finalize()
        await self._handle_flushed()
        yield None


class GradiumWorkerIntegrationTests(pipeline_fixtures.WorkerIntegrationTests):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(voice_pipeline, "SmallWebRTCTransport", MemoryTransport),
            patch.object(voice_pipeline, "BoundedGradiumSTTService", OfflineGradiumSTT),
            patch.object(voice_pipeline, "BoundedGeneralComputeLLMService", FixtureLLM),
            patch.object(voice_pipeline, "BoundedGradiumTTSService", FixtureTTS),
        ]
        for replacement in self.patches:
            replacement.start()
        self.session = voice_pipeline.VoiceSession(FakeConnection(), read_gradium_config(GRADIUM_ENV))
        self.reported_errors = []
        self.session.reporter.sink = self.reported_errors.append
        self.started = asyncio.Event()

        @self.session.worker.event_handler("on_pipeline_started")
        async def started(worker, frame):
            self.started.set()

        self.task = asyncio.create_task(self.session.run())
        await asyncio.wait_for(self.started.wait(), timeout=3)

    async def test_provider_error_cancels_worker_and_never_relays_raw_error(self):
        await self.ready()
        self.session.llm.fail = True
        self.session.llm.failure_exception = APIStatusError(
            "fixture-secret rejected model",
            response=httpx.Response(404, request=httpx.Request("POST", "https://provider.invalid/v1")), body={},
        )
        await self.speak()
        await asyncio.wait_for(asyncio.shield(self.task), timeout=3)
        messages = self.session.transport.output().messages
        errors = [message for message in messages if message["type"] == "error"]
        self.assertTrue(errors[0]["data"]["error"].startswith("[PIPECAT:GENERALCOMPUTE:MODEL] "))
        self.assertEqual(self.reported_errors, [errors[0]["data"]["error"]])
        self.assertNotIn("fixture-secret", str(messages))
        self.assertTrue(self.session.connection.closed)

    async def test_semantic_turn_proposals_trigger_interruption_and_complete_user_turn(self):
        await self.ready()
        await self.speak()
        output = self.session.transport.output()
        await asyncio.wait_for(output.bot_output_ready.wait(), timeout=3)
        types = [message["type"] for message in output.messages]
        self.assertIn("bot-interrupted", types)
        self.assertIn("user-started-speaking", types)
        self.assertIn("user-stopped-speaking", types)
        self.assertTrue(self.session.stt.flush_sent)
        self.assertIn({"role": "user", "content": "Hello pipeline"}, self.session.llm.context_seen)


if __name__ == "__main__":
    unittest.main()
