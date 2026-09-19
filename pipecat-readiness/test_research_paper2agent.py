"""Offline boundaries for real Paper2Skill subprocess orchestration and caching."""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from research_paper2agent import PACKAGE_NAME, Paper2AgentWorker, PreparationError, _rank_passages, arxiv_pdf_url


PAPER = "# A test paper\n\n## Introduction\n\n" + "The work introduces a method for research tasks. " * 45 + "\n\n## Evaluation limitations\n\n" + "Evaluation lacks out-of-domain examples and the dataset is small. " * 40
PDF = b"%PDF-1.7\nfixture bytes: the parser is independently mocked in workflow tests."
SOURCE = {"id": "S2", "url": "https://arxiv.org/abs/1706.03762v7", "title": "Test paper",
          "text": "An extracted abstract. " * 50, "packId": "exa", "coverage": "Abstract only"}


class Paper2AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        root = self.directory / "Paper2Agent"
        scripts = root / "skills/paper2agent/paper2skill/scripts"
        scripts.mkdir(parents=True)
        for name in ("paper_bundle.py", "pdf_to_skill.py", "reading_package.py"):
            (scripts / name).write_text("# fixture\n")
        (scripts.parent / "SKILL.md").write_text("# Paper2Skill fixture\n")
        self.worker = Paper2AgentWorker(root, self.directory / "cache", Path(sys.executable))
        self.events = []
        self.commands = []

    def tearDown(self):
        self.temporary.cleanup()

    def emit(self, name, **payload):
        self.events.append((name, payload))

    async def fake_command(self, arguments, work):
        args = list(map(str, arguments))
        self.commands.append(args)
        if args[0] == "-c":
            return {"pages": 12, "encrypted": False}
        stage = args[1]
        if stage == "prepare":
            (work / "review").mkdir()
        if stage == "build":
            package = work / PACKAGE_NAME
            (package / "references").mkdir(parents=True)
            (package / "references/paper.md").write_text(PAPER)
            (package / "SKILL.md").write_text("**Draft: source review remains unresolved.**\n")
        if stage == "verify":
            return {"status": "unreviewed", "mechanical_ok": True, "all_sources_agent_reviewed": False, "issues": []}
        return {"status": "prepared"}

    async def prepare(self, sources=None):
        with patch.object(self.worker, "available", return_value=True), \
                patch.object(self.worker, "_download", new=AsyncMock(return_value=PDF)), \
                patch.object(self.worker, "_command", side_effect=self.fake_command):
            return await self.worker.prepare(sources or [SOURCE], "What are the evaluation limitations?", self.emit,
                                             retrieval_dir=self.directory / "session" / "retrieval")

    def test_only_supported_arxiv_identity_becomes_a_download_url(self):
        valid = {
            "http://arxiv.org/abs/1706.03762v7?context=cs#part": "https://arxiv.org/pdf/1706.03762v7",
            "https://arxiv.org/pdf/1706.03762.pdf": "https://arxiv.org/pdf/1706.03762",
            "https://arxiv.org/abs/hep-th/9901001v2": "https://arxiv.org/pdf/hep-th/9901001v2",
            "https://arxiv.org/html/1706.03762v7": "https://arxiv.org/pdf/1706.03762v7",
            "https://arxiv.org/pdf/math.GT/0309136": None,
        }
        for source, expected in valid.items():
            self.assertEqual(arxiv_pdf_url(source), expected)
        for source in ("https://arxiv.org.evil.example/abs/1706.03762", "http://127.0.0.1/pdf/1706.03762",
                       "https://arxiv.org@evil.example/pdf/1706.03762", "https://user:secret@arxiv.org/pdf/1706.03762",
                       "https://arxiv.org:7860/pdf/1706.03762", "file:///tmp/paper.pdf",
                       "https://arxiv.org/pdf/../../secret", "https://arxiv.org/html/not-an-id",
                       "https://arxiv.org/pdf/1706.03762\\x", "https://arxiv.org/pdf/1706.03762\n"):
            self.assertIsNone(arxiv_pdf_url(source))

    async def test_unsupported_sources_and_missing_runtime_fall_back_visibly(self):
        unsupported = [dict(SOURCE, url="https://publisher.example/paper")]
        result = await self.worker.prepare(unsupported, "Question", self.emit)
        self.assertIs(result, unsupported)
        self.assertEqual(self.events[-1][1]["status"], "unsupported")
        with patch.object(self.worker, "available", return_value=False):
            result = await self.worker.prepare([SOURCE], "Question", self.emit)
        self.assertEqual(result, [SOURCE])
        self.assertEqual(self.events[-1][1]["status"], "unavailable")

    async def test_conversion_keeps_source_ids_and_publishes_honest_cache(self):
        other = dict(SOURCE, id="S1", url="https://publisher.example/paper", text="Other paper evidence. " * 100)
        result = await self.prepare([other, SOURCE])
        self.assertIs(result[0], other)
        replacement = result[1]
        self.assertEqual(replacement["id"], "S2")
        self.assertEqual(replacement["packId"], "paper2agent-draft")
        self.assertEqual(replacement["preparationStatus"], "unreviewed")
        self.assertIn("visual review incomplete", replacement["coverage"])
        self.assertIn("out-of-domain", replacement["text"])
        self.assertLessEqual(sum(len(source["text"]) for source in result), 16000)
        self.assertEqual([args[1] for args in self.commands[1:]], ["prepare", "extract", "review-aid", "build", "verify"])
        self.assertIn("--draft", self.commands[-2])
        self.assertNotIn("--strict", self.commands[-1])
        pointer = self.worker.cache_root / f"{replacement['artifactId']}.json"
        object_root = self.worker.cache_root / json.loads(pointer.read_text())["object"]
        manifest = json.loads((object_root / "manifest.json").read_text())
        self.assertEqual(manifest["sourceSha256"], sha256(PDF).hexdigest())
        self.assertFalse(manifest["verification"]["all_sources_agent_reviewed"])
        self.assertEqual(list(object_root.glob("retrieval-*.json")), [])
        retrieval = json.loads(next((self.directory / "session" / "retrieval").glob("retrieval-*.json")).read_text())
        for passage in retrieval["passages"]:
            self.assertIn(passage["text"], PAPER)
        self.assertNotIn(str(self.directory), repr(self.events))
        self.commands.clear()
        await self.prepare([other, SOURCE])
        self.assertEqual(self.commands, [])
        self.assertTrue(self.events[-1][1]["cacheHit"])

    async def test_followup_reretrieves_cached_package_without_download(self):
        initial = (await self.prepare())[0]
        with patch.object(self.worker, "_download", new=AsyncMock(side_effect=AssertionError("no network"))):
            refreshed = await self.worker.retrieve(initial, "What method does the paper introduce?",
                                                    self.directory / "session-two" / "retrieval")
        self.assertEqual(refreshed["artifactId"], initial["artifactId"])
        self.assertIn("method for research tasks", refreshed["text"])
        self.assertTrue(all(passage["chunkId"] for passage in refreshed["passages"]))
        self.assertEqual(len(list((self.directory / "session-two" / "retrieval").glob("*.json"))), 1)
        serialized_cache = "".join(path.read_text() for path in self.worker.cache_root.rglob("*.json"))
        self.assertNotIn("What method does the paper introduce?", serialized_cache)
        self.assertNotIn("What are the evaluation limitations?", serialized_cache)

    async def test_cache_rejects_modified_package_and_converter_changes(self):
        initial = (await self.prepare())[0]
        pointer = self.worker.cache_root / f"{initial['artifactId']}.json"
        object_root = self.worker.cache_root / json.loads(pointer.read_text())["object"]
        (object_root / PACKAGE_NAME / "references/paper.md").write_text("tampered evidence")
        self.commands.clear()
        await self.prepare()
        self.assertGreater(len(self.commands), 0)
        self.assertFalse(self.events[-1][1]["cacheHit"])
        (self.worker.scripts / "paper_bundle.py").write_text("# converter changed\n")
        updated = (await self.prepare())[0]
        self.assertNotEqual(initial["artifactId"], updated["artifactId"])

    async def test_corrupted_cache_shapes_are_a_cache_miss(self):
        initial = (await self.prepare())[0]
        artifact_id = initial["artifactId"]
        pointer = self.worker.cache_root / f"{artifact_id}.json"
        pointer_text = pointer.read_text()
        object_root = self.worker.cache_root / json.loads(pointer_text)["object"]
        manifest_path = object_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for value in ([], None, {"object": []}, {"object": "../../outside"}):
            pointer.write_text(json.dumps(value))
            self.assertIsNone(self.worker._cached(artifact_id, sha256(PDF).hexdigest(), self.worker._converter_hash()))
        pointer.write_text(pointer_text)
        for value in ([], None, dict(manifest, files=list(manifest["files"])),
                      dict(manifest, verification=[]), dict(manifest, sourceUrl=[]),
                      dict(manifest, pages=True), dict(manifest, package="../../outside")):
            manifest_path.write_text(json.dumps(value))
            self.assertIsNone(self.worker._cached(artifact_id, sha256(PDF).hexdigest(), self.worker._converter_hash()))

    def test_truncated_passage_records_only_lines_actually_included(self):
        paper = "First line with evaluation evidence.\n" + "Second line with limitations. " * 10 + "\nThird line is not included."
        text, passages = _rank_passages(paper, "evaluation limitations", 120)
        self.assertLessEqual(len(text), 120)
        self.assertEqual(passages[0]["startLine"], 1)
        self.assertEqual(passages[0]["endLine"], 2)
        self.assertNotIn("Third line", text)

    def test_paper_url_and_bibliography_do_not_displace_methods_and_limits(self):
        architecture = "The encoder-decoder architecture uses stacked attention layers to represent the input and generate output tokens. " * 4
        constraints = "The computational complexity and memory cost grow with sequence length, which is a scalability limitation for longer inputs. " * 4
        bibliography = "\n\n".join(f"[{number}] Example Author. Method and limitations. arXiv preprint https://arxiv.org/abs/1706.03762v7. " * 5 for number in range(1, 20))
        paper = ("# Example paper\n\nResearch Author author@example.com https://arxiv.org/abs/1706.03762v7\n\n"
                 "Provided proper attribution is provided, the authors grant permission for scholarly use.\n\n"
                 "## Abstract\n\nWe introduce a sequence processing network and evaluate it on benchmark translation tasks.\n\n"
                 "## 3 Model Architecture\n\n" + architecture + "\n\n## 4 Computational Cost\n\n" + constraints
                 + "\n\n**Acknowledgements** Thanks to our collaborators. **References**\n\n" + bibliography)
        query = "Explain the method and limitations of https://arxiv.org/abs/1706.03762v7"
        excerpt, passages = _rank_passages(paper, query, 1500)
        self.assertIn("encoder-decoder architecture", excerpt)
        self.assertIn("scalability limitation", excerpt)
        self.assertNotIn("Example Author", excerpt)
        self.assertNotIn("author@example.com", excerpt)
        self.assertNotIn("grant permission", excerpt)
        self.assertNotIn("## 3", excerpt)
        self.assertLessEqual(len(excerpt), 1500)
        self.assertEqual({passage["section"] for passage in passages}, {"3 Model Architecture", "4 Computational Cost", "Abstract"})
        without_url, _ = _rank_passages(paper, "Explain the method and limitations", 1500)
        self.assertEqual(excerpt, without_url)

    async def test_mechanical_failure_cannot_publish_an_artifact(self):
        async def fail_verification(arguments, work):
            if str(arguments[1]) == "verify":
                return {"status": "mechanical_failure", "mechanical_ok": False, "all_sources_agent_reviewed": False}
            return await self.fake_command(arguments, work)
        with patch.object(self.worker, "available", return_value=True), \
                patch.object(self.worker, "_download", new=AsyncMock(return_value=PDF)), \
                patch.object(self.worker, "_command", side_effect=fail_verification):
            result = await self.worker.prepare([SOURCE], "Question", self.emit)
        self.assertEqual(result, [SOURCE])
        self.assertEqual(self.events[-1][0], "paper2agent.failed")
        self.assertEqual(list(self.worker.cache_root.glob("*.json")), [])
        self.assertEqual(list((self.worker.cache_root / "objects").iterdir()), [])

    async def test_page_limit_prevents_extraction(self):
        with patch.object(self.worker, "available", return_value=True), \
                patch.object(self.worker, "_download", new=AsyncMock(return_value=PDF)), \
                patch.object(self.worker, "_command", new=AsyncMock(return_value={"pages": 61, "encrypted": False})) as command:
            result = await self.worker.prepare([SOURCE], "Question", self.emit)
        self.assertEqual(result, [SOURCE])
        self.assertEqual(command.await_count, 1)
        self.assertIn("60 pages", self.events[-1][1]["message"])

    async def test_download_rejects_cross_host_redirect_before_following(self):
        requests = []
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch("research_paper2agent.httpx.AsyncClient", return_value=client):
            with self.assertRaises(PreparationError):
                await self.worker._download("https://arxiv.org/pdf/1706.03762v7")
        self.assertEqual(requests, ["https://arxiv.org/pdf/1706.03762v7"])

    async def test_download_rejects_non_pdf_and_oversized_content(self):
        for body in (b"<html>Access denied</html>", b"%PDF-1.7" + b"x" * 129):
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
            with patch("research_paper2agent.httpx.AsyncClient", return_value=client), patch("research_paper2agent.MAX_PDF_BYTES", 128):
                with self.assertRaises(PreparationError):
                    await self.worker._download("https://arxiv.org/pdf/1706.03762v7")

    async def test_download_does_not_follow_abstract_or_html_redirects(self):
        for path in ("abs/1706.03762v7", "html/1706.03762v7"):
            requests = []
            def respond(request):
                requests.append(str(request.url))
                return httpx.Response(302, headers={"Location": f"https://arxiv.org/{path}"})
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch("research_paper2agent.httpx.AsyncClient", return_value=client):
                with self.assertRaises(PreparationError):
                    await self.worker._download("https://arxiv.org/pdf/1706.03762v7")
            self.assertEqual(len(requests), 1)

    async def test_total_timeout_falls_back_and_cancellation_propagates(self):
        entered = asyncio.Event()
        async def blocked_download(url):
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.worker, "available", return_value=True), patch.object(self.worker, "_download", side_effect=blocked_download):
            with patch("research_paper2agent.TOTAL_TIMEOUT", 0.01):
                self.assertEqual(await self.worker.prepare([SOURCE], "Question", self.emit), [SOURCE])
            self.assertIn("timed out", self.events[-1][1]["message"])
            entered.clear()
            task = asyncio.create_task(self.worker.prepare([SOURCE], "Question", self.emit))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_cancellation_kills_and_reaps_the_actual_subprocess(self):
        pid_path = self.directory / "child.pid"
        task = asyncio.create_task(self.worker._command(["-c", "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)", pid_path], self.directory))
        for _ in range(100):
            if pid_path.exists():
                break
            await asyncio.sleep(0.01)
        self.assertTrue(pid_path.exists())
        pid = int(pid_path.read_text())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_real_converter_builds_a_synthetic_pdf_as_an_unreviewed_draft(self):
        root = Path(__file__).resolve().parents[2] / "Paper2Agent"
        worker = Paper2AgentWorker(root, self.directory / "real-helper-cache", Path(sys.executable))
        if not worker.available():
            self.skipTest("Optional local Paper2Agent runtime is not installed")
        import pymupdf
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic integration fixture")
        page.insert_textbox(pymupdf.Rect(72, 110, 500, 650),
            "This synthetic fixture evaluates retrieval across two datasets. The evaluation uses measured accuracy and compares a baseline. The documented limitation is a small sample size. " * 7)
        content = document.tobytes()
        document.close()
        with patch.object(worker, "_download", new=AsyncMock(return_value=content)):
            result = await worker.prepare([dict(SOURCE, title="Synthetic integration fixture")], "What are the evaluation limitations?", self.emit)
        self.assertEqual(result[0]["packId"], "paper2agent-draft")
        self.assertEqual(result[0]["preparationStatus"], "unreviewed")
        self.assertIn("sample size", result[0]["text"])
        pointer = worker.cache_root / f"{result[0]['artifactId']}.json"
        manifest = json.loads((worker.cache_root / json.loads(pointer.read_text())["object"] / "manifest.json").read_text())
        self.assertTrue(manifest["verification"]["mechanical_ok"])
        self.assertFalse(manifest["verification"]["all_sources_agent_reviewed"])
        self.assertEqual(manifest["pages"], 1)


if __name__ == "__main__":
    unittest.main()
