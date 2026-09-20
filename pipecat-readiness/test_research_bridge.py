"""Research voice lifecycle and actual Pipecat worker checks without providers."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pipecat.frames.frames import (InputAudioRawFrame, InputTransportMessageFrame, InterimTranscriptionFrame,
                                  LLMContextFrame, LLMTextFrame, TranscriptionFrame, TTSSpeakFrame)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from research_bridge import ResearchTranscriptObserver, ResearchTurnProcessor
from test_research import DECISION
from test_gradium_pipeline import GRADIUM_ENV, OfflineGradiumSTT
from test_voice_pipeline import FixtureTTS, MemoryTransport
from test_voice_server import FakeConnection
from voice_config import read_gradium_config
import voice_pipeline


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.run = SimpleNamespace(id="new-run", question="Research question")
        self.runner = SimpleNamespace(voice=None, active_id=None, latest_id=None, runs={},
                                      start=AsyncMock(return_value=self.run))
        self.bridge = ResearchTurnProcessor(self.runner)
        self.run.session_id = self.bridge.session_id
        self.bridge.worker = SimpleNamespace(queue_frame=AsyncMock())
        self.bridge.rtvi = SimpleNamespace(send_server_message=AsyncMock(), interrupt_bot=AsyncMock())

    async def asyncTearDown(self):
        await self.bridge.close()

    async def test_only_committed_turn_starts_once_context_frames_do_not_submit(self):
        await self.bridge.ready()
        self.bridge.submit("What is verified?", "turn-123")
        self.bridge.submit("What is verified?", "turn-123")
        self.bridge.submit("  ", "turn-empty")
        await asyncio.gather(*list(self.bridge.submissions))
        self.runner.start.assert_awaited_once()
        self.assertEqual(self.runner.start.call_args.args[0]["question"], "What is verified?")
        self.bridge.push_frame = AsyncMock()
        context = LLMContextFrame(LLMContext(messages=[{"role": "user", "content": "What is verified?"}]))
        await self.bridge.process_frame(context, FrameDirection.DOWNSTREAM)
        await self.bridge.process_frame(context, FrameDirection.DOWNSTREAM)
        self.runner.start.assert_awaited_once()
        self.bridge.push_frame.assert_not_awaited()

    async def test_followup_inherits_only_its_session_run_sources(self):
        self.runner.runs["typed-completed"] = SimpleNamespace(source_ids=["paper2agent-code"], session_id="tab-one")
        self.runner.latest_id = "another-tabs-run"
        self.runner.voice_context = {"sessionId": "tab-one", "previousRunId": "typed-completed"}
        self.runner.active_id = None
        self.bridge.previous_run_id = "older-voice-run"
        await self.bridge.ready()
        self.bridge.submit("Focus on what it does not verify.", "followup")
        await asyncio.gather(*list(self.bridge.submissions))
        payload = self.runner.start.call_args.args[0]
        self.assertEqual(payload["previousRunId"], "typed-completed")
        self.assertEqual(payload["sourceIds"], ["paper2agent-code"])
        self.assertEqual(self.bridge.previous_run_id, "new-run")

    async def test_fresh_session_does_not_inherit_global_latest_or_other_tabs_run(self):
        self.runner.runs["old-test"] = SimpleNamespace(source_ids=["paper2agent-code"], session_id="other-tab")
        self.runner.latest_id = "old-test"
        self.runner.voice_context = {"sessionId": "fresh-tab", "previousRunId": "old-test", "sourceIds": [], "searchEnabled": True}
        await self.bridge.ready()
        self.bridge.submit("Find papers on retrieval augmented generation", "fresh")
        await asyncio.gather(*list(self.bridge.submissions))
        payload = self.runner.start.call_args.args[0]
        self.assertIsNone(payload["previousRunId"])
        self.assertEqual(payload["sourceIds"], [])
        self.assertEqual(payload["sessionId"], "fresh-tab")
        self.assertTrue(payload["searchEnabled"])

    async def test_new_research_session_clears_previous_voice_context(self):
        self.runner.runs["previous"] = SimpleNamespace(source_ids=["paper2agent-code"], session_id=self.bridge.session_id)
        self.bridge.previous_run_id = "previous"
        self.runner.voice_context = {"sessionId": "new-tab-session", "previousRunId": None, "sourceIds": []}
        context, prior = self.bridge._context()
        self.assertIsNone(prior)
        self.assertIsNone(context["previousRunId"])
        self.assertIsNone(self.bridge.previous_run_id)

    async def test_ready_announce_summary_stale_speech_and_interrupt(self):
        await self.bridge.ready()
        self.assertIs(self.runner.voice, self.bridge)
        greeting = self.bridge.worker.queue_frame.call_args.args[0]
        self.assertIsInstance(greeting, TTSSpeakFrame)
        self.assertEqual(greeting.text, "What would you like to investigate?")
        self.assertFalse(greeting.append_to_context)
        self.runner.active_id = self.run.id
        await self.bridge.announce(self.run)
        self.bridge.rtvi.send_server_message.assert_awaited_once_with({
            "type": "research.started", "runId": "new-run", "question": "Research question", "sessionId": self.bridge.session_id})
        await self.bridge.speak("The report is ready.", self.run.id)
        self.assertEqual(self.bridge.worker.queue_frame.call_args.args[0].text, "The report is ready.")
        before = self.bridge.worker.queue_frame.await_count
        await self.bridge.speak("Stale report", "older-run")
        self.assertEqual(self.bridge.worker.queue_frame.await_count, before)
        await self.bridge.interrupt()
        self.bridge.rtvi.interrupt_bot.assert_awaited_once()

    async def test_current_ui_excerpt_is_used_by_voice(self):
        self.runner.voice_context = {"sourceIds": [], "pastedText": "def selected(): pass", "pastedKind": "code"}
        await self.bridge.ready()
        self.bridge.submit("Explain paper to agent", "selected-excerpt")
        await asyncio.gather(*list(self.bridge.submissions))
        payload = self.runner.start.call_args.args[0]
        self.assertEqual(payload["sourceIds"], [])
        self.assertEqual(payload["pastedText"], "def selected(): pass")
        self.assertEqual(payload["question"], "Explain Paper2Agent")

    async def test_close_cancels_pending_submission_and_detaches(self):
        pending = asyncio.Event()
        async def waiting_start(payload):
            pending.set()
            await asyncio.Event().wait()
        self.runner.start = AsyncMock(side_effect=waiting_start)
        await self.bridge.ready()
        self.bridge.submit("Pending question", "pending-turn")
        await pending.wait()
        tasks = list(self.bridge.submissions)
        await self.bridge.close()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.bridge.submissions, set())
        self.assertIsNone(self.runner.voice)
        self.assertFalse(self.bridge.connected)
        self.bridge.submit("Disconnected", "second-turn")
        self.assertEqual(self.runner.start.await_count, 1)

    async def test_provider_error_message_never_exposes_raw_error(self):
        self.runner.start.side_effect = RuntimeError("fixture-secret upstream response")
        await self.bridge.ready()
        self.bridge.submit("Question", "failed-turn")
        await asyncio.gather(*list(self.bridge.submissions))
        event = self.bridge.rtvi.send_server_message.call_args.args[0]
        self.assertEqual(event["type"], "research.error")
        self.assertNotIn("fixture-secret", str(event))

    async def test_live_preview_uses_jev_context_without_launching_agents(self):
        self.runner._routing = AsyncMock(return_value=(DECISION["answers"], "jev-latest"))
        self.runner.voice_context = {"sourceIds": [], "pastedText": "def selected(): pass", "pastedKind": "code"}
        await self.bridge.ready()
        self.bridge.preview("What does paper to agent verify?", False)
        await asyncio.gather(*list(self.bridge.preview_tasks))
        self.runner.start.assert_not_awaited()
        self.runner._routing.assert_awaited_once()
        preview_run = self.runner._routing.call_args.args[0]
        self.assertEqual(preview_run.question, "What does Paper2Agent verify?")
        self.assertEqual(preview_run.source_ids, [])
        self.assertEqual(preview_run.pasted_text, "def selected(): pass")
        messages = [call.args[0] for call in self.bridge.rtvi.send_server_message.call_args_list]
        self.assertEqual([message["phase"] for message in messages], ["pending", "ready"])
        self.assertTrue(all(message["speculative"] for message in messages))
        self.assertEqual(messages[-1]["answers"], DECISION["answers"])

    async def test_preview_coalesces_updates_with_one_request_in_flight(self):
        started, release = asyncio.Event(), asyncio.Event()
        in_flight, maximum, calls = 0, 0, []
        async def routing(run):
            nonlocal in_flight, maximum
            calls.append(run.question)
            in_flight += 1
            maximum = max(maximum, in_flight)
            started.set()
            await release.wait()
            in_flight -= 1
            return DECISION["answers"], "jev-latest"
        self.runner._routing = routing
        await self.bridge.ready()
        with patch("research_bridge.PREVIEW_INTERVAL_SECONDS", 0.01):
            self.bridge.preview("What does Paper2Agent", False)
            await started.wait()
            self.bridge.preview("What does Paper2Agent verify", False)
            self.bridge.preview("What does Paper2Agent verify and test?", False)
            self.assertEqual(len(calls), 1)
            release.set()
            await asyncio.gather(*list(self.bridge.preview_tasks))
        self.assertEqual(maximum, 1)
        self.assertEqual(calls, ["What does Paper2Agent", "What does Paper2Agent verify and test?"])
        self.runner.start.assert_not_awaited()

    async def test_committed_turn_invalidates_even_a_late_preview_result(self):
        started = asyncio.Event()
        async def routing(run):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Model a provider finishing just as cancellation arrived.
                return DECISION["answers"], "jev-latest"
        self.runner._routing = routing
        await self.bridge.ready()
        observer = ResearchTranscriptObserver(self.bridge)
        observer.committed = "Earlier fragment"
        self.bridge.preview("What is being verified?", False)
        await started.wait()
        preview_tasks = list(self.bridge.preview_tasks)
        old_turn_id = self.bridge.preview_turn_id
        self.bridge.submit("What is being verified?", "committed-turn")
        await asyncio.gather(*preview_tasks, *list(self.bridge.submissions))
        self.assertNotEqual(self.bridge.preview_turn_id, old_turn_id)
        self.assertEqual(observer.committed, "")
        messages = [call.args[0] for call in self.bridge.rtvi.send_server_message.call_args_list]
        self.assertFalse(any(message.get("phase") == "ready" for message in messages))
        self.runner.start.assert_awaited_once()

    async def test_preview_timeout_is_bounded_and_does_not_block_committed_work(self):
        async def routing(run):
            await asyncio.Event().wait()
        self.runner._routing = routing
        await self.bridge.ready()
        with patch("research_bridge.PREVIEW_TIMEOUT_SECONDS", 0.02):
            self.bridge.preview("Explain the verification process.", False)
            await asyncio.gather(*list(self.bridge.preview_tasks))
        event = self.bridge.rtvi.send_server_message.call_args.args[0]
        self.assertEqual(event["phase"], "error")
        self.bridge.submit("Explain the verification process.", "after-timeout")
        await asyncio.gather(*list(self.bridge.submissions))
        self.runner.start.assert_awaited_once()

    async def test_transcript_observer_combines_segments_without_consuming_frames(self):
        bridge = SimpleNamespace(preview=Mock(), reset_preview=Mock())
        observer = ResearchTranscriptObserver(bridge)
        observer.push_frame = AsyncMock()
        frames = [
            InterimTranscriptionFrame(text="What does", user_id="user", timestamp="t1"),
            TranscriptionFrame(text="What does", user_id="user", timestamp="t1"),
            InterimTranscriptionFrame(text="Paper2Agent verify?", user_id="user", timestamp="t2"),
            TranscriptionFrame(text="Paper2Agent verify?", user_id="user", timestamp="t2", finalized=True),
        ]
        for frame in frames:
            await observer.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertEqual(observer.push_frame.await_count, len(frames))
        self.assertEqual(bridge.preview.call_args.args, ("What does Paper2Agent verify?", True))
        observer.clear()
        self.assertEqual(observer.committed, "")
        self.assertEqual(observer.interim, "")

    async def test_close_cancels_preview_and_emits_no_late_result(self):
        started = asyncio.Event()
        async def routing(run):
            started.set()
            await asyncio.Event().wait()
        self.runner._routing = routing
        await self.bridge.ready()
        self.bridge.preview("Still speaking about Paper2Agent", False)
        await started.wait()
        tasks = list(self.bridge.preview_tasks)
        await self.bridge.close()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.bridge.preview_tasks, set())
        self.assertEqual(self.bridge.rtvi.send_server_message.call_args.args[0]["phase"], "pending")


class ResearchFixtureTTS(FixtureTTS):
    """Convert real queued TTSSpeakFrame requests to simulated audible output."""

    async def process_frame(self, frame, direction):
        if isinstance(frame, TTSSpeakFrame):
            await super().process_frame(LLMTextFrame(text=frame.text), direction)
        else:
            await super().process_frame(frame, direction)


class SimulatedRunner:
    def __init__(self):
        self.voice = None
        self.latest_id = None
        self.active_id = None
        self.runs = {}
        self.requests = []
        self.started = asyncio.Event()

    async def _routing(self, run):
        return DECISION["answers"], "jev-latest"

    async def start(self, payload):
        self.requests.append(payload)
        run = SimpleNamespace(id=f"voice-run-{len(self.requests)}", question=payload["question"],
                              source_ids=payload["sourceIds"], session_id=payload.get("sessionId"))
        self.runs[run.id] = run
        self.active_id = self.latest_id = run.id
        await self.voice.announce(run)
        self.started.set()
        return run


class ResearchWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [
            patch.object(voice_pipeline, "SmallWebRTCTransport", MemoryTransport),
            patch.object(voice_pipeline, "BoundedGradiumSTTService", OfflineGradiumSTT),
            patch.object(voice_pipeline, "BoundedGradiumTTSService", ResearchFixtureTTS),
            patch.object(voice_pipeline, "BoundedGeneralComputeLLMService",
                         side_effect=AssertionError("Research turns must bypass the conversational LLM")),
        ]
        for replacement in self.patches:
            replacement.start()
        self.research = SimulatedRunner()
        self.session = voice_pipeline.VoiceSession(FakeConnection(), read_gradium_config(GRADIUM_ENV), research=self.research)
        self.started = asyncio.Event()
        @self.session.worker.event_handler("on_pipeline_started")
        async def started(worker, frame):
            self.started.set()
        self.task = asyncio.create_task(self.session.run())
        await asyncio.wait_for(self.started.wait(), timeout=3)

    async def asyncTearDown(self):
        await self.session.close()
        await asyncio.wait_for(self.task, timeout=5)
        for replacement in reversed(self.patches):
            replacement.stop()

    async def ready(self):
        await self.session.worker.queue_frame(InputTransportMessageFrame(message={
            "label": "rtvi-ai", "type": "client-ready", "id": "research-ready",
            "data": {"version": "2.1.0", "about": {"library": "research-offline-test"}},
        }))
        await asyncio.wait_for(self.session.transport.output().bot_ready.wait(), timeout=2)
        await wait_until(lambda: "What would you like to investigate?" in self.session.tts.text_seen)

    async def test_gradium_committed_turn_routes_once_and_returns_summary_to_audio(self):
        await self.ready()
        self.assertIs(self.research.voice, self.session.research_bridge)
        await self.session.worker.queue_frame(InputAudioRawFrame(audio=bytes(640), sample_rate=16000, num_channels=1))
        await asyncio.wait_for(self.research.started.wait(), timeout=3)
        self.assertEqual(len(self.research.requests), 1)
        self.assertEqual(self.research.requests[0]["question"], "Hello pipeline")
        await wait_until(lambda: "I'll work out the research steps for your question." in self.session.tts.text_seen)
        output = self.session.transport.output()
        await wait_until(lambda: any(message.get("type") == "server-message" and message.get("data", {}).get("type") == "research.started" for message in output.messages))
        await self.session.worker.queue_frame(LLMContextFrame(self.session.context))
        await self.session.research_bridge.speak("The analysis is ready with cited sources.", self.research.active_id)
        await wait_until(lambda: "The analysis is ready with cited sources." in self.session.tts.text_seen)
        self.assertEqual(len(self.research.requests), 1)
        self.assertTrue(output.audio)
        self.assertTrue(self.session.stt.audio_seen)
        self.assertTrue(self.session.stt.flush_sent)
        await self.session.close()
        self.assertIsNone(self.research.voice)
        self.assertTrue(self.session.connection.closed)
        self.session.tts._http_client.aclose.assert_awaited()

    async def test_live_intent_reaches_browser_while_speaking_before_research_starts(self):
        release_final = asyncio.Event()
        original_handle_text = self.session.stt._handle_text
        original_run_stt = self.session.stt.run_stt
        receiver_tasks = []
        async def while_still_speaking(text):
            await original_handle_text(text)
            await release_final.wait()
        self.session.stt._handle_text = while_still_speaking
        async def receive_transcript(audio):
            async for _ in original_run_stt(audio):
                pass
        async def send_audio_without_blocking_pipeline(audio):
            # Real Gradium receives partial transcripts on a separate websocket
            # task while run_stt only sends audio and promptly returns.
            receiver_tasks.append(asyncio.create_task(receive_transcript(audio)))
            yield None
        self.session.stt.run_stt = send_audio_without_blocking_pipeline
        await self.ready()
        await self.session.worker.queue_frame(InputAudioRawFrame(audio=bytes(640), sample_rate=16000, num_channels=1))
        output = self.session.transport.output()
        try:
            await wait_until(lambda: any(message.get("type") == "server-message"
                and message.get("data", {}).get("type") == "research.intent"
                and message["data"].get("phase") == "ready" for message in output.messages))
            self.assertEqual(self.research.requests, [])
        finally:
            release_final.set()
            await asyncio.gather(*receiver_tasks)
        await asyncio.wait_for(self.research.started.wait(), timeout=3)
        await wait_until(lambda: any(message.get("data", {}).get("type") == "research.started" for message in output.messages))
        events = [message["data"] for message in output.messages if message.get("type") == "server-message"]
        preview_index = next(i for i, event in enumerate(events) if event.get("type") == "research.intent" and event.get("phase") == "ready")
        started_index = next(i for i, event in enumerate(events) if event.get("type") == "research.started")
        self.assertLess(preview_index, started_index)
        self.assertEqual(len(self.research.requests), 1)


if __name__ == "__main__":
    unittest.main()
