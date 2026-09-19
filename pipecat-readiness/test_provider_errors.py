"""Provider failures stay useful without exposing provider text or credentials."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx
from openai import APIStatusError

from provider_errors import CATEGORIES, PROVIDERS, MESSAGES, FailureReporter, ProviderEventError, classify_failure


class ProviderErrorTests(unittest.TestCase):
    def frame(self, exception=None, error="fixture-secret private response", provider="SAMBANOVA", category=None):
        processor = object()
        return SimpleNamespace(exception=exception, error=error, processor=processor, category=category), {id(processor): provider}

    def http_error(self, status, body=None):
        return APIStatusError(
            "private fixture-secret from upstream",
            response=httpx.Response(status, request=httpx.Request("POST", "https://provider.invalid/v1")),
            body=body,
        )

    def test_actual_sambanova_http402_shape_is_quota_with_no_response_text(self):
        frame, providers = self.frame(self.http_error(402, {"message": "CREDITS_EXHAUSTED fixture-secret"}))
        failure = classify_failure(frame, providers)
        self.assertEqual((failure.provider, failure.category), ("SAMBANOVA", "QUOTA"))
        self.assertIn("remaining credits", failure.message)
        self.assertNotIn("fixture-secret", failure.wire_message)

    def test_other_provider_auth_model_voice_timeout_and_network_categories(self):
        cases = [
            ("DEEPGRAM", self.http_error(401), "AUTH"),
            ("SAMBANOVA", self.http_error(403), "AUTH"),
            ("SAMBANOVA", self.http_error(429), "QUOTA"),
            ("SAMBANOVA", self.http_error(404), "MODEL"),
            ("HUME", self.http_error(404), "VOICE"),
            ("HUME", TimeoutError("fixture-secret"), "TIMEOUT"),
            ("DEEPGRAM", httpx.ConnectError("fixture-secret"), "NETWORK"),
            ("GENERALCOMPUTE", self.http_error(404), "MODEL"),
            ("GENERALCOMPUTE", self.http_error(402), "QUOTA"),
            ("GRADIUM_STT", Exception("API key is revoked or expired"), "AUTH"),
            ("GRADIUM_TTS", Exception("Voice fixture-secret was not found"), "VOICE"),
        ]
        for provider, exception, category in cases:
            with self.subTest(provider=provider, category=category):
                frame, providers = self.frame(exception, provider=provider)
                failure = classify_failure(frame, providers)
                self.assertEqual((failure.provider, failure.category), (provider, category))
                self.assertNotIn("fixture-secret", failure.wire_message)

    def test_structured_http_status_takes_precedence_over_words_in_private_body(self):
        frame, providers = self.frame(self.http_error(402, {"message": "timeout fixture-secret"}))
        self.assertEqual(classify_failure(frame, providers).category, "QUOTA")

    def test_native_pipecat_category_and_unknown_fallback(self):
        frame, providers = self.frame(category=SimpleNamespace(value="authorization"))
        self.assertEqual(classify_failure(frame, providers).category, "AUTH")
        frame, _providers = self.frame()
        self.assertEqual(classify_failure(frame).wire_message, "[PIPECAT:PIPELINE:UNKNOWN] " + MESSAGES["PIPELINE:UNKNOWN"])

    def test_first_error_prints_once_and_later_errors_cannot_replace_it(self):
        frame, providers = self.frame(self.http_error(402))
        output = []
        reporter = FailureReporter(providers, output.append)
        first = reporter.report(frame)
        reporter.report(frame)
        frame.exception = TimeoutError("fixture-secret")
        self.assertIs(reporter.report(frame), first)
        self.assertEqual(output, [first.wire_message])

    def test_shared_browser_terminal_table_covers_every_supported_token(self):
        expected = {f"{provider}:{category}" for provider in PROVIDERS for category in CATEGORIES}
        self.assertEqual(set(MESSAGES), expected)
        self.assertTrue(all(isinstance(message, str) and message for message in MESSAGES.values()))

    def test_websocket_error_event_is_wrapped_without_losing_metadata(self):
        error = ProviderEventError(SimpleNamespace(code="invalid_api_key", description="fixture-secret"))
        self.assertIsInstance(error, Exception)
        self.assertIsNone(error.__traceback__)
        frame, providers = self.frame(error, provider="DEEPGRAM")
        self.assertEqual(classify_failure(frame, providers).category, "AUTH")


class ProviderCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepgram_callback_keeps_error_metadata_in_a_real_exception(self):
        from voice_pipeline import DiagnosticDeepgramSTTService

        service = DiagnosticDeepgramSTTService(api_key="fixture-secret")
        service.push_error = AsyncMock()
        service.stop_all_metrics = AsyncMock()
        await service._on_error(SimpleNamespace(code="invalid_api_key", description="fixture-secret"))
        error = service.push_error.call_args.kwargs["exception"]
        self.assertIsInstance(error, ProviderEventError)
        self.assertEqual(error.code, "invalid_api_key")
        self.assertNotIn("fixture-secret", service.push_error.call_args.kwargs["error_msg"])


if __name__ == "__main__":
    unittest.main()
