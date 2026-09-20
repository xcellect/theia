"""The final evidence screen must not publish unsupported draft paragraphs."""

import json
import unittest
from unittest.mock import AsyncMock

import httpx

from research import ResearchRun, ResearchRunner
from research_sources import retrieve


class EvidenceScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_relevant_question_does_not_stop_on_ambiguous_subcategory(self):
        runner = ResearchRunner({"TYPESAFE_API_KEY": "fixture", "GENERALCOMPUTE_API_KEY": "fixture", "GENERALCOMPUTE_MODEL": "fixture"})
        runner._routing = AsyncMock(return_value=({
            "intent": {"choice": "other", "confidence": 0.24},
            "needs_code": {"noul": 0.2}, "in_scope": {"noul": 0.95},
        }, "jev-fixture"))
        runner._agent = AsyncMock(return_value=None)
        run = await runner.start({"clientRequestId": "relevant", "question": "What does Paper2Agent actually verify?"})
        await run.task
        self.assertEqual(runner._agent.await_count, 2)
        self.assertFalse(any(e["type"] == "clarification.required" for e in run.events))
        await runner.close()

    async def test_clearing_excerpt_does_not_reintroduce_previous_text(self):
        runner = ResearchRunner({"TYPESAFE_API_KEY": "fixture", "GENERALCOMPUTE_API_KEY": "fixture", "GENERALCOMPUTE_MODEL": "fixture"})
        first = ResearchRun("first", "Question", [], pasted_text="old excerpt")
        first.emit("run.completed")
        runner.runs[first.id] = first
        runner._routing = AsyncMock(side_effect=RuntimeError("offline fixture"))
        run = await runner.start({"clientRequestId": "clear", "question": "New question", "previousRunId": first.id, "pastedText": ""})
        self.assertEqual(run.pasted_text, "")
        await runner.close()

    def test_code_profile_includes_actual_implementation(self):
        sources = retrieve("What does Paper2Agent verify?", ["paper2agent-paper", "paper2agent-code"], code_profile=True)
        self.assertGreaterEqual(sum(bool(s.get("path") and s["path"].endswith(".py")) for s in sources), 2)

    async def test_unsupported_claim_is_withheld_and_supported_claim_retained(self):
        runner = ResearchRunner({"TYPESAFE_API_KEY": "fixture"})
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["state"]["source_excerpts"], "593 of 599 tools passed.")
            answers = {key: {"type": "choice", "choice": "unsupported" if "98.9" in text else "supported", "confidence": 0.95}
                       for key, text in payload["state"]["paragraphs"].items()}
            return httpx.Response(200, json={"answers": answers})
        runner.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        run = ResearchRun("screen", "Question", [])
        draft = "## Answer\n\nThe study reports that 593 of 599 tools passed its tests [S1].\n\nThe paper proves a success rate of 98.9 percent across the tested tools [S1]."
        result, partial = await runner._check_evidence(run, draft, "593 of 599 tools passed.")
        self.assertTrue(partial)
        self.assertIn("593 of 599", result)
        self.assertNotIn("98.9", result)
        self.assertIn("Evidence gap", result)
        self.assertEqual(run.events[-1]["payload"]["withheld"], 1)
        await runner.close()

    async def test_failed_screen_is_explicitly_partial_without_provider_body(self):
        runner = ResearchRunner({"TYPESAFE_API_KEY": "fixture"})
        runner.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="private provider body")))
        run = ResearchRun("screen", "Question", [])
        text, partial = await runner._check_evidence(run, "A sufficiently long source-based research paragraph needs checking [S1].", "Source text")
        self.assertTrue(partial)
        self.assertIn("Evidence check unavailable", text)
        self.assertNotIn("private provider body", text)
        await runner.close()
