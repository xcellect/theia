"""End-to-end offline contracts for paper workspaces through the real runner."""

import asyncio
from copy import deepcopy
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
import httpx

from research import ResearchError, ResearchRun, ResearchRunner, register_research_routes
from research_limits import MAX_READING_PAPERS


ENV = {"TYPESAFE_API_KEY": "fixture", "GENERALCOMPUTE_API_KEY": "fixture",
       "GENERALCOMPUTE_MODEL": "fixture-model", "EXA_API_KEY": "fixture",
       "PAPER2AGENT_ROOT": "/missing/offline-paper-fixture"}
PAPERS = [
    {"id": "S1", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762v7",
     "text": "The encoder uses attention layers. " * 400, "packId": "exa", "links": ["https://github.com/example/attention"]},
    {"id": "S2", "title": "BERT", "url": "https://arxiv.org/abs/1810.04805",
     "text": "The encoder uses masked language modeling. " * 300, "packId": "exa", "links": []},
]


class PaperSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.runners = []
        self.model_calls = []
        self.prepared = []
        self.action = "discover_papers"
        self.runner = self.make_runner()
        self.acquire = self.enterContext(patch("research_session.acquire_sources", new=AsyncMock(side_effect=lambda *a, **k: deepcopy(PAPERS))))
        self.select = self.enterContext(patch("research_session.select_papers", new=AsyncMock(side_effect=lambda *a, **k: deepcopy(PAPERS))))
        self.jobs = self.enterContext(patch("research_session.discover_and_check", new=AsyncMock(return_value={
            "state": "unsupported_operation", "reason": "No registered experiment operation for this fixture.",
            "capabilities": {"cpuCount": 4, "gpu": []}, "repository": {"status": "not_found"}})))

    def make_runner(self):
        runner = ResearchRunner({**ENV, "RESEARCH_WORKSPACE_ROOT": str(self.root)})
        runner._routing = AsyncMock(side_effect=self.route)
        runner._stream_model = AsyncMock(side_effect=self.model)
        runner._check_evidence = AsyncMock(side_effect=lambda run, text, evidence: (text, False))
        runner.paper2agent.prepare = AsyncMock(side_effect=self.prepare)
        runner.paper2agent.retrieve = AsyncMock(side_effect=lambda source, question, **kw: dict(source))
        self.runners.append(runner)
        return runner

    async def asyncTearDown(self):
        for runner in self.runners:
            await runner.close()
            runner.workspace.close()
        self.temporary.cleanup()

    async def route(self, run):
        return {"intent": {"type": "choice", "choice": "compare" if "compare" in run.question.lower() else "explain", "confidence": 0.95},
                "needs_code": {"type": "noul", "noul": 0.0},
                "acquisition": {"type": "choice", "choice": "search", "confidence": 0.95},
                "action": {"type": "choice", "choice": self.action, "confidence": 0.95},
                "target": {"type": "choice", "choice": "all", "confidence": 0.95}}, "jev-fixture"

    async def prepare(self, sources, question, emit, **kwargs):
        self.prepared.append((deepcopy(sources), kwargs))
        source = dict(sources[0])
        if not source.get("text"):
            source["text"] = "The PDF provides measured evaluation evidence and describes its limitations. " * 30
        source.update(packId="paper2agent-draft", artifactId="a" * 64, sourceSha256="b" * 64,
                      preparationStatus="unreviewed", pageCount=8, coverage="Draft PDF passages; visual review pending.")
        emit("paper2agent.completed", sourceId=source["id"], pages=8, status="unreviewed", cacheHit=False)
        return [source]

    async def model(self, run, messages, max_tokens, event_type, **fields):
        self.model_calls.append((run.id, event_type, messages, fields))
        sources = [source for source in run.sources.values()
                   if not fields.get("paperId") or source.get("paperId") == fields["paperId"]]
        content = "\n\n".join(f"{source['title']} supports a scoped finding [{source['id']}]." for source in sources)
        if event_type == "report.delta":
            content = "# Paper comparison\n\n## Answer\n\n" + content + "\n\n## Limitations and open questions\n\nThis is selected-excerpt reading."
        run.emit(event_type, text=content, **fields)
        return content

    async def start(self, question="Compare the attention and BERT papers", session="session-one", request="first", **kwargs):
        run = await self.runner.start({"clientRequestId": request, "sessionId": session,
            "sourceIds": [], "question": question, "paper2agentEnabled": True, **kwargs})
        await asyncio.wait_for(run.task, 3)
        self.assertEqual(list(run.events)[-1]["type"], "run.completed", list(run.events)[-1])
        return run

    async def test_session_api_returns_reports_deletes_workspace_and_expires_replays(self):
        run = await self.start()
        app = FastAPI()
        register_research_routes(app, self.runner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            data = (await client.get("/research/sessions/session-one")).json()
            self.assertEqual(data["runs"][0]["markdown"], run.markdown)
            self.assertTrue(data["runs"][0]["done"])
            self.assertEqual(data["messages"][0]["content"], run.question)
            self.assertEqual(data["messages"][1]["content"], run.markdown)
            self.assertIn("createdAt", data["messages"][1])
            self.assertFalse(data["hasMore"])
            self.assertEqual((await client.get("/research/sessions/session-one?before=unknown")).status_code, 400)
            response = await client.delete("/research/sessions/session-one")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"sessionId": "session-one", "status": "deleted"})
            self.assertEqual((await client.get(f"/research/runs/{run.id}/events")).status_code, 404)
            self.assertEqual((await client.get(f"/research/runs/{run.id}/sources/{next(iter(run.sources))}")).status_code, 404)
            self.assertEqual((await client.delete("/research/sessions/session-one")).status_code, 404)
            self.assertEqual((await client.delete("/research/sessions/invalid%20id")).status_code, 400)
            self.assertEqual((await client.get("/research/sessions/session-one")).json()["runs"], [])
            self.assertEqual((await client.get("/research/sessions")).json()["sessions"], [])
        self.assertNotIn(run.id, self.runner.runs)
        self.assertNotIn("first", self.runner.requests)
        self.assertNotIn("first", self.runner.request_fingerprints)
        self.assertIsNone(self.runner.latest_id)
        self.assertIsNone(self.runner.get_run(run.id))
        self.assertFalse((self.root / "sessions/session-one").exists())

    async def test_delete_rejects_active_research_and_bound_voice_without_losing_history(self):
        entered = asyncio.Event()
        async def waiting_route(run):
            entered.set()
            await asyncio.Event().wait()
        self.runner._routing = waiting_route
        run = await self.runner.start({"clientRequestId": "active", "sessionId": "session-one",
            "sourceIds": [], "question": "Explain the paper", "paper2agentEnabled": True})
        await asyncio.wait_for(entered.wait(), 2)
        with self.assertRaises(ResearchError) as raised:
            await self.runner.delete_session("session-one")
        self.assertEqual(raised.exception.status, 409)
        self.assertIsNotNone(self.runner.workspace.get_run(run.id))
        await self.runner.cancel(run.id)
        self.runner.voice = object()
        self.runner.voice_context = {"sessionId": "session-one"}
        with self.assertRaises(ResearchError) as raised:
            await self.runner.delete_session("session-one")
        self.assertEqual(raised.exception.code, "SESSION_BUSY")
        self.runner.voice = None
        await self.runner.delete_session("session-one")
        self.assertIsNone(self.runner.voice_context)

    async def test_cleanup_error_is_sanitized_and_deleted_reports_leave_memory_cache(self):
        run = await self.start()
        app = FastAPI()
        register_research_routes(app, self.runner)
        with patch("research_workspace.shutil.rmtree", side_effect=OSError("/private/secret-file")):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.delete("/research/sessions/session-one")
                self.assertEqual(response.status_code, 500)
                self.assertNotIn("/private", response.text)
                self.assertEqual((await client.get(f"/research/runs/{run.id}/events")).status_code, 404)
        self.assertNotIn(run.id, self.runner.runs)
        self.assertFalse(self.runner.workspace.session_exists("session-one"))

    async def test_public_session_pages_more_than_twenty_messages_without_losing_turns(self):
        for index in range(25):
            run = self.runner.workspace.begin_run(f"page-{index:02}", "paged", f"Question {index}", f"request-{index}", "fixture")
            self.runner.workspace.save_run(dict(run, done=True, status="completed", markdown=f"# Answer {index}"))
        latest = self.runner.public_session("paged")
        self.assertEqual(len(latest["runs"]), 20)
        self.assertEqual(len(latest["messages"]), 40)
        self.assertTrue(latest["hasMore"])
        earlier = self.runner.public_session("paged", before=latest["nextBefore"])
        self.assertEqual(len(earlier["runs"]), 5)
        self.assertFalse(earlier["hasMore"])
        self.assertEqual([run["runId"] for run in earlier["runs"] + latest["runs"]], [f"page-{index:02}" for index in range(25)])

    async def test_two_paper_run_streams_and_persists_balanced_evidence_and_citations(self):
        run = await self.start()
        self.assertEqual(len(run.sources), 2)
        self.assertEqual(sorted(len(source["text"]) for source in run.sources.values()), [8000, 8000])
        self.assertEqual(sum(event["type"] == "paper.agent.completed" for event in run.events), 2)
        calls = [call for call in self.model_calls if call[1] == "paper.agent.delta"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            text = call[2][-1]["content"].split("Actual source evidence:\n", 1)[1]
            self.assertEqual(sum(title in text for title in ("Attention Is All You Need", "BERT")), 1)
        for source_id in run.sources:
            self.assertTrue(source_id.startswith("P"))
            self.assertIn(f"/runs/{run.id}/sources/{source_id}", run.markdown)
        session = self.runner.workspace.session("session-one")
        self.assertEqual(len(session["papers"]), 2)
        self.assertTrue(all(len(paper["reports"]) == 1 for paper in session["papers"]))
        self.assertTrue(all(paper["jobs"][0]["state"] == "unsupported_operation" for paper in session["papers"]))
        report = self.root / "sessions" / "session-one" / "runs" / run.id / "report.md"
        self.assertEqual(report.read_text(), run.markdown)
        for _, kwargs in self.prepared:
            self.assertTrue(kwargs["retrieval_dir"].is_relative_to(self.root / "sessions" / "session-one"))

    async def test_restart_restores_report_citation_endpoint_and_followup_without_exa(self):
        run = await self.start()
        saved_markdown, saved_sources = run.markdown, deepcopy(run.sources)
        first_runner = self.runner
        await first_runner.close()
        first_runner.workspace.close()
        self.runners.remove(first_runner)
        self.runner = self.make_runner()
        restored = self.runner.get_run(run.id)
        self.assertEqual(restored.markdown, saved_markdown)
        self.assertEqual(restored.sources, saved_sources)
        app = FastAPI()
        register_research_routes(app, self.runner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for source_id, source in saved_sources.items():
                response = await client.get(f"/research/runs/{run.id}/sources/{source_id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["text"], source["text"])
        self.acquire.reset_mock()
        self.select.reset_mock()
        self.action = "compare_papers"
        followup = await self.start("Compare their limitations", request="followup", previousRunId=run.id)
        self.acquire.assert_not_awaited()
        self.select.assert_not_awaited()
        self.assertEqual(self.runner.paper2agent.retrieve.await_count, 2)
        self.assertEqual(set(followup.sources), set(saved_sources))
        self.assertIn("not source evidence", followup.previous)
        self.assertEqual(len(self.runner.workspace.session("session-one")["messages"]), 4)

    async def test_metadata_only_selection_is_prepared_before_evidence_is_required(self):
        self.acquire.side_effect = None
        self.acquire.return_value = []
        self.select.side_effect = None
        self.select.return_value = [dict(PAPERS[0], text="")]
        run = await self.start("Explain the attention paper")
        self.assertEqual(len(run.sources), 1)
        self.assertEqual(self.prepared[0][0][0]["text"], "")
        self.assertIn("PDF provides measured evaluation", next(iter(run.sources.values()))["text"])
        self.assertIn("Paper2Agent draft", run.markdown)

    async def test_five_papers_all_receive_bounded_evidence_and_only_two_readers_run_at_once(self):
        papers = [dict(PAPERS[0], id=f"S{index+1}", title=f"Paper {index+1}",
                       url=f"https://arxiv.org/abs/2401.{index:05}", text=f"Evidence for paper {index}. " * 600,
                       selectionReason=f"Jev selected relevant paper {index+1}.") for index in range(MAX_READING_PAPERS)]
        self.select.side_effect = None
        self.select.return_value = papers
        active = peak = 0
        async def concurrent_model(run, messages, max_tokens, event_type, **fields):
            nonlocal active, peak
            if event_type == "paper.agent.delta":
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                try:
                    return await self.model(run, messages, max_tokens, event_type, **fields)
                finally:
                    active -= 1
            return await self.model(run, messages, max_tokens, event_type, **fields)
        self.runner._stream_model = concurrent_model
        run = await self.start("Analyze relevant papers about attention methods")
        self.assertEqual(len(run.sources), MAX_READING_PAPERS)
        self.assertEqual(peak, 2)
        self.assertEqual(sum(len(source["text"]) for source in run.sources.values()), 16000)
        self.assertTrue(all(len(source["text"]) == 3200 for source in run.sources.values()))
        self.assertEqual(self.runner.health()["paper2agent"]["maxPapers"], MAX_READING_PAPERS)
        self.assertEqual(self.runner._validate_paper_ids(run.session_id, run.paper_ids), run.paper_ids)
        writer = next(call for call in self.model_calls if call[1] == "report.delta")
        for source in run.sources.values():
            self.assertIn(source["text"], writer[2][-1]["content"])
        selected = [event["payload"] for event in run.events if event["type"] == "paper.selected"]
        self.assertTrue(all(event["message"].startswith("Jev selected relevant paper") for event in selected))

    async def test_jev_specific_target_overrides_multiple_selected_checkboxes(self):
        run = await self.start()
        papers = self.runner._paper_catalog(run)
        target = next(paper["paperId"] for paper in papers if paper["title"] == "BERT")
        answers, _ = await self.route(run)
        answers.update(action={"choice": "answer_paper"}, target={"choice": target}, reading_scope={"choice": "single"})
        followup = ResearchRun("followup", "Explain BERT's masking objective only", [], session_id=run.session_id, paper_ids=run.paper_ids)
        self.assertEqual(self.runner._resolve_paper_route(followup, answers), ("answer_paper", [target]))

    async def test_jev_relevance_chooses_saved_subset_instead_of_all_selected_papers(self):
        sources = [dict(PAPERS[0], title=f"Paper {index}", url=f"https://arxiv.org/abs/2401.{index:05}") for index in range(5)]
        papers = [self.runner.workspace.save_paper("saved-set", source) for source in sources]
        run = ResearchRun("followup", "Compare the first and third papers", [], session_id="saved-set", paper_ids=[p["paperId"] for p in papers])
        catalog = self.runner._paper_catalog(run)
        chosen = {papers[0]["paperId"], papers[2]["paperId"]}
        answers = {"intent": {"choice": "compare"}, "action": {"choice": "compare_papers"},
                   "target": {"choice": "all"}, "reading_scope": {"choice": "multiple"},
                   **{f"saved_paper_{index}": {"noul": 0.95 if p["paperId"] in chosen else 0.05} for index, p in enumerate(catalog)}}
        action, targets = self.runner._resolve_paper_route(run, answers)
        self.assertEqual(action, "compare_papers")
        self.assertEqual(set(targets), chosen)

    async def test_non_arxiv_fallback_skips_preparation_and_labels_the_exa_evidence(self):
        self.select.side_effect = None
        self.select.return_value = []
        self.acquire.side_effect = None
        self.acquire.return_value = [dict(PAPERS[0], url="https://journal.example/paper")]
        run = await self.start("Find relevant attention papers")
        self.runner.paper2agent.prepare.assert_not_awaited()
        skipped = next(event["payload"] for event in run.events if event["type"] == "paper2agent.skipped")
        self.assertEqual(skipped["status"], "excerpt_only")
        self.assertEqual(skipped["title"], PAPERS[0]["title"])
        self.assertIn("paperId", skipped)
        self.assertFalse(any(event["type"] == "paper2agent.failed" for event in run.events))

    async def test_unmatched_single_paper_does_not_analyze_unrelated_search_excerpts(self):
        self.select.side_effect = None
        self.select.return_value = []
        original_route = self.route
        async def single_route(run):
            answers, model = await original_route(run)
            answers["reading_scope"] = {"choice": "single"}
            return answers, model
        self.runner._routing = single_route
        run = await self.runner.start({"clientRequestId": "single", "sessionId": "session-one", "sourceIds": [],
            "question": "Analyze https://arxiv.org/abs/2501.09999 only", "paper2agentEnabled": True})
        await run.task
        self.assertEqual(run.events[-1]["type"], "run.failed")
        self.assertIn("requested paper", run.events[-1]["payload"]["message"])
        self.assertEqual(run.sources, {})
        self.assertEqual(self.model_calls, [])
        self.assertEqual(self.select.await_args.kwargs["reading_scope"], "single")

    async def test_rejected_arxiv_candidates_remain_excerpts_without_pdf_preparation(self):
        self.select.side_effect = None
        self.select.return_value = []
        run = await self.start("Find relevant attention papers")
        self.runner.paper2agent.prepare.assert_not_awaited()
        self.assertTrue(all(source["packId"] == "exa" for source in run.sources.values()))
        self.assertEqual(sum(event["type"] == "paper2agent.skipped" for event in run.events), 2)

    async def test_paper_selection_cannot_read_another_sessions_memory(self):
        run = await self.start()
        with self.assertRaises(ResearchError):
            await self.runner.start({"clientRequestId": "foreign", "sessionId": "session-two",
                "sourceIds": [], "question": "What are its limitations?", "paperIds": run.paper_ids})
        empty = self.runner.public_session("session-two")
        self.assertEqual(empty["papers"], [])
        self.assertEqual(empty["messages"], [])
        self.assertEqual(empty["summary"], "")

    async def test_cancellation_persists_terminal_state_and_cleans_all_child_tasks(self):
        entered_agent, entered_job = asyncio.Event(), asyncio.Event()
        async def blocked_model(*args, **kwargs):
            entered_agent.set()
            await asyncio.Event().wait()
        async def blocked_job(*args, **kwargs):
            entered_job.set()
            await asyncio.Event().wait()
        self.runner._stream_model = blocked_model
        self.jobs.side_effect = blocked_job
        run = await self.runner.start({"clientRequestId": "cancel", "sessionId": "session-one",
            "sourceIds": [], "question": "Compare papers", "paper2agentEnabled": True})
        await asyncio.wait_for(asyncio.gather(entered_agent.wait(), entered_job.wait()), 2)
        children = list(self.runner._children[run.id])
        await self.runner.cancel(run.id)
        self.assertTrue(all(task.done() for task in children))
        self.assertNotIn(run.id, self.runner._children)
        saved = self.runner.workspace.get_run(run.id)
        self.assertEqual(saved["status"], "cancelled")
        self.assertTrue(saved["done"])
        self.assertEqual(saved["events"][-1]["type"], "run.cancelled")
        session = self.runner.workspace.session("session-one")
        self.assertTrue(all(job["state"] == "cancelled" for paper in session["papers"] for job in paper["jobs"]))

    async def test_idempotent_request_after_restart_does_not_launch_provider_work(self):
        run = await self.start()
        await self.runner.close()
        self.runner.workspace.close()
        self.runners.remove(self.runner)
        self.runner = self.make_runner()
        repeated = await self.runner.start({"clientRequestId": "first", "sessionId": "session-one",
            "sourceIds": [], "question": "Compare the attention and BERT papers", "paper2agentEnabled": True})
        self.assertEqual(repeated.id, run.id)
        self.assertTrue(repeated.done)
        self.runner._routing.assert_not_awaited()
        self.runner._stream_model.assert_not_awaited()

    async def test_prior_assistant_claims_and_stale_citations_never_enter_reader_or_writer_prompts(self):
        stale_id = "P" + "deadbeef" * 3
        fabricated = "FABRICATED_HISTORY_CLAIM: every model converged in zero steps"
        earlier_question = "Explain the reproducibility evidence for these architectures."
        historical = self.runner.workspace.begin_run("historical-run", "session-one", earlier_question,
                                                     "historical-request", "historical-fingerprint")
        historical.update(done=True, status="completed", markdown=f"{fabricated} [{stale_id}].",
                          events=[{"runId": "historical-run", "sessionId": "session-one", "seq": 1,
                                   "type": "run.completed", "payload": {"status": "completed"}}])
        self.runner.workspace.save_run(historical)
        run = await self.start()
        # Preserve raw conversation history, while isolating evidence prompts.
        self.assertIn(fabricated, run.previous)
        self.assertIn(stale_id, run.previous)
        current_ids = set(run.sources)
        for _, event_type, messages, fields in self.model_calls:
            if event_type not in {"paper.agent.delta", "report.delta"}:
                continue
            prompt = "\n".join(message["content"] for message in messages)
            self.assertIn(earlier_question, prompt)
            self.assertNotIn(fabricated, prompt)
            self.assertNotIn(stale_id, prompt)
            citations = set(re.findall(r"P[a-f0-9]{24}", prompt))
            if event_type == "paper.agent.delta":
                source = next(source for source in run.sources.values() if source["paperId"] == fields["paperId"])
                self.assertEqual(citations, {source["id"]})
                evidence = messages[-1]["content"].split("Actual source evidence:\n", 1)[1]
                self.assertIn(source["text"], evidence)
                for other in run.sources.values():
                    if other["id"] != source["id"]:
                        self.assertNotIn(other["text"], evidence)
            else:
                self.assertEqual(citations, current_ids)

    async def test_each_paper_answer_resolves_only_its_own_current_citation(self):
        async def cross_paper_model(run, messages, max_tokens, event_type, **fields):
            output = await self.model(run, messages, max_tokens, event_type, **fields)
            if event_type == "paper.agent.delta":
                other = next(source for source in run.sources.values() if source["paperId"] != fields["paperId"])
                output += f"\nInjected cross-paper draft claim [{other['id']}]."
            return output
        self.runner._stream_model = cross_paper_model
        run = await self.start()
        completions = [event["payload"] for event in run.events if event["type"] == "paper.agent.completed"]
        self.assertEqual(len(completions), 2)
        for payload in completions:
            own = next(source for source in run.sources.values() if source["paperId"] == payload["paperId"])
            ids = set(re.findall(r"P[a-f0-9]{24}", payload["text"]))
            self.assertEqual(ids, {own["id"]})
            self.assertIn("unverified source reference removed", payload["text"])

    async def test_report_waits_for_actual_job_outcomes_then_persists_preflight_without_execution_claims(self):
        finish_jobs = asyncio.Event()
        async def delayed_job(*args, **kwargs):
            await finish_jobs.wait()
            return {"state": "blocked_compute", "reason": "Requires 16 GB GPU VRAM; measured worker has no compatible GPU.",
                    "capabilities": {"gpu": []}, "repository": {"status": "author-linked",
                        "url": "https://github.com/example/paper-code", "commit": "1234567890abcdef" * 2}}
        self.jobs.side_effect = delayed_job
        run = await self.runner.start({"clientRequestId": "preflight", "sessionId": "session-one",
            "sourceIds": [], "question": "Compare papers and check runnable experiments", "paper2agentEnabled": True})
        for _ in range(100):
            if any(event["type"] == "report.completed" for event in run.events):
                break
            await asyncio.sleep(0.01)
        self.assertTrue(any(event["type"] == "report.completed" for event in run.events))
        self.assertFalse(run.done)
        self.assertNotIn("## Code and experiment preflight", run.markdown)
        finish_jobs.set()
        await asyncio.wait_for(run.task, 2)
        self.assertEqual(list(run.events)[-1]["type"], "run.completed")
        self.assertIn("## Code and experiment preflight", run.markdown)
        self.assertIn("blocked_compute", run.markdown)
        self.assertIn("Requires 16 GB GPU VRAM; measured worker has no compatible GPU.", run.markdown)
        self.assertIn("https://github.com/example/paper-code", run.markdown)
        self.assertIn("1234567890ab", run.markdown)
        self.assertIn("Experiments were not executed.", run.markdown)
        self.assertNotIn("experiment.started", [event["type"] for event in run.events])
        report_events = [event for event in run.events if event["type"] == "report.completed"]
        self.assertEqual(len(report_events), 2)
        self.assertEqual(report_events[-1]["payload"]["markdown"], run.markdown)
        persisted = self.runner.workspace.get_run(run.id)
        self.assertEqual(persisted["markdown"], run.markdown)
        self.assertEqual((self.root / "sessions" / "session-one" / "runs" / run.id / "report.md").read_text(), run.markdown)


if __name__ == "__main__":
    unittest.main()
