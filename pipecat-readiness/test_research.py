"""Offline contract tests; no provider credentials or network calls needed."""

import asyncio
from copy import deepcopy
import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
import httpx

from research import ResearchError, ResearchRun, ResearchRunner, finalize_report, register_research_routes, search_query, validate_routing
from research_sources import retrieve, unknown_reference
from research_search import ExaSearchError

ENV = {"TYPESAFE_API_KEY": "test", "GENERALCOMPUTE_API_KEY": "test", "GENERALCOMPUTE_MODEL": "test-model"}
DECISION = {"model": "jev-latest", "answers": {
    "intent": {"type": "choice", "choice": "critique", "confidence": 0.9,
               "probabilities": {"critique": 0.8, "explain": 0.1, "code": 0.05, "compare": 0.04, "other": 0.01}},
    "needs_code": {"type": "noul", "noul": 0.8},
}}


class GroundingTests(unittest.TestCase):
    def test_referential_search_followups_include_prior_question(self):
        for question in ("What are their limitations?", "Focus on limitations.", "Compare them."):
            with self.subTest(question=question):
                run = ResearchRun("followup", question, [], previous="Previous question: Papers about diffusion transformers\nPrevious answer: Do not use this answer as evidence.")
                self.assertIn("Papers about diffusion transformers", search_query(run))
                self.assertIn(question, search_query(run))
                self.assertNotIn("Do not use this answer", search_query(run))

    def test_independent_topic_and_explicit_url_keep_their_own_query(self):
        for question in ("Find papers about protein folding", "Focus on protein diffusion models", "Analyze this https://arxiv.org/abs/1234.5678"):
            with self.subTest(question=question):
                run = ResearchRun("new-topic", question, [], previous="Previous question: Papers about diffusion transformers\nPrevious answer: Old findings.")
                self.assertEqual(search_query(run), question)

    def test_search_followup_context_is_bounded_and_excludes_answer(self):
        run = ResearchRun("bounded", "Explain their limitations " + "detail " * 550, [],
                          previous="Previous question: " + "topic " * 800 + "\nPrevious answer: UNSUPPORTED_PREVIOUS_FINDING")
        query = search_query(run)
        self.assertLessEqual(len(query), 3850)
        self.assertLessEqual(len(query.split("Research topic from previous question: ")[1]), 800)
        self.assertNotIn("UNSUPPORTED_PREVIOUS_FINDING", query)

    def test_retrieval_is_bounded_and_registered(self):
        sources = retrieve("What does Paper2Agent verify in its workflow?", ["paper2agent-paper", "paper2agent-code"], code_profile=True)
        self.assertLessEqual(len(sources), 8)
        self.assertLessEqual(sum(len(s["text"]) for s in sources), 16000)
        self.assertEqual({s["packId"] for s in sources}, {"paper2agent-paper", "paper2agent-code"})
        self.assertTrue(all(s["sha256"] and s["text"] and not s["path"].startswith("/") for s in sources))

    def test_unknown_reference_cannot_be_claimed_as_read(self):
        self.assertTrue(unknown_reference("Read https://example.com/unseen-paper"))
        self.assertFalse(unknown_reference("https://github.com/jmiao24/Paper2Agent"))
        self.assertTrue(unknown_reference("https://github.com/jmiao24/Paper2Agent-malicious"))

    def test_invalid_decisions_are_rejected(self):
        for key, value in (("confidence", float("nan")), ("confidence", True), ("choice", "invented")):
            result = deepcopy(DECISION)
            result["answers"]["intent"][key] = value
            with self.assertRaises(ResearchError):
                validate_routing(result)
        self.assertEqual(validate_routing(DECISION)["intent"]["choice"], "critique")

    def test_citations_are_resolved_only_to_loaded_sources(self):
        run = ResearchRun("run1", "Question", [])
        run.sources = {"S1": {"id": "S1", "title": "Test", "section": "Overview", "startLine": 1, "endLine": 2}}
        report = finalize_report("A claim [S1]. Another [S999]. [External](https://fabricated.example).", run)
        self.assertIn("[S1](/api/research/runs/run1/sources/S1)", report)
        self.assertNotIn("https://fabricated", report)
        self.assertNotIn("[S999]", report)
        self.assertIn("unverified", report)
        self.assertIn("[S1](/api/research/runs/run1/sources/S1)", finalize_report("Claim [S1](https://invented.example)", run))
        self.assertIn("no resolvable source citations", finalize_report("Uncited output.", run))

    def test_model_citation_locations_are_replaced_by_registered_excerpt_links(self):
        run = ResearchRun("run1", "Question", [])
        run.sources = {source_id: {"id": source_id, "title": "Test", "section": "Overview", "startLine": 1, "endLine": 2}
                       for source_id in ("S1", "S2")}
        report = finalize_report("Claim [S1 lines 999-1000]. Claim [S2 §Invented](https://fabricated.example). "
                                 "Together [S1, S2]. Unknown [S999 lines 4-5].", run)
        self.assertIn("[S1](/api/research/runs/run1/sources/S1)", report)
        self.assertIn("[S2](/api/research/runs/run1/sources/S2)", report)
        for invented in ("999-1000", "§Invented", "https://fabricated", "[S999"):
            self.assertNotIn(invented, report)
        self.assertIn("associated claim as unverified", report)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace_tmp = TemporaryDirectory()
        self.addCleanup(self.workspace_tmp.cleanup)
        self.runner = ResearchRunner({**ENV, "RESEARCH_WORKSPACE_ROOT": self.workspace_tmp.name})
        async def routing(run):
            return validate_routing(DECISION), "jev-latest"
        self.runner._routing = routing
        self.runner._stream_model = AsyncMock(return_value="Offline fixture finding [S1].")

    async def asyncTearDown(self):
        await self.runner.close()

    async def test_two_concurrent_agents_and_grounded_report(self):
        agents = set()
        both_started = asyncio.Event()
        async def model(run, messages, max_tokens, event_type, **fields):
            if "agent" in fields:
                agents.add(fields["agent"])
                if len(agents) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=2)
            result = "## Answer\nThe workflow tests tools [S1].\n\n## Limitations and open questions\nStatic reading only [S2]."
            run.emit(event_type, text=result, **fields)
            return result
        self.runner._stream_model = model
        run = await self.runner.start({"clientRequestId": "one", "question": "What does Paper2Agent verify?"})
        duplicate = await self.runner.start({"clientRequestId": "one", "question": "What does Paper2Agent verify?"})
        self.assertIs(run, duplicate)
        await run.task
        self.assertEqual(agents, {"evidence", "critic"})
        events = list(run.events)
        self.assertEqual(events[-1]["type"], "run.completed")
        self.assertEqual(sum(e["type"] == "agent.completed" for e in events), 2)
        self.assertIn("## Sources analyzed", run.markdown)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(self.runner.latest_id, run.id)
        self.assertIsNone(self.runner.active_id)

    async def test_reused_request_id_requires_identical_payload(self):
        first = await self.runner.start({"clientRequestId": "one", "question": "First question"})
        with self.assertRaises(ResearchError) as error:
            await self.runner.start({"clientRequestId": "one", "question": "Changed question"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.runner.active_id, first.id)

    async def test_completed_voice_summary_can_be_interrupted(self):
        class Voice:
            interruptions = 0
            async def interrupt(self):
                self.interruptions += 1
        voice = Voice()
        self.runner.voice = voice
        completed = ResearchRun("complete", "Question", [])
        completed.emit("run.completed")
        self.runner.runs[completed.id] = completed
        self.runner.latest_id = completed.id
        await self.runner.cancel(completed.id)
        self.assertEqual(voice.interruptions, 1)

    async def test_new_question_cancels_old_and_suppresses_stale_events(self):
        waiting = asyncio.Event()
        async def routing(run):
            waiting.set()
            await asyncio.Event().wait()
        self.runner._routing = routing
        first = await self.runner.start({"clientRequestId": "one", "question": "First question"})
        await waiting.wait()
        second = await self.runner.start({"clientRequestId": "two", "question": "Second question"})
        self.assertTrue(first.cancelled)
        count = first.seq
        first.emit("agent.delta", text="stale")
        self.assertEqual(first.seq, count)
        self.assertEqual(self.runner.active_id, second.id)

    async def test_unknown_url_requests_excerpt(self):
        run = await self.runner.start({"clientRequestId": "unknown", "question": "Analyze https://example.com/paper"})
        await run.task
        self.assertTrue(any(e["type"] == "clarification.required" for e in run.events))
        self.assertFalse(any(e["type"] == "agent.started" for e in run.events))

    async def test_no_configuration_never_starts_fake_run(self):
        runner = ResearchRunner({})
        self.assertFalse(runner.health()["configured"])
        with self.assertRaises(ResearchError) as error:
            await runner.start({"clientRequestId": "missing", "question": "Question"})
        self.assertEqual(error.exception.code, "MISSING_CONFIG")
        self.assertEqual(runner.runs, {})

    async def test_sse_replays_same_run_without_new_provider_work(self):
        async def routing(run):
            decision = deepcopy(DECISION)
            decision["answers"]["intent"]["confidence"] = 0.2
            return validate_routing(decision), "jev-latest"
        self.runner._routing = routing
        run = await self.runner.start({"clientRequestId": "sse", "question": "Question"})
        await run.task
        app = FastAPI()
        register_research_routes(app, self.runner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/research/runs/{run.id}/events", headers={"Last-Event-ID": "2"})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(events[0]["seq"], 3)
            self.assertEqual(events[-1]["type"], "run.completed")
            self.assertEqual(len(self.runner.runs), 1)


class SearchOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace_tmp = TemporaryDirectory()
        self.addCleanup(self.workspace_tmp.cleanup)
        self.runner = ResearchRunner({**ENV, "RESEARCH_WORKSPACE_ROOT": self.workspace_tmp.name, "EXA_API_KEY": "fixture", "PAPER2AGENT_ROOT": "/missing/offline-source-fixture"})
        self.decision = {**validate_routing(DECISION),
                         "acquisition": {"type": "choice", "choice": "search", "confidence": 0.99,
                                         "probabilities": {"search": 0.99, "provided": 0.005, "clarify": 0.005}}}
        self.runner._routing = AsyncMock(side_effect=lambda run: (self.decision, "jev-fixture"))
        self.runner._agent = AsyncMock(return_value="Supported finding [S1].")
        self.runner._stream_model = AsyncMock(return_value="## Answer\n\nSupported finding from the acquired publication [S1].")
        self.runner._check_evidence = AsyncMock(side_effect=lambda run, text, evidence: (text, False))
        self.web_source = {"id": "S1", "packId": "exa", "title": "Retrieved paper", "url": "https://arxiv.org/abs/1234.5678",
                           "text": "The study reports the measured result.", "section": "Extracted source text", "path": None,
                           "startLine": None, "endLine": None, "coverage": "Abstract only"}
        self.acquire = AsyncMock(return_value=[self.web_source])
        self.patcher = patch("research.acquire_sources", self.acquire)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.runner.close()

    async def test_general_research_searches_without_local_package(self):
        self.assertTrue(self.runner.health()["configured"])
        self.assertTrue(self.runner.health()["search"]["configured"])
        run = await self.runner.start({"clientRequestId": "search", "question": "Find papers on protein diffusion models", "sourceIds": []})
        await run.task
        self.acquire.assert_awaited_once()
        self.assertEqual(self.runner._agent.await_count, 2)
        route = next(event for event in run.events if event["type"] == "routing.completed")
        self.assertEqual(route["payload"]["acquisition"], "search")
        self.assertIn("Abstract only", run.markdown)
        self.assertNotIn("lines None", run.markdown)
        self.assertEqual(run.events[-1]["type"], "run.completed")
        self.assertIn("Coverage: Abstract only", self.runner._agent.await_args_list[0].args[3])

    async def test_supplied_url_requests_contents_acquisition(self):
        run = await self.runner.start({"clientRequestId": "url", "question": "Analyze https://arxiv.org/abs/1234.5678.", "sourceIds": []})
        await run.task
        self.assertEqual(self.acquire.await_args.kwargs["urls"], ["https://arxiv.org/abs/1234.5678"])

    async def test_draft_preparation_feeds_generated_passages_to_both_analysts(self):
        draft = {**self.web_source, "packId": "paper2agent-draft", "text": "Distinct passage from the generated reading package.",
                 "coverage": "Paper2Agent draft PDF extraction; unreviewed selected passages"}
        self.runner.paper2agent.prepare = AsyncMock(return_value=[draft])
        run = await self.runner.start({"clientRequestId": "draft", "question": "Explain the method", "sourceIds": [], "paper2agentEnabled": True})
        await run.task
        self.runner.paper2agent.prepare.assert_awaited_once_with([self.web_source], run.question, run.emit)
        self.assertEqual(run.sources["S1"], draft)
        self.assertEqual(self.runner._agent.await_count, 2)
        for call in self.runner._agent.await_args_list:
            self.assertIn(draft["text"], call.args[3])
            self.assertNotIn(self.web_source["text"], call.args[3])
        self.assertIn("Paper2Agent draft: PDF extraction has not passed page-by-page review", run.markdown)
        self.assertEqual(run.events[-1]["type"], "run.completed")

    async def test_preparation_is_opt_in_and_changes_request_identity(self):
        self.runner.paper2agent.prepare = AsyncMock(return_value=[self.web_source])
        payload = {"clientRequestId": "opt-in", "question": "Explain the method", "sourceIds": []}
        run = await self.runner.start(payload)
        await run.task
        self.runner.paper2agent.prepare.assert_not_awaited()
        with self.assertRaises(ResearchError) as error:
            await self.runner.start({**payload, "paper2agentEnabled": True})
        self.assertEqual(error.exception.code, "REQUEST_CONFLICT")

    async def test_preparation_voice_context_and_boolean_validation(self):
        self.runner.set_voice_context({"sourceIds": [], "paper2agentEnabled": True})
        self.assertTrue(self.runner.voice_context["paper2agentEnabled"])
        with self.assertRaises(ResearchError):
            self.runner.set_voice_context({"sourceIds": [], "paper2agentEnabled": "true"})
        with self.assertRaises(ResearchError):
            await self.runner.start({"clientRequestId": "bad", "question": "Explain this", "paper2agentEnabled": 1})

    async def test_search_disabled_clarification_is_spoken_before_completion(self):
        observed = []
        async def speak(message, run_id):
            observed.append((message, self.runner.runs[run_id].done))
        self.runner.voice = type("Voice", (), {"speak": AsyncMock(side_effect=speak), "announce": AsyncMock(), "interrupt": AsyncMock()})()
        run = await self.runner.start({"clientRequestId": "disabled", "question": "Find protein folding papers", "sourceIds": [], "searchEnabled": False})
        await run.task
        self.acquire.assert_not_awaited()
        self.runner._agent.assert_not_awaited()
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0][1])
        self.assertEqual(run.events[-1]["payload"]["status"], "clarification")

    async def test_exa_failure_preserves_search_stage_and_is_spoken(self):
        self.acquire.side_effect = ExaSearchError("EXA_UNAVAILABLE", "Exa search is temporarily unavailable.")
        self.runner.voice = type("Voice", (), {"speak": AsyncMock(), "announce": AsyncMock(), "interrupt": AsyncMock()})()
        run = await self.runner.start({"clientRequestId": "failed", "question": "Find protein folding papers", "sourceIds": []})
        await run.task
        self.assertEqual(run.events[-1]["type"], "run.failed")
        self.assertEqual(run.events[-1]["payload"]["stage"], "search")
        self.assertIn("Exa", run.events[-1]["payload"]["message"])
        self.assertNotIn("General Compute", run.events[-1]["payload"]["message"])
        self.runner.voice.speak.assert_awaited_once()
        self.runner._agent.assert_not_awaited()

    async def test_provided_excerpt_skips_search_and_missing_local_package(self):
        self.decision["acquisition"]["choice"] = "provided"
        self.decision["needs_code"]["noul"] = 0.1
        run = await self.runner.start({"clientRequestId": "excerpt", "question": "Explain this study", "sourceIds": [], "pastedText": "A study of protein folding reports an experimentally measured result."})
        await run.task
        self.acquire.assert_not_awaited()
        self.assertEqual(run.sources["S1"]["packId"], "pasted")
        self.assertEqual(run.events[-1]["type"], "run.completed")

    async def test_sessions_do_not_inherit_or_cancel_another_session(self):
        other = ResearchRun("other", "Private prior question", [], pasted_text="Prior evidence", session_id="session_a")
        other.emit("run.completed")
        self.runner.runs[other.id] = other
        run = await self.runner.start({"clientRequestId": "fresh", "question": "Find new papers", "sourceIds": [], "sessionId": "session_b", "previousRunId": "other"})
        self.assertEqual(run.previous, "")
        self.assertEqual(run.pasted_text, "")
        with self.assertRaises(ResearchError) as error:
            await self.runner.start({"clientRequestId": "competing", "question": "Find other papers", "sessionId": "session_c"})
        self.assertEqual(error.exception.code, "SESSION_BUSY")
        self.assertFalse(run.cancelled)
        self.assertEqual(self.runner.health()["activeSessionId"], "session_b")
        self.assertEqual(run.events[0]["payload"]["sessionId"], "session_b")
        await run.task

    async def test_jev_receives_enabled_search_and_typed_acquisition_question(self):
        seen = []
        def respond(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"model": "jev-fixture", "answers": self.decision})
        self.runner.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        run = ResearchRun("preview", "Find protein folding papers", [], search_enabled=True)
        answers, _ = await ResearchRunner._routing(self.runner, run)
        self.assertTrue(seen[0]["state"]["search_available"])
        self.assertEqual(seen[0]["state"]["available_sources"], [])
        self.assertEqual(set(seen[0]["questions"]["acquisition"]["criteria"]), {"search", "provided", "clarify"})
        self.assertEqual(answers["acquisition"]["choice"], "search")


if __name__ == "__main__":
    unittest.main()
