"""Offline checks: no microphone, external network, or billable provider calls."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from server import create_app, configure_safe_logging, main, run_local_server
from voice_config import ConfigurationError, REQUIRED_VARIABLES, read_config

configure_safe_logging()

FIXTURE_ENV = {
    "DEEPGRAM_API_KEY": "fixture-deepgram-secret",
    "SAMBANOVA_API_KEY": "fixture-sambanova-secret",
    "SAMBANOVA_MODEL": "fixture-model",
    "HUME_API_KEY": "fixture-hume-secret",
    "HUME_VOICE_ID": "fixture-voice",
}
HEADERS = {"x-pipecat-proxy": "practice-web"}
OFFER = {"type": "offer", "sdp": "v=0\r\n"}


class FakeConnection:
    pc_id = "fixture-peer"

    def __init__(self):
        self.events = {}
        self.closed = False

    def event_handler(self, name):
        def register(callback):
            self.events.setdefault(name, []).append(callback)
            return callback
        return register

    async def disconnect(self):
        if self.closed:
            return
        self.closed = True
        for callback in self.events.get("closed", []):
            await callback(self)


class FakeSession:
    def __init__(self, connection, config):
        self.connection = connection
        self.finished = asyncio.Event()
        self.close_calls = 0

    async def run(self):
        await self.finished.wait()

    async def close(self):
        self.close_calls += 1
        self.finished.set()
        await self.connection.disconnect()


class FakeHandler:
    def __init__(self):
        self.connection = None
        self.requests = []
        self.patches = []
        self.close_calls = 0

    async def handle_web_request(self, request, webrtc_connection_callback):
        self.requests.append(request)
        if not request.pc_id:
            self.connection = FakeConnection()
            await webrtc_connection_callback(self.connection)
        return {"sdp": "fixture-answer", "type": "answer", "pc_id": self.connection.pc_id}

    async def handle_patch_request(self, request):
        self.patches.append(request)

    async def close(self):
        self.close_calls += 1
        if self.connection:
            await self.connection.disconnect()


class ConfigTests(unittest.TestCase):
    def test_missing_variables_are_specific_to_modular_route(self):
        self.assertEqual(read_config(FIXTURE_ENV).model, "fixture-model")
        with self.assertRaises(ConfigurationError) as result:
            read_config({"HUME_API_KEY": "fixture-hume-secret"})
        self.assertIn("DEEPGRAM_API_KEY", result.exception.missing)
        self.assertNotIn("HUME_SECRET_KEY", result.exception.missing)
        self.assertNotIn("HUME_CONFIG_ID", result.exception.missing)
        self.assertNotIn("fixture-hume-secret", str(result.exception))

    def test_rejects_unsafe_provider_url_and_invalid_timeout_without_echoing_values(self):
        for update in [
            {"SAMBANOVA_BASE_URL": "https://fixture-secret@host.example/v1"},
            {"SAMBANOVA_BASE_URL": "http://host.example/v1"},
            {"PROVIDER_TIMEOUT_MS": "fixture-secret"},
            {"PROVIDER_TIMEOUT_MS": "120001"},
        ]:
            with self.subTest(update=tuple(update)):
                with self.assertRaises(ConfigurationError) as result:
                    read_config(FIXTURE_ENV | update)
                self.assertNotIn("fixture-secret", str(result.exception))

    def test_startup_failure_explains_bind_problem_without_raw_exception(self):
        output = io.StringIO()
        with (
            patch("server.configure_safe_logging"),
            patch("server.load_practice_environment"),
            patch("server.create_app", return_value=object()),
            patch("server.run_local_server", side_effect=SystemExit(3)),
            redirect_stderr(output), redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 3)
        self.assertIn("port 7860", output.getvalue())
        self.assertIn("local listening socket", output.getvalue())

    def test_initialization_failure_hides_exception_and_points_to_dependency_setup(self):
        output = io.StringIO()
        with (
            patch("server.configure_safe_logging"),
            patch("server.load_practice_environment"),
            patch("server.create_app", side_effect=ValueError("fixture-secret")),
            redirect_stderr(output), redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn("uv sync", output.getvalue())
        self.assertNotIn("fixture-secret", output.getvalue())

    def test_ready_message_is_only_written_by_the_after_bind_callback(self):
        output = io.StringIO()

        def bound_server(server):
            self.assertNotIn("is ready", output.getvalue())
            # Uvicorn calls this hook after loop.create_server succeeds.
            server._log_started_message([])
            server.started = True

        with patch("uvicorn.Server.run", autospec=True, side_effect=bound_server), redirect_stdout(output):
            run_local_server(object())
        self.assertIn("is ready", output.getvalue())
        self.assertIn("Keep this terminal running", output.getvalue())

    def test_normal_server_exit_is_explicitly_reported_as_stopped(self):
        output = io.StringIO()
        with (
            patch("server.configure_safe_logging"),
            patch("server.load_practice_environment"),
            patch("server.create_app", return_value=object()),
            patch("server.run_local_server"),
            redirect_stdout(output),
        ):
            main()
        self.assertIn("Initializing", output.getvalue())
        self.assertIn("backend stopped", output.getvalue())
        self.assertNotIn("is ready", output.getvalue())


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.environment = dict(FIXTURE_ENV)
        self.handler = FakeHandler()
        self.app = create_app(environment=self.environment, handler=self.handler, session_factory=FakeSession)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 1234)),
            base_url="http://127.0.0.1:7860",
            headers=HEADERS,
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def test_missing_config_health_and_offer_do_not_start_a_session(self):
        self.environment.clear()
        health = await self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.json()["configured"])
        self.assertEqual(health.json()["missing"], list(REQUIRED_VARIABLES))
        response = await self.client.post("/api/offer", json=OFFER)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MISSING_CONFIG")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(self.handler.requests, [])

    async def test_web_origins_and_missing_proxy_header_are_rejected(self):
        response = await self.client.get("/health", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.get("/health", headers={"x-pipecat-proxy": ""})
        self.assertEqual(response.status_code, 403)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, client=("192.0.2.1", 1234)),
            base_url="http://127.0.0.1:7860", headers=HEADERS,
        ) as external:
            response = await external.get("/health")
            self.assertEqual(response.status_code, 403)

    async def test_rejected_request_input_is_not_echoed(self):
        response = await self.client.post("/api/offer", json={"sdp": "fixture-secret", "type": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("fixture-secret", response.text)
        response = await self.client.post("/api/offer", content="fixture-secret")
        self.assertEqual(response.status_code, 415)
        response = await self.client.post("/api/offer", json={"sdp": "x" * 256_001, "type": "offer"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.handler.requests, [])

    async def test_simultaneous_offers_only_create_one_session(self):
        responses = await asyncio.gather(*[self.client.post("/api/offer", json=OFFER) for _ in range(2)])
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(len(self.handler.requests), 1)
        health = await self.client.get("/health")
        self.assertEqual(health.json()["activeSessions"], 1)
        for value in FIXTURE_ENV.values():
            self.assertNotIn(value, health.text)

    async def test_renegotiation_and_patch_keep_the_existing_session(self):
        await self.client.post("/api/offer", json=OFFER)
        session = self.app.state.sessions.session
        response = await self.client.post("/api/offer", json=OFFER | {"pc_id": "fixture-peer", "restart_pc": True})
        self.assertEqual(response.status_code, 200)
        self.assertIs(self.app.state.sessions.session, session)
        response = await self.client.patch("/api/offer", json={
            "pc_id": "fixture-peer",
            "candidates": [{"candidate": "", "sdp_mid": "0", "sdp_mline_index": 0}],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.handler.patches[0].candidates[0].candidate, "")
        response = await self.client.patch("/api/offer", json={"pc_id": "wrong-peer", "candidates": []})
        self.assertEqual(response.status_code, 404)

    async def test_disconnect_frees_slot_and_shutdown_closes_the_next_session(self):
        await self.client.post("/api/offer", json=OFFER)
        first_session = self.app.state.sessions.session
        first_task = self.app.state.sessions.task
        await first_session.connection.disconnect()
        await first_task
        self.assertEqual(self.app.state.sessions.active_sessions, 0)
        response = await self.client.post("/api/offer", json=OFFER)
        self.assertEqual(response.status_code, 200)
        second_session = self.app.state.sessions.session
        second_task = self.app.state.sessions.task
        await self.app.state.sessions.close()
        self.assertTrue(second_task.done())
        self.assertTrue(second_session.connection.closed)
        self.assertEqual(self.app.state.sessions.active_sessions, 0)

    async def test_construction_failure_closes_connection_and_hides_provider_error(self):
        def fail(_connection, _config):
            raise ValueError("provider rejected fixture-secret")
        self.app.state.sessions.session_factory = fail
        response = await self.client.post("/api/offer", json=OFFER)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "CONNECTION_FAILED")
        self.assertNotIn("fixture-secret", response.text)
        self.assertTrue(self.handler.connection.closed)
        self.assertEqual(self.app.state.sessions.active_sessions, 0)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_services_construct_in_order_and_close_without_api_calls(self):
        from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
        from voice_pipeline import VoiceSession

        with patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Network is forbidden in this test")):
            connection = SmallWebRTCConnection()
            session = VoiceSession(connection, read_config(FIXTURE_ENV | {"DEEPGRAM_MODEL": "fixture-stt-model"}))
            processors = session.pipeline.processors
            self.assertLess(processors.index(session.stt), processors.index(session.aggregators.user()))
            self.assertLess(processors.index(session.aggregators.user()), processors.index(session.llm))
            self.assertLess(processors.index(session.llm), processors.index(session.tts))
            self.assertLess(processors.index(session.tts), processors.index(session.transport.output()))
            self.assertEqual(session.stt._settings.model, "fixture-stt-model")
            self.assertEqual(session.llm._client.max_retries, 0)
            self.assertEqual(session.llm._client.timeout.read, 60)
            self.assertEqual(session.worker._params.audio_out_sample_rate, 48000)
            self.assertEqual(session.context.get_messages(), [])
            self.assertIn("one or two short sentences", session.llm._settings.system_instruction)
            await session.close()
            await session.close()
            self.assertTrue(session.llm._client.is_closed())
            self.assertTrue(session.tts._http_client.is_closed)

    async def test_raw_provider_errors_are_replaced_before_rtvi_sends_them(self):
        from pipecat.frames.frames import ErrorFrame
        from voice_pipeline import SafeRTVIProcessor, SAFE_PIPELINE_ERROR
        from provider_errors import FailureReporter

        rtvi = SafeRTVIProcessor(reporter=FailureReporter(sink=lambda message: None))
        rtvi.push_transport_message = AsyncMock()
        await rtvi._send_error_frame(ErrorFrame(error="fixture-secret provider body", fatal=False))
        message = rtvi.push_transport_message.call_args.args[0]
        self.assertEqual(message.data.error, SAFE_PIPELINE_ERROR)
        self.assertTrue(message.data.fatal)

    async def test_sambanova_stream_has_a_total_deadline(self):
        from pipecat.services.sambanova.llm import SambaNovaLLMService
        from voice_pipeline import BoundedSambaNovaLLMService

        async def stalled(_self, _context):
            await asyncio.Event().wait()

        llm = BoundedSambaNovaLLMService(api_key="fixture-secret", request_timeout=0.01)
        try:
            with patch.object(SambaNovaLLMService, "_process_context", stalled):
                with self.assertRaises(TimeoutError):
                    await llm._process_context(None)
        finally:
            await llm._client.close()


if __name__ == "__main__":
    unittest.main()
