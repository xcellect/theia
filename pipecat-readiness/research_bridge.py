"""Keep committed research turns independent of the real-time audio pipeline."""

import asyncio
import re
import time
from contextlib import suppress
from uuid import uuid4

from pipecat.frames.frames import (
    InterimTranscriptionFrame, LLMContextFrame, ProposedUserStartedSpeakingFrame,
    TranscriptionFrame, TTSSpeakFrame, UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

PREVIEW_INTERVAL_SECONDS = 0.5
PREVIEW_TIMEOUT_SECONDS = 4


class ResearchTranscriptObserver(FrameProcessor):
    """Observe STT text without delaying audio or starting a research run."""

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        bridge.observer = self
        self.clear()

    def clear(self):
        self.committed = ""
        self.interim = ""
        self.seen = set()

    @staticmethod
    def _join(committed, current):
        # Gradium interim strings are cumulative; other STT services emit segments.
        if not committed or current == committed or current.startswith(committed + " "):
            return current
        return " ".join(part for part in (committed, current) if part)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, (ProposedUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
                if self.committed or self.interim:
                    self.bridge.reset_preview()
            elif isinstance(frame, InterimTranscriptionFrame):
                self.interim = frame.text.strip()
                self.bridge.preview(self._join(self.committed, self.interim), False)
            elif isinstance(frame, TranscriptionFrame):
                key = (frame.timestamp, frame.text)
                if key not in self.seen:
                    self.seen.add(key)
                    self.committed = self._join(self.committed, frame.text.strip())[:4000]
                    self.interim = ""
                    self.bridge.preview(self.committed, True)
        await self.push_frame(frame, direction)


class ResearchTurnProcessor(FrameProcessor):
    """Consume inference frames; only the aggregator's committed event starts work."""

    def __init__(self, runner):
        super().__init__()
        self.research = runner
        self.worker = None
        self.rtvi = None
        self.connected = False
        self.session_id = uuid4().hex
        self.research_session_id = self.session_id
        self.turns = set()
        self.submissions = set()
        self.previous_run_id = None
        self.observer = None
        self.preview_task = None
        self.preview_tasks = set()
        self.preview_lock = asyncio.Lock()
        self.preview_generation = 0
        self.preview_turn_id = uuid4().hex
        self.preview_revision = 0
        self.preview_text = ""
        self.preview_final = False
        self.preview_last_call = 0.0

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)

    async def ready(self):
        self.connected = True
        self.research.voice = self
        await self.speak("What would you like to investigate?", None)

    def reset_preview(self):
        """Invalidate a speculative turn synchronously before committed dispatch."""
        self.preview_generation += 1
        self.preview_turn_id = uuid4().hex
        self.preview_revision = 0
        self.preview_text = ""
        self.preview_final = False
        if self.preview_task is not None:
            self.preview_task.cancel()
            self.preview_task = None
        if self.observer is not None:
            self.observer.clear()

    def preview(self, text, final=False):
        if not self.connected or not isinstance(text, str):
            return
        text = " ".join(text.split())[:4000]
        if not text or (text == self.preview_text and final == self.preview_final):
            return
        self.preview_text, self.preview_final = text, final
        self.preview_revision += 1
        if len(text) < 6 or self.preview_task is not None:
            return
        task = asyncio.create_task(self._preview_loop(self.preview_generation, self.preview_turn_id))
        self.preview_task = task
        self.preview_tasks.add(task)
        task.add_done_callback(self.preview_tasks.discard)

    def _context(self):
        context = dict(getattr(self.research, "voice_context", None) or {})
        session_id = context.get("sessionId") or self.session_id
        if session_id != self.research_session_id:
            self.research_session_id = session_id
            self.previous_run_id = None
        previous_id = context.get("previousRunId") or self.previous_run_id
        prior = self.research.runs.get(previous_id)
        if prior and getattr(prior, "session_id", None) != session_id:
            prior, previous_id = None, None
        context.update({"sessionId": session_id, "previousRunId": previous_id,
                        "sourceIds": context.get("sourceIds", getattr(prior, "source_ids", [])),
                        "searchEnabled": context.get("searchEnabled", True)})
        return context, prior

    def _preview_run(self, text, turn_id):
        from research import ResearchRun

        context, prior = self._context()
        source_ids = context["sourceIds"]
        pasted_text, pasted_kind = getattr(prior, "pasted_text", ""), getattr(prior, "pasted_kind", "paper")
        if context is not None:
            source_ids = context.get("sourceIds", source_ids)
            pasted_text = context.get("pastedText", "")
            pasted_kind = context.get("pastedKind", "paper")
        previous = (f"Previous question: {getattr(prior, 'question', '')}\n"
                    f"Previous answer: {getattr(prior, 'markdown', '')[:3500]}") if prior else ""
        question = re.sub(r"\bpaper\s+(?:to|two|2)\s+agent\b", "Paper2Agent", text, flags=re.I)
        return ResearchRun(f"preview-{turn_id}", question, list(source_ids), pasted_text, pasted_kind, previous,
                           search_enabled=context["searchEnabled"], session_id=context["sessionId"],
                           paper2agent_enabled=context.get("paper2agentEnabled", False), paper_ids=context.get("paperIds", []))

    async def _preview_loop(self, generation, turn_id):
        def current():
            return self.connected and generation == self.preview_generation

        try:
            while current():
                await asyncio.sleep(max(0, self.preview_last_call + PREVIEW_INTERVAL_SECONDS - time.monotonic()))
                if not current():
                    return
                text, final, revision = self.preview_text, self.preview_final, self.preview_revision
                common = {"type": "research.intent", "transcript": text, "turnId": turn_id,
                          "speculative": True, "final": final}
                # A lock also covers a just-cancelled previous turn while its HTTP
                # request unwinds, so there is never overlapping preview work.
                async with self.preview_lock:
                    if not current():
                        return
                    self.preview_last_call = time.monotonic()
                    await self.rtvi.send_server_message({**common, "phase": "pending"})
                    try:
                        async with asyncio.timeout(PREVIEW_TIMEOUT_SECONDS):
                            answers, model = await self.research._routing(self._preview_run(text, turn_id))
                        if current():
                            profile = "code" if answers["needs_code"]["noul"] >= 0.65 else "paper"
                            await self.rtvi.send_server_message({**common, "phase": "ready", "answers": answers,
                                                                 "model": model, "profile": profile})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if current():
                            await self.rtvi.send_server_message({**common, "phase": "error",
                                "message": "Live intent preview is unavailable. Your completed question will still be processed."})
                if revision == self.preview_revision:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # A disconnected RTVI channel must not leak a background exception
            # into the audio pipeline or expose provider details.
            return
        finally:
            if self.preview_task is asyncio.current_task():
                self.preview_task = None

    def submit(self, content, timestamp):
        if not self.connected or not content or not content.strip():
            return
        # Timestamp identifies the committed turn, not a partial STT fragment.
        key = timestamp or uuid4().hex
        if key in self.turns:
            return
        self.turns.add(key)
        self.reset_preview()
        task = asyncio.create_task(self._submit(content.strip(), key))
        self.submissions.add(task)
        task.add_done_callback(self.submissions.discard)

    async def _submit(self, question, key):
        try:
            # Normalize the prepared project's spoken name, preserving other text.
            question = re.sub(r"\bpaper\s+(?:to|two|2)\s+agent\b", "Paper2Agent", question, flags=re.I)
            context, _ = self._context()
            run = await self.research.start({
                "clientRequestId": f"voice-{self.session_id}-{key}",
                "question": question,
                **context,
            })
            self.previous_run_id = run.id
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.connected:
                await self.rtvi.send_server_message({
                    "type": "research.error",
                    "message": "Research could not start. Check the research setup and try again.",
                })
                await self.speak("Research could not start. Please check the message on screen and try again.")

    def accepts_run(self, run):
        context, _ = self._context()
        return getattr(run, "session_id", None) == context["sessionId"]

    async def announce(self, run):
        if self.connected and self.accepts_run(run):
            await self.rtvi.send_server_message({
                "type": "research.started", "runId": run.id, "question": run.question,
                "sessionId": getattr(run, "session_id", None),
            })
            await self.speak("I'll work out the research steps for your question.", run.id)

    async def speak(self, text, run_id=None):
        if not self.connected or (run_id and self.research.active_id != run_id):
            return
        run = self.research.runs.get(run_id) if run_id else None
        if run and not self.accepts_run(run):
            return
        await self.worker.queue_frame(TTSSpeakFrame(text=text[:900], append_to_context=False))

    async def interrupt(self):
        if self.connected:
            await self.rtvi.interrupt_bot()

    async def close(self):
        self.connected = False
        self.reset_preview()
        if self.research.voice is self:
            self.research.voice = None
        for task in list(self.preview_tasks):
            task.cancel()
        for task in list(self.preview_tasks):
            with suppress(asyncio.CancelledError, Exception):
                await task
        self.preview_tasks.clear()
        for task in list(self.submissions):
            task.cancel()
        for task in list(self.submissions):
            with suppress(asyncio.CancelledError, Exception):
                await task
        self.submissions.clear()
