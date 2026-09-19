"""Offline discovery, execution-gate and real local Git/process lifecycle tests."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import research_jobs as jobs


CAPABILITIES = {"diskFreeBytes": 5_000_000_000, "ramAvailableBytes": 8_000_000_000,
                "cudaAvailable": False, "gpu": [], "isolatedExecutor": False,
                "runtimes": {"python": "3.12", "node": True, "r": False}}
PAPER = {"id": "S1", "paperId": "arxiv-1234.5678", "title": "A Test Paper",
         "url": "https://arxiv.org/abs/1234.5678", "text": "Our implementation: https://github.com/example/paper-code"}


class JobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.events = []

    def tearDown(self):
        self.temporary.cleanup()

    def emit(self, name, **payload):
        self.events.append((name, payload))

    async def call(self, respond, source=None, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(jobs, "measure_capabilities", AsyncMock(return_value=CAPABILITIES)):
                return await jobs.discover_and_check(source or PAPER, "Explain the method", self.root,
                    client, kwargs.get("exa_key", "exa-secret"), "jev-secret", "jev-latest", self.emit)

    def test_github_urls_restrict_transport_host_and_arguments(self):
        for value in ("file:///etc/passwd", "git@github.com:owner/repo", "https://github.com.evil.org/x/y",
                      "https://secret@github.com/x/y", "https://github.com/x/y?token=secret", "http://github.com/x/y",
                      "https://github.com:443/x/y", "https://github.com/x/%2e%2e", "https://github.com/x/..",
                      "https://github.com/x/-evil", "https://github.com/search?q=paper", "https://github.com/x\\y/a",
                      "https://github.com/x/y\nconfig", "--upload-pack=evil"):
            self.assertIsNone(jobs.github_repository(value), value)
        self.assertEqual(jobs.github_repository("https://github.com/Owner/repo.git"), "https://github.com/Owner/repo")
        self.assertEqual(jobs.github_repository("https://github.com/Owner/repo/tree/main#readme"), "https://github.com/Owner/repo")

    def test_candidates_preserve_provenance_without_official_assumption(self):
        source = {**PAPER, "links": [{"url": "https://github.com/example/second"}, "https://github.com/example/paper-code"]}
        candidates = jobs.repository_candidates(source)
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(item["origin"] == "paper-link" and "status" not in item for item in candidates))
        self.assertTrue(all(item["evidenceUrl"] == PAPER["url"] for item in candidates))

    async def test_no_repository_continues_without_clone_or_execution(self):
        def respond(request):
            self.assertEqual(str(request.url), "https://api.exa.ai/search")
            payload = json.loads(request.content)
            self.assertNotIn("category", payload)
            self.assertEqual(payload["includeDomains"], ["github.com"])
            return httpx.Response(200, json={"results": []})
        with patch.object(jobs, "clone_for_inspection", AsyncMock()) as clone:
            result = await self.call(respond, {**PAPER, "text": "No code URL in this paper."})
        clone.assert_not_called()
        self.assertEqual(result["repository"]["status"], "not-found")
        self.assertEqual(result["state"], "unsupported_operation")
        self.assertFalse(result["executed"])
        self.assertEqual(self.events[-1][0], "experiment.blocked")
        self.assertNotIn("secret", repr(result) + repr(self.events))

    async def test_wrong_repository_is_not_cloned_and_one_fallback_search_occurs(self):
        calls = []
        def respond(request):
            calls.append(str(request.url))
            if request.url.host == "api.exa.ai":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={"answers": {"R1": {"choice": "unrelated", "confidence": 0.99}}})
        with patch.object(jobs, "clone_for_inspection", AsyncMock()) as clone:
            result = await self.call(respond)
        clone.assert_not_called()
        self.assertEqual(result["repository"]["status"], "uncertain")
        self.assertEqual(calls.count("https://api.exa.ai/search"), 1)

    async def test_verified_repository_pins_before_compute_gate_and_does_not_execute(self):
        (self.root / "README.md").write_text("This implementation requires CUDA. At least 16 GB RAM is required.\n")
        (self.root / "pyproject.toml").write_text('[project]\nname="fixture"\n')
        clone_result = {"commit": "a" * 40, "relativePath": "repo/paper-code", "checkoutScope": "README and manifests only"}
        def respond(request):
            self.assertEqual(request.url.host, "api.typesafe.ai")
            self.assertEqual(json.loads(request.content)["questions"]["R1"]["type"], "choice")
            return httpx.Response(200, json={"answers": {"R1": {"choice": "author-linked", "confidence": 0.94}}})
        with patch.object(jobs, "clone_for_inspection", AsyncMock(return_value=(clone_result, self.root))) as clone:
            result = await self.call(respond)
        clone.assert_awaited_once_with("https://github.com/example/paper-code", self.root)
        self.assertEqual(result["repository"]["commit"], "a" * 40)
        self.assertIn(result["state"], {"blocked_compute", "blocked_environment"})
        self.assertFalse(result["executed"])
        names = [name for name, _ in self.events]
        self.assertLess(names.index("repo.cloned"), names.index("compute.checked"))
        self.assertNotIn("experiment.started", names)

    async def test_search_hit_requires_explicit_jev_association(self):
        def respond(request):
            if request.url.host == "api.exa.ai":
                return httpx.Response(200, json={"results": [{"url": "https://github.com/example/paper-code", "text": "A generic matching search hit."}]})
            return httpx.Response(200, json={"answers": {"R1": {"choice": "author-linked", "confidence": True}}})
        with patch.object(jobs, "clone_for_inspection", AsyncMock()) as clone:
            result = await self.call(respond, {**PAPER, "text": "No code URL."})
        clone.assert_not_called()
        self.assertEqual(result["repository"]["status"], "uncertain")

    def test_gate_distinguishes_cpu_memory_cuda_unknown_and_missing_worker(self):
        req = {"runtime": "python", "cudaRequired": False}
        self.assertEqual(jobs.execution_gate(req, CAPABILITIES)[0], "blocked_environment")
        state, reason = jobs.execution_gate({**req, "cudaRequired": True}, CAPABILITIES)
        self.assertEqual(state, "blocked_environment")
        self.assertIn("CUDA", reason)
        self.assertEqual(jobs.execution_gate({**req, "ramBytes": 10_000_000_000}, CAPABILITIES)[0], "blocked_compute")
        self.assertEqual(jobs.execution_gate({**req, "runtime": "unknown"}, CAPABILITIES)[0], "requirements_unknown")
        self.assertEqual(jobs.execution_gate({**req, "runtime": "r"}, CAPABILITIES)[0], "blocked_environment")
        isolated = {**CAPABILITIES, "isolatedExecutor": True}
        self.assertEqual(jobs.execution_gate(req, isolated)[0], "unsupported_operation")
        self.assertEqual(jobs.execution_gate({**req, "operation": "test"}, isolated)[0], "requirements_unknown")
        self.assertEqual(jobs.execution_gate({**req, "operation": "test", "requirementsComplete": True}, isolated)[0], "eligible")

    def test_requirements_do_not_follow_symlinks_or_infer_cuda_from_dependency(self):
        secret = self.root / "secret.txt"
        secret.write_text("Requires CUDA and at least 999 GB RAM.")
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "README.md").symlink_to(secret)
        (repo / "requirements.txt").write_text("torch\ncuda-python\n")
        result = jobs.inspect_requirements(repo)
        self.assertEqual(result["runtime"], "python")
        self.assertFalse(result["cudaRequired"])
        self.assertIsNone(result["ramBytes"])
        self.assertNotIn("README.md", result["inspectedFiles"])
        self.assertFalse(result["requirementsComplete"])

    async def test_provider_failure_and_timeout_leave_actionable_terminal_events(self):
        result = await self.call(lambda _: httpx.Response(500, text="secret provider body"))
        self.assertEqual(result["state"], "blocked_environment")
        self.assertNotIn("secret", repr(result) + repr(self.events))
        async def wait_forever(_):
            await asyncio.Event().wait()
        with patch.object(jobs, "TOTAL_TIMEOUT", 0.01):
            result = await self.call(wait_forever)
        self.assertIn("time limit", result["reason"])
        self.assertEqual(self.events[-1][0], "experiment.blocked")

    async def test_cancellation_propagates(self):
        entered = asyncio.Event()
        async def wait_forever(_):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(self.call(wait_forever))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_process_cancellation_reaps_parent(self):
        pid_file = self.root / "pid"
        task = asyncio.create_task(jobs._process([sys.executable, "-c",
            "import os,time,pathlib;pathlib.Path(" + repr(str(pid_file)) + ").write_text(str(os.getpid()));time.sleep(30)"], timeout=10))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        self.assertTrue(pid_file.exists())
        pid = int(pid_file.read_text())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    @unittest.skipUnless(shutil.which("git"), "Git is required for local clone lifecycle validation")
    async def test_real_clone_pins_sparse_tree_disables_secrets_and_cleans_staging(self):
        upstream = self.root / "upstream"
        upstream.mkdir()
        def git(*arguments):
            return subprocess.check_output(["git", *arguments], cwd=upstream, stderr=subprocess.DEVNULL).decode().strip()
        git("init")
        (upstream / "README.md").write_text("Fixture research paper implementation.\n")
        (upstream / "pyproject.toml").write_text('[project]\nname="fixture"\n')
        (upstream / "untrusted.py").write_text("raise RuntimeError('Never execute me')\n")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "Fixture")
        commit = git("rev-parse", "HEAD")
        process = jobs._process
        commands = []
        async def local_process(arguments, **kwargs):
            args = list(arguments)
            commands.append(args)
            self.assertNotIn("TYPESAFE_API_KEY", kwargs.get("env", {}))
            self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            if "clone" in args:
                index = args.index("https://github.com/example/paper-code.git")
                args[index] = upstream.as_uri()
                args[1:1] = ["-c", "protocol.file.allow=always"]
            return await process(args, **kwargs)
        workspace = self.root / "job"
        with patch.object(jobs, "_process", local_process):
            result, checkout = await jobs.clone_for_inspection("https://github.com/example/paper-code", workspace)
        self.assertEqual(result["commit"], commit)
        self.assertTrue((checkout / "README.md").exists())
        self.assertFalse((checkout / "untrusted.py").exists())
        self.assertFalse(list((workspace / "repo").glob(".clone-*")))
        clone = next(command for command in commands if "clone" in command)
        self.assertIn("--depth=1", clone)
        self.assertIn("core.hooksPath=/dev/null", clone)
        self.assertIn("protocol.allow=never", clone)
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip(), commit)
        self.assertEqual(subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=checkout).returncode, 1)

    async def test_failed_clone_cleans_owned_staging_only(self):
        untouched = self.root / "existing.txt"
        untouched.write_text("Keep this")
        with patch.object(jobs, "_process", AsyncMock(side_effect=jobs.JobError("Fixture failure."))):
            with self.assertRaises(jobs.JobError):
                await jobs.clone_for_inspection("https://github.com/example/paper-code", self.root)
        self.assertEqual(untouched.read_text(), "Keep this")
        self.assertFalse(list((self.root / "repo").iterdir()))


if __name__ == "__main__":
    unittest.main()
