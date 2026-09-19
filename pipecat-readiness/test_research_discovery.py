"""Offline contracts for metadata-preserving paper discovery and Jev selection."""

import asyncio
import json
import unittest

import httpx

from research_discovery import arxiv_identity, select_papers
from research_search import acquire_sources, result_links

TEXT = "The research evaluates attention mechanisms for translation and reports a comparison against recurrent models. " * 60
URL_A = "https://arxiv.org/abs/1706.03762v7"
URL_B = "https://arxiv.org/abs/1810.04805"


def answer(value):
    return {"type": "choice", "choice": value, "confidence": 0.95}


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []

    def emit(self, name, **payload):
        self.events.append((name, payload))

    async def test_metadata_only_candidates_survive_without_becoming_evidence(self):
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["contents"]["extras"], {"links": 32})
            return httpx.Response(200, json={"results": [{"url": URL_A, "title": "Attention Is All You Need"}]})
        candidates = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            sources = await acquire_sources("Explain attention", "exa-key", self.emit,
                candidates=candidates, allow_empty=True, http=client)
        self.assertEqual(sources, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["textStatus"], "unavailable")
        self.assertIsNone(candidates[0]["sourceId"])

    async def test_links_are_scanned_before_text_truncation_and_are_public_only(self):
        row = {"url": "https://papers.example.org/project", "text": TEXT + " See " + URL_A,
               "extras": {"links": [URL_B, {"url": "http://127.0.0.1/private"}, {"href": "https://github.com/org/project"}]}}
        candidates = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": [row]}))) as client:
            sources = await acquire_sources("Paper question", "key", self.emit, candidates=candidates, http=client)
        self.assertEqual(len(sources[0]["text"]), 3200)
        self.assertNotIn(URL_A, sources[0]["text"])
        self.assertIn(URL_A, candidates[0]["links"])
        self.assertIn(URL_B, candidates[0]["links"])
        self.assertNotIn("http://127.0.0.1/private", candidates[0]["links"])
        self.assertEqual(result_links({"subpages": {"unexpected": True}}), [])

    async def test_direct_metadata_candidate_reaches_pdf_selection_without_text(self):
        def respond(request):
            payload = json.loads(request.content)
            selected = payload["state"]["candidates"][0]["candidateId"]
            return httpx.Response(200, json={"answers": {"first_paper": answer(selected), "second_paper": answer("none")}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {URL_A}", [], [{"url": URL_A, "title": "Attention", "links": []}],
                client, "jev-key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["text"], "")
        self.assertEqual(selected[0]["arxivId"], "1706.03762v7")
        self.assertEqual(selected[0]["paperId"], "arxiv-1706.03762")
        self.assertNotIn("jev-key", repr(self.events))

    async def test_nested_link_gets_its_own_identity_and_source_id(self):
        origin = "https://papers.example.org/project"
        source = {"id": "S1", "url": origin, "title": "Project landing page", "text": TEXT}
        seen = []
        def respond(request):
            seen.append(str(request.url))
            payload = json.loads(request.content)
            if request.url.host == "api.exa.ai":
                self.assertEqual(payload["extras"], {"links": 32})
                return httpx.Response(200, json={"results": [{"url": URL_A, "title": "Attention Is All You Need", "author": "Vaswani et al.", "text": TEXT}]})
            row = payload["state"]["candidates"][0]
            self.assertEqual(row["title"], "Attention Is All You Need")
            self.assertEqual(row["originTitle"], "Project landing page")
            return httpx.Response(200, json={"answers": {"first_paper": answer(row["candidateId"]), "second_paper": answer("none")}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Find the attention paper", [source], [{"url": origin, "title": "Project landing page", "sourceId": "S1", "links": [URL_A]}],
                client, "jev-key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected[0]["title"], "Attention Is All You Need")
        self.assertEqual(selected[0]["id"], "S2")
        self.assertEqual(len(seen), 2)

    async def test_top_level_identity_wins_over_an_earlier_bibliography_link(self):
        source = {"id": "S1", "url": URL_A, "title": "Attention Is All You Need", "text": TEXT}
        def respond(request):
            self.assertEqual(request.url.host, "api.typesafe.ai")  # No redundant Exa contents call.
            candidate = json.loads(request.content)["state"]["candidates"][0]
            self.assertEqual(candidate["identityStatus"], "direct")
            self.assertEqual(candidate["title"], "Attention Is All You Need")
            return httpx.Response(200, json={"answers": {"first_paper": answer(candidate["candidateId"]), "second_paper": answer("none")}})
        rows = [{"url": "https://papers.example.org/referrer", "title": "Other paper", "links": [URL_A]},
                {"url": URL_A, "title": "Attention Is All You Need", "sourceId": "S1", "links": []}]
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Explain attention research", [source], rows, client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected[0]["id"], "S1")
        self.assertEqual(selected[0]["text"], TEXT)

    async def test_unrelated_bibliography_does_not_replace_explicit_paper(self):
        origin = "https://papers.example.org/specific-paper"
        seen = []
        def respond(request):
            seen.append(str(request.url))
            if request.url.host == "api.exa.ai":
                return httpx.Response(200, json={"results": [{"url": URL_B, "title": "BERT", "text": TEXT}]})
            state = json.loads(request.content)["state"]
            self.assertEqual(state["candidates"][0]["title"], "BERT")
            self.assertEqual(state["candidates"][0]["originTitle"], "An unrelated biology paper")
            return httpx.Response(200, json={"answers": {"first_paper": answer("none"), "second_paper": answer("none")}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {origin}", [], [{"url": origin, "title": "An unrelated biology paper", "links": [URL_B]}],
                client, "jev-key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected, [])
        self.assertEqual(len(seen), 2)  # No fallback substitution after an explicit URL.

    async def test_jev_cannot_select_an_undiscovered_id_or_url(self):
        for value in ("forged-id", "https://evil.example/paper"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
                    json={"answers": {"first_paper": answer(value), "second_paper": answer("none")}}))) as client:
                selected = await select_papers(f"Explain {URL_A}", [], [{"url": URL_A, "title": "Attention", "links": []}],
                    client, "key", "jev-latest", self.emit, "exa-key")
            self.assertEqual(selected, [])

    async def test_comparison_gets_two_distinct_jev_relevant_papers(self):
        def respond(request):
            candidates = json.loads(request.content)["state"]["candidates"]
            # Independent choices can tie; independent relevance scores safely
            # permit the other paper without guessing from result ordering.
            values = {"first_paper": answer(candidates[0]["candidateId"]), "second_paper": answer(candidates[0]["candidateId"])}
            values.update({"relevant_" + row["candidateId"]: {"type": "noul", "noul": 0.95} for row in candidates})
            return httpx.Response(200, json={"answers": values})
        rows = [{"url": URL_A, "title": "Attention", "links": []}, {"url": URL_B, "title": "BERT", "links": []}]
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Compare {URL_A} and {URL_B}", [], rows, client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({item["paperId"] for item in selected}), 2)
        self.assertEqual(len({item["id"] for item in selected}), 2)

    async def test_one_arxiv_fallback_search_can_rescue_empty_initial_results(self):
        requests = []
        def respond(request):
            requests.append(str(request.url))
            payload = json.loads(request.content)
            if request.url.host == "api.exa.ai":
                self.assertEqual(payload["includeDomains"], ["arxiv.org"])
                return httpx.Response(200, json={"results": [{"url": URL_A, "title": "Attention Is All You Need"}]})
            candidate_id = payload["state"]["candidates"][0]["candidateId"]
            return httpx.Response(200, json={"answers": {"first_paper": answer(candidate_id), "second_paper": answer("none")}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Find attention research", [], [], client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(requests), 2)

    async def test_cancellation_propagates(self):
        entered = asyncio.Event()
        async def blocked(request):
            entered.set()
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
            task = asyncio.create_task(select_papers(f"Explain {URL_A}", [], [{"url": URL_A, "links": []}],
                client, "key", "jev-latest", self.emit, "exa-key"))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    def test_canonical_identity_and_host_allowlist(self):
        for url in (URL_A, "https://arxiv.org/pdf/1706.03762v7.pdf", "https://arxiv.org/html/1706.03762v7", "https://export.arxiv.org/abs/1706.03762v7"):
            self.assertEqual(arxiv_identity(url)["arxivId"], "1706.03762v7")
        for url in ("https://arxiv.org.evil.example/abs/1706.03762", "https://user:password@arxiv.org/abs/1706.03762", "http://127.0.0.1/paper"):
            self.assertIsNone(arxiv_identity(url))


if __name__ == "__main__":
    unittest.main()
