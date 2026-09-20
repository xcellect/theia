"""Durable-session invariants without providers or a running web server."""

import json
from pathlib import Path
import tempfile
import unittest

from research_workspace import WorkspaceStore


SOURCE = {"id": "S1", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762v7",
          "text": "The encoder uses six layers. [Exact source passage]", "coverage": "Selected unreviewed PDF passages",
          "preparationStatus": "unreviewed", "artifactId": "fixture-artifact"}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.store = WorkspaceStore(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def begin(self, run_id="run-1", session_id="session-a", question="Explain the paper", request_id=None):
        return self.store.begin_run(run_id, session_id, question, request_id or run_id, "fingerprint-" + question)

    def complete(self, run_id="run-1", session_id="session-a", text="A cited answer.", source=None):
        run = self.begin(run_id, session_id)
        run["markdown"] = text
        run["sources"] = {source["id"]: source} if source else {}
        run["events"] = [{"runId": run_id, "seq": 1, "type": "run.started", "payload": {}},
                         {"runId": run_id, "seq": 2, "type": "run.completed", "payload": {"status": "completed"}}]
        return self.store.save_run(run)

    def restart(self):
        self.store.close()
        self.store = WorkspaceStore(self.root)

    def test_reports_sources_and_two_papers_survive_restart_without_session_bleed(self):
        first = self.store.save_paper("session-a", SOURCE)
        second = self.store.save_paper("session-a", dict(SOURCE, title="A second paper", url="https://arxiv.org/abs/2005.11401v4", text="Different source evidence."))
        report = "Six encoder layers. [" + first["sourceId"] + "]"
        self.complete(text=report, source=first["source"])
        self.store.save_paper_answer("session-a", first["paperId"], "run-1", report)
        self.complete("run-2", source=second["source"])
        self.store.save_paper_answer("session-a", second["paperId"], "run-2", "Second findings.")
        self.store.ensure_session("session-b")
        self.restart()
        self.assertEqual(self.store.get_run("run-1")["markdown"], report)
        self.assertEqual(self.store.get_run("run-1")["sources"][first["sourceId"]]["text"], SOURCE["text"])
        own = self.store.session("session-a")
        self.assertEqual(len(own["papers"]), 2)
        self.assertEqual(len(own["messages"]), 4)
        self.assertEqual(len(own["papers"][0]["reports"]), 1)
        empty = self.store.session("session-b")
        self.assertEqual((empty["papers"], empty["messages"], empty["runs"]), ([], [], []))
        self.assertEqual(self.store.paper_sources("session-b"), [])
        self.assertTrue((self.root / "sessions/session-a/runs/run-1/report.md").exists())
        retrieval = self.root / "sessions/session-a/papers" / first["paperId"] / "retrieval/run-1.json"
        self.assertEqual(json.loads(retrieval.read_text())["source"]["text"], SOURCE["text"])

    def test_request_idempotency_is_scoped_to_session_and_conflicts_rejected(self):
        first = self.begin(request_id="same-request")
        repeated = self.begin("different-run", request_id="same-request")
        self.assertEqual(first["runId"], repeated["runId"])
        self.assertEqual(len(self.store.session("session-a")["messages"]), 1)
        with self.assertRaisesRegex(ValueError, "different question"):
            self.store.begin_run("third-run", "session-a", "Different", "same-request", "different-fingerprint")
        other = self.begin("run-other", "session-b", request_id="same-request")
        self.assertEqual(other["sessionId"], "session-b")
        self.restart()
        self.assertEqual(self.store.find_request("session-a", "same-request")["runId"], "run-1")

    def test_restart_marks_only_unfinished_run_and_job_interrupted_once(self):
        paper = self.store.save_paper("session-a", SOURCE)
        self.begin()
        self.store.save_run({"id": "run-1", "markdown": "Partial result", "events": [
            {"seq": 1, "type": "run.started", "payload": {}}]})
        self.store.save_job("session-a", paper["paperId"], {"jobId": "job-1", "state": "running"})
        self.store.save_job("session-a", paper["paperId"], {"jobId": "job-2", "state": "blocked_compute"})
        self.complete("run-done")
        self.restart()
        interrupted = self.store.get_run("run-1")
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertTrue(interrupted["done"])
        self.assertEqual(interrupted["markdown"], "Partial result")
        self.assertEqual(interrupted["events"][-1]["payload"]["code"], "SERVER_RESTARTED")
        self.assertEqual(self.store.get_run("run-done")["status"], "completed")
        jobs = self.store.session("session-a")["papers"][0]["jobs"]
        self.assertEqual({j["jobId"]: j["state"] for j in jobs}, {"job-1": "interrupted", "job-2": "blocked_compute"})
        self.restart()
        self.assertEqual(len(self.store.get_run("run-1")["events"]), 2)
        self.assertEqual(len([m for m in self.store.session("session-a")["messages"] if m["runId"] == "run-1"]), 2)

    def test_event_batches_are_deduplicated_and_completed_history_cannot_be_rewritten(self):
        self.begin()
        event = {"seq": 1, "type": "agent.delta", "payload": {"text": "Finding"}}
        self.store.save_run({"id": "run-1", "events": [event]})
        self.store.save_run({"id": "run-1", "events": [event], "markdown": "Draft"})
        self.assertEqual(len(self.store.get_run("run-1")["events"]), 1)
        self.store.save_run({"id": "run-1", "markdown": "Final", "events": [
            {"seq": 2, "type": "run.completed", "payload": {"status": "completed"}}]})
        self.store.save_run({"id": "run-1", "done": False, "markdown": "Late callback"})
        self.assertEqual(self.store.get_run("run-1")["markdown"], "Final")
        self.assertEqual(self.store.get_run("run-1")["seq"], 2)

    def test_ten_turns_have_bounded_memory_without_losing_raw_history(self):
        paper = self.store.save_paper("session-a", SOURCE)
        for index in range(10):
            self.complete("run-" + str(index), text=("Finding " + str(index) + ". ") * 1200, source=paper["source"])
            self.store.save_paper_answer("session-a", paper["paperId"], "run-" + str(index), "Short note " + str(index), "partial" if index == 9 else "completed")
        memory = self.store.memory("session-a", [paper["paperId"]])
        self.assertLessEqual(len(memory), 11250)
        self.assertIn("not source evidence", memory)
        self.assertIn('"status":"partial"', memory)
        state = self.store.session("session-a")
        self.assertEqual(len(state["messages"]), 20)
        self.assertGreater(state["summarizedThroughMessageId"], 0)
        self.assertLessEqual(len(state["summary"]), 3000)
        self.assertEqual(self.store.paper_sources("session-a", [paper["paperId"]])[0]["text"], SOURCE["text"])
        self.restart()
        self.assertEqual(self.store.memory("session-a", [paper["paperId"]]), memory)
        self.assertEqual(len(self.store.session("session-a")["messages"]), 20)

    def test_paper_identity_deduplicates_arxiv_forms_and_preserves_citation_revisions(self):
        paper = self.store.save_paper("session-a", SOURCE)
        same = self.store.save_paper("session-a", dict(SOURCE, id="S8", url="https://arxiv.org/pdf/1706.03762v7.pdf"))
        self.assertEqual(paper["paperId"], same["paperId"])
        self.assertEqual(paper["sourceId"], same["sourceId"])
        self.complete(source=paper["source"])
        revised = self.store.save_paper("session-a", dict(SOURCE, text="Another actual passage."))
        self.assertEqual(revised["paperId"], paper["paperId"])
        self.assertNotEqual(revised["sourceId"], paper["sourceId"])
        self.assertEqual(len(self.store.session("session-a")["papers"]), 1)
        self.assertEqual(self.store.get_run("run-1")["sources"][paper["sourceId"]]["text"], SOURCE["text"])

    def test_cross_session_references_and_path_traversal_are_rejected(self):
        paper = self.store.save_paper("session-a", SOURCE)
        self.store.ensure_session("session-b")
        for value in ("../outside", "/tmp/absolute", "a/b", "", "a\\b", "session\n"):
            with self.assertRaises(ValueError):
                self.store.ensure_session(value)
        with self.assertRaises(ValueError):
            self.store.paper_sources("session-b", [paper["paperId"]])
        with self.assertRaises(ValueError):
            self.store.save_job("session-b", paper["paperId"], {"jobId": "job", "state": "running"})
        self.begin()
        with self.assertRaises(ValueError):
            self.store.save_run({"id": "run-1", "sessionId": "session-b"})
        with self.assertRaises(ValueError):
            self.store.save_run({"id": "run-1", "events": [{"seq": 1, "runId": "run-other"}]})
        self.assertEqual(self.store.get_run("run-1")["events"], [])

    def test_symlink_escape_cannot_create_an_artifact_outside_workspace(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "sessions").mkdir()
        (self.root / "sessions/escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.ensure_session("escape")
        self.assertEqual(list(outside.iterdir()), [])

    def test_selected_memory_excludes_other_papers_findings(self):
        first = self.store.save_paper("session-a", SOURCE)
        other = self.store.save_paper("session-a", dict(SOURCE, url="https://arxiv.org/abs/2005.11401", title="Other"))
        self.complete()
        self.store.save_paper_answer("session-a", first["paperId"], "run-1", "First paper finding.")
        self.store.save_paper_answer("session-a", other["paperId"], "run-1", "Secret second finding.")
        memory = self.store.memory("session-a", [first["paperId"]])
        self.assertIn("First paper finding", memory)
        self.assertNotIn("Secret second finding", memory)

    def test_passage_identity_is_saved_and_empty_rediscovery_retains_readable_source(self):
        source = dict(SOURCE, section="Selected methods", passages=[{"chunkId": "exact-chunk", "startLine": 20, "endLine": 22, "text": SOURCE["text"]}])
        paper = self.store.save_paper("session-a", source)
        self.complete(source=paper["source"])
        finding = self.store.save_paper_answer("session-a", paper["paperId"], "run-1", "Six layers. [" + paper["sourceId"] + "]")
        self.assertEqual(finding["chunkIds"], ["exact-chunk"])
        self.assertEqual(finding["sourceVersion"], "v7")
        empty = self.store.save_paper("session-a", dict(SOURCE, text=""))
        self.assertEqual(empty["source"]["section"], "Selected methods")
        self.assertEqual(empty["sourceId"], paper["sourceId"])
        self.assertEqual(empty["source"]["text"], SOURCE["text"])

    def test_job_id_cannot_be_reassigned_to_another_paper(self):
        first = self.store.save_paper("session-a", SOURCE)
        second = self.store.save_paper("session-a", dict(SOURCE, url="https://arxiv.org/abs/2005.11401"))
        self.store.save_job("session-a", first["paperId"], {"jobId": "job-1", "state": "queued"})
        with self.assertRaisesRegex(ValueError, "move between papers"):
            self.store.save_job("session-a", second["paperId"], {"jobId": "job-1", "state": "running"})

    def test_history_pages_preserve_every_turn_report_and_message(self):
        for index in range(45):
            self.complete(f"run-{index:02}", text=f"# Report {index}\n\nFull cited answer.")
        pages, before = [], None
        while True:
            page = self.store.session("session-a", before=before, limit=20, create=False)
            self.assertEqual(page["totalRuns"], 45)
            self.assertEqual(len(page["messages"]), len(page["runs"]) * 2)
            self.assertTrue(all(run["done"] and run["markdown"].startswith("# Report") for run in page["runs"]))
            pages[0:0] = page["runs"]
            if not page["hasMore"]:
                self.assertIsNone(page["nextBefore"])
                break
            before = page["nextBefore"]
        self.assertEqual([run["runId"] for run in pages], [f"run-{index:02}" for index in range(45)])
        with self.assertRaisesRegex(ValueError, "cursor"):
            self.store.session("session-a", before="missing-run", limit=20)

    def test_old_completed_snapshot_retains_partial_event_status_after_reload(self):
        run = self.begin()
        self.store.save_run(dict(run, markdown="# Uncertain report"), [
            {"seq": 1, "type": "report.completed", "payload": {"partial": True}},
            {"seq": 2, "type": "run.completed", "payload": {"status": "completed", "partial": True}},
        ])
        self.assertNotIn("partial", self.store.get_run("run-1"))
        self.restart()
        restored = self.store.session("session-a", limit=20)["runs"][0]
        self.assertEqual(restored["status"], "completed")
        self.assertTrue(restored["partial"])
        self.assertEqual(restored["markdown"], "# Uncertain report")

    def test_delete_removes_all_session_records_files_and_keeps_other_workspace(self):
        paper = self.store.save_paper("session-a", SOURCE)
        self.complete(source=paper["source"])
        self.store.save_paper_answer("session-a", paper["paperId"], "run-1", "Saved findings")
        self.store.save_job("session-a", paper["paperId"], {"jobId": "job-1", "state": "blocked_compute"})
        self.complete("other-run", "other-session", text="Keep this report")
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("Do not delete")
        (self.root / "sessions/session-a/external.txt").symlink_to(outside)
        self.assertTrue(self.store.delete_session("session-a"))
        self.assertFalse((self.root / "sessions/session-a").exists())
        self.assertEqual(outside.read_text(), "Do not delete")
        for table in ("messages", "papers", "paper_answers", "jobs", "runs"):
            self.assertEqual(self.store.db.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", ("session-a",)).fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM events WHERE run_id='run-1'").fetchone()[0], 0)
        self.assertEqual(self.store.get_run("other-run")["markdown"], "Keep this report")
        self.assertFalse(self.store.delete_session("session-a"))
        self.assertEqual(self.store.session("session-a", create=False)["runs"], [])
        self.assertNotIn("session-a", [session["sessionId"] for session in self.store.sessions()])
        self.restart()
        self.assertIsNone(self.store.get_run("run-1"))
        self.assertEqual(self.store.get_run("other-run")["markdown"], "Keep this report")

    def test_delete_rejects_active_work_and_invalid_or_symlink_session_paths(self):
        self.begin()
        with self.assertRaisesRegex(RuntimeError, "running"):
            self.store.delete_session("session-a")
        self.complete()
        paper = self.store.save_paper("session-a", SOURCE)
        self.store.save_job("session-a", paper["paperId"], {"jobId": "job-1", "state": "cloning"})
        with self.assertRaisesRegex(RuntimeError, "jobs"):
            self.store.delete_session("session-a")
        for bad in ("../session-a", "", "a/b", None):
            with self.assertRaises(ValueError):
                self.store.delete_session(bad)
        self.store.save_job("session-a", paper["paperId"], {"jobId": "job-1", "state": "completed"})
        directory = self.root / "sessions/session-a"
        relocated = self.root / "relocated"
        directory.rename(relocated)
        directory.symlink_to(relocated, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.store.delete_session("session-a")
        self.assertTrue((relocated / "runs/run-1/report.md").exists())


if __name__ == "__main__":
    unittest.main()
