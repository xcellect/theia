# Research Orb

Open **http://127.0.0.1:3000/** (or `/research`) to ask a research question by text or voice, inspect Jev's routing decision, watch paper discovery and two specialists, and export a cited Markdown report. Jev chooses whether to search with Exa, read supplied evidence, or request clarification. General Compute runs the Evidence Analyst, Critical Reader, and report writer; Gradium provides speech recognition and synthesis. Prepared Paper2Agent material remains an optional source example.

## Start locally

From `voice-ai-hackathon/practice/`, preserve existing settings in `.env.local` and add the research variables from `.env.example`:

| Setting | Purpose |
| --- | --- |
| `TYPESAFE_API_KEY` | Required for live Jev routing. |
| `TYPESAFE_MODEL=jev-latest` | Jev model; defaults to `jev-latest`. |
| `EXA_API_KEY` | Required for publication search and extraction of public paper URLs. Optional when using only prepared or pasted sources. |
| `GENERALCOMPUTE_API_KEY` and `GENERALCOMPUTE_MODEL` | Required for the specialists and report. Use an exact available model ID. |
| `GENERALCOMPUTE_BASE_URL` | Optional; defaults to `https://api.generalcompute.com/v1`. |
| `GRADIUM_API_KEY` and `GRADIUM_VOICE_ID` | Required for voice. Typed research does not require Gradium. |
| `GRADIUM_REGION=auto` | Optional voice region. |
| `PAPER2AGENT_ROOT` | Optional absolute path to the prepared example checkout. Blank uses sibling `Paper2Agent/`; external search does not depend on this pack. |

Keys stay in the server environment. Existing process variables take precedence over `.env.local`, then `.env`. Restart the Python server after changing settings.

```sh
# Once, if dependencies have not been installed:
npm ci
npm run setup:pipecat

# Terminal 1: Next.js on 127.0.0.1:3000
npm run dev

# Terminal 2, also from practice/: Python on 127.0.0.1:7860
npm run dev:pipecat
```

If these processes are already running, reuse the frontend and restart the Python process to load the research routes. Use the browser's **Start voice** control to request microphone access. End the existing voice session before starting another. The local proxy accepts `localhost`, `127.0.0.1`, and loopback IPv6 hosts; this setup is for local testing.

## Test the workflow

1. Start with **New research**, keep **Search for papers** enabled, and ask: “Find recent papers on evaluating research agents.” No Paper2Agent source selection is required.
2. Watch Jev's acquisition decision, the actual Exa query/results, extraction status, and each specialist's streamed findings. Discovered results and **Sources examined** are distinct; the latter contains only text actually passed to the analysts.
3. Read the report, inspect a few substantive claims against their citations, then copy or download the Markdown.
4. Ask a follow-up within the same tab/session. Its previous question/report provides context while the server remains running; an earlier generated answer is never treated as source evidence.
5. Try a public paper URL, or paste a short code sample/paper excerpt. URLs selected for acquisition are sent to Exa's contents API. Pasted code is read, never executed. To use the bundled example, select Paper2Agent manuscript/implementation and ask what it verifies.
6. Cancel an active run, then submit a replacement. Cancelled findings and speech must not replace the new result.
7. Start voice and repeat the question. The transcript and **Live intent · provisional** panel update while you speak. When the turn ends, the final Jev decision selects the analysis; verify one run starts and listen for the short final summary.
8. Refresh during a run or after its report completes. The page reconnects only to its saved session/run and replays activity without another model call. Open a fresh tab or click **New research** for an empty workspace. While voice is connected, health recovery is restricted to the matching session.

Exa publication search requests five results together with extracted text. URL acquisition uses Exa's fixed API endpoint; the local backend does not directly fetch user URLs. Credentials, IP literals, local hostnames, and non-HTTP(S) URLs are rejected. Provider responses and execution time are bounded. Only actual extracted text is registered: metadata, generated summaries, empty content, and unreadable extraction do not become evidence. Each excerpt is capped at 3,200 characters, with 16,000 characters total. Citations open the exact registered excerpt and original URL. Coverage labels identify recognizable abstract-only content and otherwise state that complete-paper coverage is unverified. Exa's combined search/extraction response arrives as one batch; discoveries appear when it returns, then the analysts and writer stream normally.

The app does not upload/fully convert PDFs, import repositories at a pinned revision, execute code, or reproduce experiments. A publisher URL is not a guarantee that its complete paper can be read. Repository pages extracted by Exa are not a verified code checkout. The analysts use prepared Paper2Agent reading instructions only on that local-source branch; they do not run Paper2Skill/Paper2MCP, build new MCP tools, or independently reproduce paper experiments.

Tab session/run IDs are stored in `sessionStorage`, not durable account history. **New research** resets displayed results, selected/pasted sources, and previous-run context; it is disabled during an active run. The backend is still a local, single-user service with one active research run and shared voice infrastructure. Session IDs guard UI recovery and follow-up context; they are not authentication or multi-user authorization.

Live intent previews call Jev on the accumulating transcript, with at most one preview request in flight and at least 0.5 seconds between starts. Preview values may change as more words arrive; they never start the specialists. A committed turn cancels its preview and obtains the final routing decision. A failed preview does not prevent the completed question from being processed. The final decision separates request type from evidence acquisition: `search`, `provided`, or `clarify`. Missing evidence can trigger search rather than rejecting a question for being outside Paper2Agent. Clarifications and research failures appear in the UI and are spoken when voice is connected.

## Verification

**Exa integration checkpoint — September 19, 2026:** a real Exa adapter probe returned five papers and 16,000 characters of extracted evidence. The real browser then received the synthetic spoken question “Find papers about evaluating retrieval augmented generation.” Jev selected search; Exa produced five discoveries and five registered excerpts; both agents completed, with 28 finding deltas and 17 report deltas. The final report contained 6,198 characters and was not marked partial. The citation drawer exposed a 3,200-character source excerpt; download and refresh recovery passed.

That browser check also confirmed an empty fresh browser, a new session after **New research**, an empty workspace after its reload, no overflow at 390 px, and no browser errors. The microphone input was synthetic; physical capture, audible quality, and headset latency still require user testing. **All 100 Python tests, 70 JavaScript tests, the production build with TypeScript, and HTTP checks pass.** The new backend coverage includes eight adapter tests, seven acquisition/runner tests, two additional bridge tests, and three follow-up-query tests. The browser-bundle secret scan passed across 125 files against eight configured credentials. The backend has been restarted with the follow-up-query fix. Provider key values are not recorded here.

**Earlier prepared-source checkpoint, before Exa/session changes:** live typed research passed through the backend and browser. The initial run routed in 0.44 seconds and completed two agents plus a report in 6.94 seconds (one observation, before the final evidence screen was added). The following historical measurements establish the previous voice/report path, not acceptance of the newly added search path.

That browser test clicked the actual **Start voice** control and used a synthetic microphone with real providers. It observed the transcript and four intent snapshots before the run, 20 specialist deltas, 10 report deltas, both agent panels, and eight source excerpts. Report download and refresh recovery passed with no browser errors. Screenshots at 1440 px and 390 px were visually inspected and had no horizontal overflow. Clipboard output was exactly the same 4,975-character Markdown as the download; the rendered report was unchanged after refresh. With reduced motion enabled, measured animation durations were zero and the orb retained its visible “Ready when you are” label.

A separate live synthetic voice check recognized the known input, received four intent-preview updates with a ready Jev preview before the run, completed both specialists, and produced a 4,705-character report. After report readiness, a 285-character summary produced five non-silent 48 kHz audio frames; cleanup passed. These checks exercise real providers and the browser/pipeline with synthetic input. They do **not** verify a person's physical microphone, speakers, perceived speech quality, or headset latency. At this checkpoint, **70 JavaScript tests, 80 Python tests, the production build including TypeScript checks, and HTTP verification pass**. The secret scan also passed across 123 files against seven configured values; those values are not recorded here.

Reports now receive a second Jev check against the actual excerpts. Draft passages with uncertain support are withheld, and the report is labeled partial; this is a model-based screen, not a guarantee of scientific correctness. Check important claims against the citation drawer. Live streamed text is labeled draft until that check finishes.

After the latest source audit, the prompts were tightened to distinguish reproduction checks from scientific correctness, metadata validation from test execution, and absent excerpt evidence from global claims about the framework. The subsequent live run completed both agents and a 5,980-character report; the screen withheld one of seven passages. The UI correctly labels it partial. The strict `smoke:research` command returned failure because it requires a fully supported, non-partial report, not because the report or streaming pipeline failed.

The latest three-claim manual audit matched the relevant manuscript and workflow-verifier excerpts, but categorical statements about new-dataset verification and scientific correctness still overstated what those excerpts establish. Grounding acceptance remains **partial** while prompts are tightened and the revised report is rechecked.

```sh
# Configuration and local route readiness; these do not prove live research:
npm run check:config -- gradium
curl http://127.0.0.1:3000/api/research/health
curl http://127.0.0.1:3000/api/research/voice/health

# Live General Compute / Gradium provider probe:
npm run smoke:gradium

# One live Jev + two-specialist + report run, with summary-only output:
npm run smoke:research
# Optional alternate local frontend port:
node scripts/research-smoke.mjs --base-url http://127.0.0.1:3001

# One integrated synthetic speech research turn (no microphone/headset):
npm run smoke:research:voice

# Automated checks:
npm test
npm run typecheck
npm run test:pipecat
npm run build
```

A successful real research run verifies Jev routing and model generation. A browser microphone/headset session is required to verify capture, transcription, acknowledgment, and final speech. Record those outcomes separately from automated checks in the [MVP acceptance criteria](../../markdown.md).

If the app reports an unavailable backend, start or restart `npm run dev:pipecat`. Missing settings are listed by variable name. Provider errors retain the question so it can be retried. Runs have a 90-second deadline; retained incomplete output is labeled partial. History and source excerpts are held in memory, capped at five runs and about 15 minutes, and disappear on restart.

## Integration points

The browser uses same-origin `/api/research/...` endpoints. Next.js forwards them only to the local Python process, strips browser credentials, and streams events without buffering. Python owns routing, retrieval, model calls, cancellation, and the event log.

| Browser endpoint | Behavior |
| --- | --- |
| `GET /api/research/health` | Research/search readiness, source packs, provider names, and active/latest run/session identifiers. |
| `POST /api/research/context` | Save `{sourceIds, pastedText?, pastedKind?, searchEnabled?, sessionId?, previousRunId?}` for the next voice turn; returns `{status:"ok"}` without provider calls. |
| `POST /api/research/runs` | Start with `{clientRequestId, question, sourceIds, pastedText?, pastedKind?, previousRunId?, searchEnabled?, sessionId?}`; returns `202 {runId}`. |
| `GET /api/research/runs/:runId/events` | Replay/live SSE; honors `Last-Event-ID`. |
| `POST /api/research/runs/:runId/cancel` | Cancel with a JSON `{}` body. |
| `GET /api/research/runs/:runId/sources/:sourceId` | An excerpt actually read by that run. |
| `GET /api/research/voice/health` | Combined research and Gradium readiness. |
| `POST/PATCH /api/research/voice/offer` | Small WebRTC signaling for research voice. |

The two optional prepared source IDs are `paper2agent-paper` and `paper2agent-code`. External search normally submits `sourceIds: []` and `searchEnabled: true`. Citation IDs such as `S1` are scoped to a run. Reconnecting an event stream replays the existing run; it does not start another model call. The UI stores its own `sessionId`/`runId` in `sessionStorage` and checks matching session identifiers during voice recovery; it no longer loads the global latest run on a fresh visit.

Before a committed run, the voice data channel sends `research.intent` messages with `phase: pending | ready | error`, `turnId`, `transcript`, and `speculative: true`; ready messages include the actual Jev answers, model, and profile. These provisional messages are separate from the run's buffered SSE events. `research.started` announces the committed run/session. SSE carries routing/acquisition, `search.started/result/completed`, `source.fetch.started/completed`, source-read events, specialist deltas/completions, draft report deltas, evidence-check status, and the final report. Draft text may be revised or withheld by the final evidence screen.
