"""Offline search contracts: real evidence, bounded extraction, safe failures."""

import asyncio
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

import httpx

from research_search import ExaSearchError, acquire_sources, public_url

TEXT = "The study evaluates retrieval methods across multiple research tasks and compares measured outcomes with a baseline. " * 50


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []

    def emit(self, name, **payload):
        self.events.append((name, payload))

    async def test_search_registers_only_bounded_extracted_evidence(self):
        def respond(request):
            self.assertEqual(str(request.url), "https://api.exa.ai/search")
            self.assertEqual(request.headers["x-api-key"], "fixture-secret")
            self.assertEqual(json.loads(request.content), {"query": "retrieval papers", "category": "publication", "numResults": 5, "contents": {"text": True}})
            return httpx.Response(200, json={"results": [{"url": f"https://papers.example.org/{i}", "title": f"Paper {i}", "author": "Author", "publishedDate": "2026-01-01", "text": TEXT} for i in range(8)]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            sources = await acquire_sources("retrieval papers", "fixture-secret", self.emit, http=client)
            self.assertFalse(client.is_closed)
        self.assertEqual(len(sources), 5)
        self.assertEqual(sum(len(source["text"]) for source in sources), 16000)
        self.assertEqual([source["id"] for source in sources], [f"S{i}" for i in range(1, 6)])
        for source in sources:
            self.assertTrue(TEXT.startswith(source["text"]))
            self.assertEqual(source["sha256"], sha256(source["text"].encode()).hexdigest())
            self.assertIsNone(source["path"])
            self.assertIsNone(source["startLine"])
            self.assertIn("not verified", source["coverage"])
        self.assertEqual(self.events[0][0], "search.started")
        self.assertEqual(self.events[-1], ("search.completed", {"count": 8, "usableCount": 5, "provider": "Exa"}))
        self.assertNotIn("fixture-secret", repr(self.events))

    async def test_url_extraction_and_abstract_coverage(self):
        def respond(request):
            self.assertEqual(str(request.url), "https://api.exa.ai/contents")
            self.assertEqual(json.loads(request.content), {"urls": ["https://arxiv.org/abs/1234.5678"], "text": True})
            return httpx.Response(200, json={"results": [{"url": "https://arxiv.org/abs/1234.5678", "text": "Abstract " + TEXT[:500]}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            sources = await acquire_sources("Explain this paper", "key", self.emit, urls=["https://arxiv.org/abs/1234.5678#section"], http=client)
        self.assertIn("Abstract only", sources[0]["coverage"])
        self.assertEqual(self.events[1][0], "source.fetch.started")

    async def test_arxiv_filtered_discovery_uses_compatible_search_payload(self):
        candidates = []
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["includeDomains"], ["arxiv.org"])
            self.assertEqual(payload["numResults"], 8)
            self.assertNotIn("category", payload)
            return httpx.Response(200, json={"results": [{"url": "https://arxiv.org/abs/2411.06165", "title": "An arXiv paper"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            sources = await acquire_sources("Find supporting evidence", "key", self.emit, http=client,
                include_domains=["arxiv.org"], candidates=candidates, allow_empty=True)
        self.assertEqual(sources, [])
        self.assertEqual(len(candidates), 1)

    async def test_metadata_summary_bad_text_and_duplicates_are_not_evidence(self):
        rows = [
            {"url": "https://papers.example.org/metadata", "summary": TEXT},
            {"url": "https://papers.example.org/short", "text": "Too short."},
            {"url": "https://papers.example.org/html", "text": "<!DOCTYPE html>" + TEXT},
            {"url": "http://127.0.0.1/private", "text": TEXT},
            {"url": "https://papers.example.org/real", "text": TEXT},
            {"url": "https://papers.example.org/real#duplicate", "text": TEXT},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": rows}))) as client:
            sources = await acquire_sources("Question", "key", self.emit, http=client)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], "https://papers.example.org/real")

    async def test_no_content_is_actionable_without_claims(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": [{"url": "https://papers.example.org/one", "title": "Metadata only", "summary": TEXT}]}))) as client:
            with self.assertRaises(ExaSearchError) as caught:
                await acquire_sources("Question", "key", self.emit, http=client)
        self.assertEqual(caught.exception.code, "no_content")
        self.assertIn("paste an excerpt", str(caught.exception))
        self.assertEqual(self.events[-1][1]["usableCount"], 0)

    async def test_provider_errors_are_sanitized(self):
        for status, code in [(401, "authentication"), (402, "quota"), (429, "rate_limit"), (503, "provider_error"), (302, "provider_error")]:
            with self.subTest(status=status):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _, status=status: httpx.Response(status, text="secret-key-and-provider-details"))) as client:
                    with self.assertRaises(ExaSearchError) as caught:
                        await acquire_sources("Question", "secret-key", self.emit, http=client)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("secret-key", str(caught.exception))

    async def test_bad_json_and_excess_response_are_safe(self):
        for body, code in [(b"private invalid response", "invalid_response"), (b"x" * 2_000_001, "response_too_large")]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _, body=body: httpx.Response(200, content=body))) as client:
                with self.assertRaises(ExaSearchError) as caught:
                    await acquire_sources("Question", "key", self.emit, http=client)
            self.assertEqual(caught.exception.code, code)

    async def test_timeout_is_bounded_and_cancellation_propagates(self):
        entered = asyncio.Event()
        async def wait_forever(request):
            entered.set()
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(wait_forever)) as client:
            with patch("research_search.TOTAL_TIMEOUT", 0.01):
                with self.assertRaises(ExaSearchError) as caught:
                    await acquire_sources("Question", "key", self.emit, http=client)
                self.assertEqual(caught.exception.code, "timeout")
            task = asyncio.create_task(acquire_sources("Question", "key", self.emit, http=client))
            await entered.wait()
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_unsafe_urls_rejected_before_network_or_event(self):
        bad_urls = ["file:///etc/passwd", "http://localhost/a", "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.1/a", "http://169.254.169.254/latest", "https://user:secret@arxiv.org/abs/1", "https://papers.example.org:7860/a", "http://2130706433/", "http://0x7f000001/", "http://host.internal/a", "https://arxiv.org\\@localhost/a", "https://arxiv.org/\nfoo"]
        for url in bad_urls:
            with self.subTest(url=url):
                with self.assertRaises(ExaSearchError):
                    await acquire_sources("Question", "key", self.emit, urls=[url])
        self.assertEqual(self.events, [])
        self.assertEqual(public_url("https://ARXIV.ORG/abs/1234#section"), "https://arxiv.org/abs/1234")


if __name__ == "__main__":
    unittest.main()
