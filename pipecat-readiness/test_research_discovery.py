"""Offline contracts for metadata-preserving paper discovery and Jev selection."""

import asyncio
import json
import unittest

import httpx

from research_discovery import arxiv_identity, select_papers
from research_limits import MAX_READING_PAPERS
from research_search import acquire_sources, result_links

TEXT = "The research evaluates attention mechanisms for translation and reports a comparison against recurrent models. " * 60
URL_A = "https://arxiv.org/abs/1706.03762v7"
URL_B = "https://arxiv.org/abs/1810.04805"


def answer(value):
    return {"type": "choice", "choice": value, "confidence": 0.95}


def decision(payload, *, scope="single", count=1, accepted=None):
    candidates = payload["state"]["candidates"]
    allowed = {row["candidateId"] for row in candidates} if accepted is None else set(accepted)
    values = {"reading_scope": answer(scope), "paper_count": answer(str(count))}
    for row in candidates:
        for kind in ("relevant_", "identity_"):
            values[kind + row["candidateId"]] = {"type": "noul", "noul": 0.95 if row["candidateId"] in allowed else 0.05}
    return httpx.Response(200, json={"answers": values})


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
            return decision(payload)
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
            return decision(payload)
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
            return decision(json.loads(request.content))
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
            self.assertEqual(state["requested_paper_metadata"][0]["title"], "An unrelated biology paper")
            return decision(json.loads(request.content), accepted=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {origin}", [], [{"url": origin, "title": "An unrelated biology paper", "links": [URL_B]}],
                client, "jev-key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected, [])
        self.assertEqual(len(seen), 4)  # A bounded preprint lookup is allowed, but identity still fails.

    async def test_jev_cannot_select_an_undiscovered_id_or_url(self):
        for value in ("forged-id", "https://evil.example/paper"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,
                    json={"answers": {"first_paper": answer(value), "second_paper": answer("none")}}))) as client:
                selected = await select_papers(f"Explain {URL_A}", [], [{"url": URL_A, "title": "Attention", "links": []}],
                    client, "key", "jev-latest", self.emit, "exa-key")
            self.assertEqual(selected, [])

    async def test_comparison_gets_two_distinct_jev_relevant_papers(self):
        def respond(request):
            return decision(json.loads(request.content), scope="multiple", count=2)
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
            return decision(payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Find attention research", [], [], client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(requests), 3)

    async def test_publisher_url_without_text_resolves_to_same_arxiv_paper(self):
        origin = "https://doi.org/10.1000/attention"
        metadata = [{"url": origin, "title": "Attention Is All You Need", "author": "Vaswani et al.", "links": []}]
        requests = []
        def respond(request):
            requests.append(str(request.url))
            payload = json.loads(request.content)
            if request.url.host == "api.exa.ai":
                self.assertEqual(payload["includeDomains"], ["arxiv.org"])
                self.assertIn("Attention Is All You Need", payload["query"])
                self.assertEqual(payload["numResults"], 8)
                return httpx.Response(200, json={"results": [{"url": URL_A, "title": "Attention Is All You Need", "author": "Vaswani et al."}]})
            self.assertEqual(payload["state"]["requested_paper_metadata"][0]["title"], metadata[0]["title"])
            return decision(payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {origin}", [], metadata, client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], URL_A)
        self.assertEqual(selected[0]["text"], "")
        self.assertIn("specific requested paper", selected[0]["selectionReason"])

    async def test_topic_scope_selects_more_than_two_without_plural_keyword(self):
        rows = [{"url": f"https://arxiv.org/abs/2401.0000{i}", "title": f"Attention study {i}", "links": []} for i in range(1, 5)]
        def respond(request):
            payload = json.loads(request.content)
            self.assertIn("reading_scope", payload["questions"])
            self.assertEqual(request.url.host, "api.typesafe.ai")
            return decision(payload, scope="topic", count=4)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("What evidence supports sliding attention?", [], rows, client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 4)
        self.assertEqual(len({item["id"] for item in selected}), 4)

    async def test_title_specific_scope_keeps_one_even_with_high_count_answer(self):
        rows = [{"url": URL_A, "title": "Attention Is All You Need", "links": []}, {"url": URL_B, "title": "BERT", "links": []}]
        def respond(request):
            return decision(json.loads(request.content), scope="single", count=5)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers('Analyze "Attention Is All You Need" and its comparison with prior work', [], rows,
                client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["arxivId"], "1706.03762v7")

    async def test_runner_reading_scope_is_respected_and_candidate_bound_is_eight(self):
        rows = [{"url": f"https://arxiv.org/abs/2401.000{i:02d}", "title": f"Attention study {i}", "links": []} for i in range(12)]
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(len(payload["state"]["candidates"]), 8)
            self.assertNotIn("reading_scope", payload["questions"])
            return decision(payload, scope="single", count=5)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Survey attention evidence", [], rows, client, "key", "jev-latest", self.emit, "exa-key", reading_scope="topic")
        self.assertEqual(len(selected), MAX_READING_PAPERS)

    async def test_topic_fallback_fills_initial_two_with_additional_jev_relevant_papers(self):
        rows = [{"url": URL_A, "title": "Attention", "links": []}, {"url": URL_B, "title": "BERT", "links": []}]
        seen = []
        def respond(request):
            payload = json.loads(request.content)
            seen.append(str(request.url))
            if request.url.host == "api.exa.ai":
                self.assertEqual(payload["includeDomains"], ["arxiv.org"])
                self.assertEqual(payload["query"], "Survey attention evidence")
                return httpx.Response(200, json={"results": [
                    {"url": "https://arxiv.org/abs/2401.00001", "title": "Attention followup"},
                    {"url": "https://arxiv.org/abs/2401.00002", "title": "Attention evaluation"}]})
            return decision(payload, scope="topic", count=4)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Survey attention evidence", [], rows, client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 4)
        self.assertEqual(len(seen), 3)

    async def test_exa_failure_preserves_safe_actionable_reason(self):
        def respond(request):
            if request.url.host == "api.exa.ai":
                return httpx.Response(402, text="private-provider-details-and-secret")
            return decision(json.loads(request.content), scope="topic", count=3)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers("Survey attention evidence", [], [], client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected, [])
        failed = [payload for name, payload in self.events if name == "paper.selection.failed"]
        self.assertEqual(failed[0]["code"], "quota")
        self.assertIn("Exa search credits", failed[0]["message"])
        completed = [payload for name, payload in self.events if name == "paper.selection.completed"]
        self.assertEqual(completed[0]["reason"], failed[0]["message"])
        self.assertNotIn("private-provider", repr(self.events))

    async def test_high_relevance_cannot_override_rejected_paper_identity(self):
        def respond(request):
            payload = json.loads(request.content)
            response = decision(payload)
            values = response.json()
            candidate_id = payload["state"]["candidates"][0]["candidateId"]
            values["answers"]["identity_" + candidate_id] = {"type": "noul", "noul": 0.2}
            return httpx.Response(200, json=values)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {URL_A}", [], [{"url": URL_A, "title": "Attention", "links": []}],
                client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(selected, [])
        rejected = [payload for name, payload in self.events if name == "paper.selection.candidate"]
        self.assertEqual(rejected[0]["accepted"], False)
        self.assertEqual(rejected[0]["relevance"], 0.95)

    async def test_arxiv_doi_metadata_reaches_pdf_without_broad_search(self):
        doi = "https://doi.org/10.48550/arxiv.2411.06165"
        def respond(request):
            self.assertEqual(request.url.host, "api.typesafe.ai")
            return decision(json.loads(request.content))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            selected = await select_papers(f"Explain {doi}", [], [{"url": doi, "title": "A paper", "links": []}],
                client, "key", "jev-latest", self.emit, "exa-key")
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], "https://arxiv.org/abs/2411.06165")
        self.assertEqual(selected[0]["text"], "")

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
        for url in ("https://doi.org/10.48550/arXiv.1706.03762v7", "https://dx.doi.org/10.48550/arxiv.1706.03762v7"):
            self.assertEqual(arxiv_identity(url)["arxivId"], "1706.03762v7")
        self.assertIsNone(arxiv_identity("https://doi.org/10.1000/1706.03762"))


if __name__ == "__main__":
    unittest.main()
