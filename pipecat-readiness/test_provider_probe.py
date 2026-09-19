"""Provider-probe diagnostics must never print response bodies or credentials."""
import json
import base64
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from provider_probe import failure, gradium_stt, gradium_tts, run


class ProbeTests(unittest.TestCase):
    def test_credits_and_payment_method_failures_are_distinguished_without_raw_text(self):
        for message, reason in [
            ("fixture-secret: CREDITS_EXHAUSTED. You are out of credits.", "CREDITS_EXHAUSTED"),
            ("A payment method is required; fixture-secret", "PAYMENT_METHOD_REQUIRED"),
        ]:
            error = Exception(message)
            error.status_code = 402
            result = failure("sambanova", error)
            self.assertEqual(result["category"], "QUOTA")
            self.assertEqual(result["billingReason"], reason)
            self.assertEqual(result["httpStatus"], 402)
            self.assertNotIn("fixture-secret", json.dumps(result))

    def test_auth_and_voice_errors_hide_response_contents(self):
        for provider, status, category in [("deepgram", 401, "AUTH"), ("hume", 404, "VOICE")]:
            error = Exception("fixture-secret")
            error.status_code = status
            result = failure(provider, error)
            self.assertEqual(result["category"], category)
            self.assertNotIn("fixture-secret", json.dumps(result))

    def test_timeout_remains_a_fixed_category(self):
        result = failure("sambanova", TimeoutError("fixture-secret"))
        self.assertEqual(result["category"], "TIMEOUT")
        self.assertNotIn("fixture-secret", json.dumps(result))

    def test_socket_resolution_failure_is_a_safe_network_error(self):
        import socket
        result = failure("gradium-stt", socket.gaierror("fixture-secret"))
        self.assertEqual(result["category"], "NETWORK")
        self.assertNotIn("fixture-secret", json.dumps(result))


class FakeWebsocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return json.dumps(next(self.messages))


class GradiumProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = SimpleNamespace(stt_url="wss://api.gradium.ai/api/speech/asr",
            tts_url="wss://api.gradium.ai/api/speech/tts", gradium_key="fixture-secret",
            voice_id="fixture-voice", timeout_seconds=1)

    async def test_stt_requires_ready_and_end_confirmation_without_transcribing_speech(self):
        socket = FakeWebsocket([{"type": "ready", "sample_rate": 24000},
                                {"type": "step"}, {"type": "end_of_stream"}])
        with patch("websockets.asyncio.client.connect", return_value=socket):
            result = await gradium_stt(self.config)
        self.assertTrue(result["ok"])
        self.assertTrue(socket.closed)
        self.assertEqual(socket.sent[0]["input_format"], "pcm_16000")
        self.assertEqual(result["inputSampleRate"], 16000)
        self.assertEqual(result["reportedSampleRate"], 24000)
        self.assertEqual(base64.b64decode(socket.sent[1]["audio"]), bytes(3200))
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertIn("no spoken transcription", result["note"])

    async def test_tts_counts_only_completed_48khz_audio(self):
        socket = FakeWebsocket([{"type": "ready", "sample_rate": 48000},
            {"type": "audio", "audio": base64.b64encode(bytes(960)).decode()},
            {"type": "end_of_stream"}])
        with patch("websockets.asyncio.client.connect", return_value=socket):
            result = await gradium_tts(self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(result["audioBytes"], 960)
        self.assertEqual(socket.sent[0]["voice_id"], "fixture-voice")
        self.assertTrue(socket.closed)

    async def test_terminal_error_and_wrong_audio_rate_are_not_success(self):
        for messages, category in [
            ([{"type": "error", "message": "API key is revoked or expired fixture-secret", "code": 1008}], "AUTH"),
            ([{"type": "ready", "sample_rate": 16000}], "PROTOCOL"),
            ([{"type": "ready", "sample_rate": 48000},
              {"type": "audio", "audio": base64.b64encode(bytes(960)).decode()},
              {"type": "error", "message": "Insufficient credits fixture-secret", "code": 1008}], "QUOTA"),
        ]:
            socket = FakeWebsocket(messages)
            with patch("websockets.asyncio.client.connect", return_value=socket):
                try:
                    await gradium_tts(self.config)
                except Exception as error:
                    result = failure("gradium-tts", error)
                else:
                    self.fail("A rejected or incomplete stream must not pass")
            self.assertFalse(result["ok"])
            self.assertEqual(result["category"], category)
            self.assertNotIn("fixture-secret", json.dumps(result))
            self.assertTrue(socket.closed)

    async def test_gradium_stack_never_probes_legacy_services(self):
        providers = {name: AsyncMock(return_value={"provider": name, "ok": True})
                     for name in ("gradium_stt", "generalcompute", "gradium_tts")}
        output = StringIO()
        with patch("provider_probe.load_practice_environment"), \
             patch("provider_probe.read_gradium_config", return_value=self.config), \
             patch("provider_probe.read_config", side_effect=AssertionError("Wrong stack")), \
             patch.multiple("provider_probe", **providers), redirect_stdout(output):
            self.assertEqual(await run("all", "gradium"), 0)
        for probe in providers.values():
            probe.assert_awaited_once()
        self.assertNotIn("fixture-secret", output.getvalue())
        with patch("provider_probe.load_practice_environment", side_effect=AssertionError("Wrong stack")), redirect_stdout(StringIO()):
            self.assertEqual(await run("sambanova", "gradium"), 1)
