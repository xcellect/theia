# Voice AI Hackathon: AI Agent Setup Checklist

Prepared for Aishik Sanyal. Sources checked **September 18, 2026**. Event: **Saturday, September 19, 2026**, San Francisco. All times below are **America/Los_Angeles (PDT, UTC−7)**.

**Goal:** arrive with working development tools, a tested voice conversation, a successful SambaNova stream, and a rehearsed deployment workflow. At kickoff, adapt to the official starter and build one small, demonstrable use case.

This is an execution checklist for your coding agents. **Execution update — September 18, 2026:** the browser supports Hume EVI and modular Pipecat (Deepgram → SambaNova → Hume TTS). Checked items have observed evidence in [docs/readiness.md](docs/readiness.md). The user reported Hume EVI working; real token issuance succeeded. Automated checks and synthetic local WebRTC audio pass. **Full preparation is not complete:** the user's SambaNova smoke timed out, the new modular route needs credentials and a headset test, and hosted rehearsal remains pending. Unchecked items are blocked, conditional, optional, or event-day work. Proposed paths, time budgets, and performance targets are our implementation plan, not organizer requirements.

## 1. Event facts and unresolved requirements

| Item | Verified information |
| --- | --- |
| Registration | Host approval is required. Check your own approval status. |
| Venue | AGI House SF, 170 St. Germain Ave., San Francisco, CA 94114. |
| Event stack | The event site describes SambaNova inference, Hume voice, and Pipecat orchestration. |
| Starter | The event site says a starter repository will be released at kickoff. Its repository URL is still to be obtained. |
| Tracks | The event site lists action-taking agents and software controlled by voice. |
| Credits | Luma advertises compute credits for contestants; redemption instructions and allowances need confirmation. |

Sources: [Luma listing](https://luma.com/voiceaihackathon?tk=37D2TX), [AGI House event site](https://agihouse.ai/voiceaihackathon/?utm_source=luma). The AGI House text was accessible through [Jina Reader](https://r.jina.ai/https://agihouse.ai/voiceaihackathon/).

**The agendas disagree.** AGI House explicitly labels its schedule a draft. Confirm the final agenda with the hosts; use **6:30 p.m. as our submission-ready target** and **7 p.m. as the conservative deadline** until clarified.

| Milestone | Luma | AGI House draft |
| --- | --- | --- |
| Doors | 10 a.m. | 10 a.m. |
| Kickoff | 11 a.m. | 10:30 a.m. |
| Lunch / main build | Noon | Lunch 12:30 p.m.; sprint 1:30 p.m. |
| Workshops | 2 p.m. | 4 p.m. |
| Submission / evening | Submission 7 p.m.; judging 7:30 p.m. | Sound check 6:30 p.m.; demos 7:30 p.m.; judging 9 p.m. |

Sources: [Luma agenda](https://luma.com/voiceaihackathon), [AGI House draft agenda](https://agihouse.ai/voiceaihackathon/).

- [ ] **H01 — Human:** confirm registration approval, travel, arrival by 10 a.m., laptop, charger, wired headset/microphone, and display adapter.
- [ ] **H02 — Human:** obtain the final agenda, submission link, demo time limit, team-size rules, and judging rubric.
- [ ] **H03 — Human:** confirm which sponsor services are required, whether the official starter is mandatory, and whether AI coding agents are permitted.
- [ ] **H04 — Human:** confirm what may be prepared beforehand: tutorials, reusable boilerplate, UI components, and project-specific code. Record the answer; preserve the provenance of practice code.
- [ ] **H05 — Human:** complete account sign-ins, verification, and credit redemption when needed. Enter credentials through local secret files or the host's secret manager, not the chat transcript.
- [x] **A01 — Coordinator:** record these answers in `docs/event-brief.md`; keep unknowns marked `UNKNOWN`. Prepare host questions for the user; do not contact people on the user's behalf without authorization.

## 2. Give this instruction to your lead agent

```text
Use voice-ai-hackathon-agent-checklist.md as the task specification.
Inspect the existing workspace and its instructions first. Set up the practice
environment, prove the integrations, and leave reproducible run commands.

Work through the required preparation tasks, using separate agents or sessions
for the ownership lanes below when available. Agree on interfaces before
parallel edits. Use separate worktrees/checkouts or non-overlapping files.
One coordinator owns shared manifests, lockfiles, and integration.

Use current official documentation and the installed package's actual APIs.
Preserve existing work. Keep provider secrets on the server. Do not invent
credentials, the event repository URL, model names, credits, or host rules.
Do not start paid resources without an established budget and authorization.

Treat tutorials as practice until reuse rules are known. Choose one integrated
voice route; do not turn every optional experiment into required work.
When blocked, record the exact blocker and continue independent tasks.
Ask for human help only for genuinely required credentials or decisions.

Check off a task only after its acceptance condition is observed. Record
PASS, FAIL, BLOCKED, or NOT RUN, with commands, results, and evidence in
docs/readiness.md. Distinguish automated checks from actual microphone tests.
Finish with what works, how to run it, remaining blockers, and the next action.
```

### Ownership and order

These are work lanes; one agent may execute them sequentially.

| Lane | Owns | Depends on |
| --- | --- | --- |
| A — Coordinator / environment | Rules, runtime, shared dependencies, configuration contract, integration | Human answers as they become available |
| B — Voice / interface | Hume practice app, microphone lifecycle, transcript, Pipecat voice adapters | A's scaffold and agreed dependencies |
| C — Inference / tools | SambaNova smoke test, streaming, one reversible action, optional EVI bridge | A's configuration contract |
| D — Deployment / QA | Hosting workflow, failure checks, measurements, demo and runbook | Can prepare checks early; needs working B + C for live verification |

Run **A first**, then **B and C independently**. Integrate one route, then let D verify it. Delegate a narrow task with the allowed paths, expected interface, and acceptance condition from this file.

## 3. Preparation budget and architecture decision

Budget **6–8 hours total**, allowing independent lanes to overlap. If time is short, prioritize working audio, a real SambaNova request, credentials, and a reliable runbook.

| Priority | Work | Suggested time box |
| --- | --- | --- |
| Required | Rules, accounts, local tools, environment contract | 45–60 minutes |
| Required | Hume browser voice practice | 60–90 minutes |
| Required | SambaNova non-streaming and streaming requests | 30–45 minutes |
| Required | Pipecat runtime readiness and starter migration notes | 30–45 minutes |
| Choose one | A working combined stack, if credentials are available | 60–90 minutes |
| Required | Run/deploy rehearsal, live audio checks, short demo | 60–90 minutes |
| Optional | Additional integration experiments or visual polish | Remaining time only |

| Route | When to use | Components |
| --- | --- | --- |
| **Event-first: Pipecat** | Prefer at kickoff if the official starter matches the advertised stack | Browser transport, speech recognition, SambaNova LLM, Hume TTS, Pipecat pipeline |
| **Alternative: EVI + custom backend** | Useful if the EVI practice app works well and hosts accept this architecture | Browser Hume SDK, EVI, your streaming backend, SambaNova LLM |
| **Fallback demo** | When an integration fails | Working voice route or clearly labeled recording; document missing sponsor integration and confirm eligibility |

The first two routes are separate implementations. **Hume EVI handles a voice conversation; Hume TTS in a Pipecat pipeline generates speech and does not supply speech recognition by itself.** Verify the starter's actual input/audio services before adding providers. See [Hume EVI quickstart](https://dev.hume.ai/docs/speech-to-speech-evi/quickstart/nextjs) and [Pipecat Hume TTS integration](https://docs.pipecat.ai/api-reference/server/services/tts/hume).

## 4. A — Workspace, runtime, and secrets

- [x] **A02:** inspect the existing repository, `AGENTS.md`, package manifests, and uncommitted work. Choose a separate practice directory if there is no existing project; do not overwrite files to scaffold.
- [x] **A03:** confirm Git, a Node.js version compatible with the chosen Next.js starter, one JS package manager, Python compatible with the Pipecat starter, and `uv` work locally. Pipecat's current quickstart requires Python 3.11 or later; also honor the actual project's version bounds. [Pipecat quickstart](https://docs.pipecat.ai/pipecat/get-started/quickstart)
- [x] **A04:** install dependencies once per workspace and retain lockfiles. Record runtime and dependency versions in `docs/readiness.md`; assign all dependency changes to lane A.
- [x] **A05:** create `.env.example` with placeholders and document which variables each route requires. Exclude real `.env` / `.env.local` files from Git, while keeping the example trackable.
- [x] **A06:** implement explicit environment loading for app servers and standalone scripts. A script must not silently assume the web framework has loaded its environment.
- [x] **A07:** add a configuration check that reports missing variable **names**, never their values. Validate only variables needed by the selected route.
- [ ] **A08:** check that Hume, SambaNova, package registries, and the intended host are reachable from the development machine. Record blocked domains; continue work that does not need those services.
- [x] **A09:** keep Hume and SambaNova provider keys out of browser bundles, `NEXT_PUBLIC_*` variables, committed fixtures, screenshots, and logs. Temporary browser access tokens are distinct from long-lived provider credentials.
- [x] **A10:** create `README.md`, `docs/readiness.md`, and `docs/event-brief.md`. Each must distinguish practice configuration from the event-day configuration.

Suggested environment contract — **these application variable names must be wired into code; they are not automatically read by every SDK**:

```dotenv
# Common server-side credentials
HUME_API_KEY=
SAMBANOVA_API_KEY=

# Public-cloud practice default; replace with the assigned event endpoint.
SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1
SAMBANOVA_MODEL=

# EVI route only
HUME_SECRET_KEY=
HUME_CONFIG_ID=

# Pipecat/Hume TTS route only
HUME_VOICE_ID=
# Local modular practice uses Deepgram STT and Small WebRTC (no transport key).
DEEPGRAM_API_KEY=
DEEPGRAM_MODEL=nova-3-general
# Recheck the actual event starter's service variables at kickoff.

# Optional EVI-to-SambaNova bridge only
CLM_ENDPOINT_URL=
CLM_AUTH_SECRET=
```

The public SambaCloud base URL is documented above; event/SambaStack endpoints can differ. Get the assigned endpoint and exact model ID from the sponsor. [SambaNova keys and URLs](https://docs.sambanova.ai/docs/en/get-started/api-keys-urls)

**Acceptance:** a fresh terminal can install/start the practice project using the README; a missing key produces a useful error without revealing secrets.

## 5. C — SambaNova setup and streaming proof

Use the [SambaNova quickstart](https://docs.sambanova.ai/docs/en/get-started/quickstart) and [OpenAI client compatibility guide](https://docs.sambanova.ai/docs/en/features/openai-compatibility). An OpenAI-compatible client pointed at SambaNova uses a **SambaNova key**, not an OpenAI key.

- [ ] **C01:** have the user establish account access or provide the assigned event credentials; verify available credit/quota without starting an unapproved paid plan.
- [ ] **C02:** choose a model actually available to that account/endpoint. Store its exact ID in `SAMBANOVA_MODEL`; do not derive an API ID from a marketing or benchmark name.
- [ ] **C03:** implement a small server-side smoke script, using the native SambaNova SDK or a compatible client with the configured base URL. Make one non-streaming request and confirm nonempty output.
- [ ] **C04:** add a streaming request and show text arriving incrementally. Handle empty/control chunks and stream termination; do not concatenate everything before displaying it.
- [ ] **C05:** record time to first **nonempty text** chunk separately from total completion time. Preserve the endpoint, model ID, and sanitized result in `docs/readiness.md`.
- [x] **C06:** add timeout/cancellation and readable handling for invalid credentials, unavailable models, quota limits, and transport failures. Avoid unbounded retries.
- [ ] **C07:** if the chosen demo needs tool calls, verify one call with that exact model and endpoint. Validate arguments server-side and return a structured result. Use a harmless local task-board action for the smoke test.
- [x] **C08:** create a deterministic fake provider for UI/failure testing; keep a separate real-provider smoke command and mark fake responses visibly as demo data.

**Acceptance:** both request modes work against the intended provider; streaming begins before completion; configuration can change without code edits. The action branch is only ready when the selected model completes an actual tool round trip.

## 6. B — Hume browser voice practice

Start from [Hume's Next.js guide](https://dev.hume.ai/docs/speech-to-speech-evi/quickstart/nextjs) and its [official example](https://github.com/HumeAI/hume-api-examples/tree/main/evi/evi-next-js-app-router-quickstart). Read the actual source and installed SDK types when a snippet behaves unexpectedly.

- [x] **B01:** use the existing Next.js app or a separate practice app. Install `@humeai/voice-react` and `hume` with the chosen package manager; retain the lockfile.
- [x] **B02:** obtain the Hume API and secret keys via the user's account. Generate a temporary EVI access token on the server and pass only that token to the browser. [Hume authentication](https://dev.hume.ai/docs/introduction/api-key)
- [ ] **B03:** connect from an explicit Start button so microphone capture and playback begin after a user gesture; provide End, connection status, and useful error feedback.
- [ ] **B04:** wire the SDK's voice provider and connection lifecycle. Show actual `user_message` and `assistant_message` text in the transcript; verify the filter includes these events.
- [ ] **B05:** support mute/unmute where the chosen SDK exposes it. On End, release audio resources and stop provider activity; repeat Start/End without duplicate sessions.
- [ ] **B06:** use an explicit EVI configuration for repeatable prompts/voice. Record its ID/version where available and confirm it is the configuration used by the active connection.
- [ ] **B07:** obtain a fresh token for a new/reconnected session when required; prevent token responses from being cached as public content. [Hume authentication](https://dev.hume.ai/docs/introduction/api-key)
- [ ] **B08:** have a person perform a three-turn conversation on the actual laptop/headset. Confirm intelligible output, transcript visibility, and handling of an interrupted response.

**Acceptance:** the user can click Start, speak, hear a response, read both speakers' transcript, interrupt, and End. Browser-only mocks do not satisfy the microphone/audio check.

## 7. B + C — Pipecat readiness and the official starter

Use [Pipecat's quickstart](https://docs.pipecat.ai/pipecat/get-started/quickstart), [SambaNova service](https://docs.pipecat.ai/api-reference/server/services/llm/sambanova), and [Hume TTS service](https://docs.pipecat.ai/api-reference/server/services/tts/hume).

- [x] **P01 — Beforehand:** prepare Python/`uv` and learn the transport, speech recognition, language model, speech synthesis, and turn-detection responsibilities. Keep the official starter URL as `TBD — obtain at kickoff`.
- [ ] **P02 — Optional practice:** scaffold the generic quickstart in a separate directory. Its default providers are Deepgram, OpenAI, and Cartesia; this is not the event starter. Do not create extra paid accounts just to preserve these defaults.
- [x] **P03 — If running Pipecat now:** replace the model/output services with `SambaNovaLLMService` and `HumeTTSService`, using APIs supported by the installed version. Install the matching `sambanova` and `hume` extras; preserve the starter's version constraints.
- [x] **P04:** explicitly choose speech recognition and browser transport. Use an already available provider, the event's supplied service, or mark the live pipeline blocked pending access. Hume TTS alone cannot transcribe incoming speech.
- [ ] **P05:** verify the Hume voice ID, output audio format, and transport compatibility. Keep listening, turn detection, streaming generation, speech playback, and interruption handling in the chosen framework.
- [ ] **P06 — At kickoff:** clone the organizer-provided repository from the host's actual link. Read its instructions, inspect its credentials and dependency pins, and run it unchanged before porting features.
- [ ] **P07 — At kickoff:** inventory the actual STT, LLM, TTS, transport, endpoints, and model IDs. Replace practice assumptions with supplied settings; record evidence that inference reaches the assigned SambaNova endpoint.
- [ ] **P08:** complete one three-turn conversation through this pipeline. Confirm transcript events reach the UI and interruption stops queued speech.
- [ ] **P09:** port only the small agreed demo feature after the baseline works. Run the voice check again after integration.

Generic practice commands, **only in a new practice workspace** and after checking the current guide:

```bash
uv tool install "pipecat-ai[cli]"
pipecat init quickstart
cd pipecat-quickstart
# Configure a local environment file and select available services first.
uv sync
uv run bot.py
```

**Acceptance:** before the event, tools are installed and outstanding service access is named. At kickoff, the unchanged official starter must work before it counts as an integrated baseline. A generated scaffold alone is not a voice test.

## 8. Optional C — Hume EVI → SambaNova bridge

**Time box: 45–60 minutes for the first working stream.** Use this route if it is the selected architecture, or as a bounded practice experiment. If it remains blocked, preserve the independent smoke tests and move to the event starter.

Hume supports a public HTTPS custom-model endpoint ending in `/chat/completions`, returning compatible server-sent events (SSE). Its examples describe message conversion and termination. [Hume custom language model guide](https://dev.hume.ai/docs/speech-to-speech-evi/guides/custom-language-model)

- [ ] **I01:** implement the endpoint in the existing backend. Extract the supported conversation fields from Hume's request and call SambaNova with streaming enabled.
- [ ] **I02:** emit `Content-Type: text/event-stream`, compatible completion chunks, and the terminating `data: [DONE]` event. Flush incrementally and handle failure/disconnection.
- [ ] **I03:** use a deployed endpoint or supported development tunnel that Hume can reach. Test reachability externally; `localhost` on the developer machine is insufficient.
- [ ] **I04:** configure EVI to use this endpoint and verify which model/configuration the live session actually reaches.
- [ ] **I05:** authenticate the bridge. Set its credential through Hume's trusted server-side control plane after obtaining and validating the active chat ID; do not embed `CLM_AUTH_SECRET` or the SambaNova key in browser code. Gate the first turn until configuration succeeds. [Hume control plane](https://dev.hume.ai/docs/speech-to-speech-evi/guides/control-plane)
- [ ] **I06:** validate the bridge using an HTTP streaming client, then a live voice session. Confirm output is heard before full generation completes, and record the provider call without logging its credentials.

**Acceptance:** one spoken turn demonstrably traverses EVI, the authenticated bridge, and SambaNova, then returns audible speech. Report this as an alternative architecture unless the hosts confirm it satisfies event requirements.

## 9. A + C — Pick one useful, demoable interaction

Do the following as planning before the event; implement project-specific features only within the organizers' rules.

- [x] **M01:** write one sentence: “For [user], this voice agent helps [task] by [observable action/result].” Pick one person, one scenario, and one finish line.
- [x] **M02:** choose a track and scope. A low-dependency default is a **voice-controlled task board**: create, rename, and complete a task while the audience sees the state change.
- [ ] **M03:** if choosing the previously suggested conversation-practice app, keep one role-play and transcript-grounded feedback; confirm track fit with the hosts. Every quoted example in feedback must exist in the transcript.
- [x] **M04:** define a 60–90 second demonstration with three user utterances, one interruption/correction, and a visible outcome.
- [x] **M05:** give the model a short spoken-response prompt: concise replies, one question at a time, no spoken Markdown, and confirmation based on actual tool results.
- [ ] **M06:** implement the demo action against local or sandbox data. Validate arguments and prevent duplicated actions when requests repeat; require confirmation before any later real external action with consequences.
- [ ] **M07:** show action status and resulting app state. A model saying “done” does not prove a tool ran.
- [x] **M08:** write the cut list: no multiple personas, account system, billing, vector database, telephony, or multiple deployment targets unless one is essential to the chosen scenario.

**Acceptance:** a first-time viewer can see what speaking accomplished, and the entire interaction fits the demo limit.

## 10. D — Deployment and reproducibility

- [ ] **D01:** use an existing authorized host or the starter's supported deployment path. Confirm which components require a persistent Python process, WebRTC/WebSocket support, or HTTP streaming. Do not assume a static frontend host runs the voice backend.
- [x] **D02:** create one copyable run command per component and a documented install command from its lockfile. Add a small readiness/health check that exposes no credentials.
- [x] **D03:** document the exact environment variables, ports, public URLs, and start/stop steps. Include how the browser finds its backend and how Hume reaches the bridge, if applicable.
- [ ] **D04:** rehearse deployment of the practice app using configured secrets. Check microphone permissions, audio output, frontend/backend routing, and streaming from the hosted URL.
- [ ] **D05:** verify WebRTC connectivity when relevant; use the chosen transport's supported relay/network setup if the venue network blocks the connection. Keep a known-working local demo path.
- [x] **D06:** check a clean install/build/start after integration. Run only the relevant existing checks and targeted tests for configuration, stream parsing, and action validation.
- [x] **D07:** tag or otherwise record the known-working commit. Document rollback and reset of demo data; save the exact commands.
- [x] **D08:** cache/install required dependencies and model assets before arrival where permitted. Record whether the demo still requires external APIs; local hosting does not imply offline operation.

**Acceptance:** the demo runs from the documented commands and the intended URL on the presentation laptop, without relying on an unexplained background process.

## 11. D — Voice and failure checks

Run this matrix on the **selected final route**. Automated fixtures can cover failure handling; a person must verify real microphone input and audible playback. Store results in `docs/readiness.md`.

| Done | Check | Passing observation |
| --- | --- | --- |
| [ ] | Normal conversation | Three turns complete with readable transcript and intelligible speech. |
| [ ] | Turn detection | A short pause within a sentence does not repeatedly trigger premature responses. |
| [ ] | Interruption | Speaking over the assistant stops stale playback and leads to a coherent next turn. |
| [ ] | Self-correction | “Make it Tuesday—sorry, Wednesday” uses the final intended value. |
| [ ] | Silence | The app stays stable; any reprompt is bounded and does not loop. |
| [ ] | Background noise | The headset works in a noisy-room trial; obvious false turns are recorded and addressed. |
| [ ] | Microphone denied / missing | The UI gives an actionable recovery path instead of hanging. |
| [ ] | Start → End → Start | Audio resources and sessions are cleaned up; no double voices. |
| [ ] | Expired / invalid auth | A controlled error appears; reconnect uses the correct token path. |
| [ ] | Quota / timeout / lost connection | The UI leaves the loading state and offers a bounded retry/reconnect. |
| [ ] | Tool failure / repeated request | Failed actions are reported truthfully; a retry does not duplicate a completed action. |
| [ ] | Transcript correctness | User and assistant messages are shown once and in order; partials do not create fake completed turns. |
| [ ] | Secret handling | Browser requests, bundles, repository diff, and shared logs contain no long-lived provider keys. |
| [ ] | Hosted rehearsal | The complete interaction works from the intended demo URL and audio device. |

### Measure perceived delay

- [ ] **Q01:** record ten ordinary turns with model, network, and route noted. Define end-to-end delay as **end of user speech to start of audible assistant playback**; use client instrumentation or a recording with aligned timestamps.
- [ ] **Q02:** record LLM first-text latency separately. If only transcript-arrival timestamps are available, label the measurement as a proxy, not true speech-to-speech latency.
- [ ] **Q03:** report the median and slowest observed turn plus the sample count. Use **under two seconds median** as an initial project target, not a sponsor promise or judging rule.
- [ ] **Q04:** if delay is disruptive, inspect turn detection, speech recognition, first-token delay, speech synthesis, buffering, and cold starts. Change the largest contributor first; retest the affected path.

**Acceptance:** every required check is PASS or has a named blocker and demo mitigation. A successful build does not substitute for live voice validation.

## 12. Event-day runbook

These are our working milestones. Confirm the event's final schedule at registration and adjust the early targets if needed.

- [ ] **10–10:30 a.m.:** check in, verify the final deadline/rules, test venue audio/network, and find the sponsor support contacts.
- [ ] **At kickoff:** obtain the official repository, credit redemption steps, exact endpoints/models, and credentials; run the unmodified starter.
- [ ] **By noon:** select one use case, assign file ownership, and commit a working baseline or identify the exact sponsor-access blocker.
- [ ] **By 2 p.m.:** complete one spoken request that produces the intended visible result; take integration blockers to the relevant workshop/engineer.
- [ ] **By 4 p.m.:** finish the core interaction. Cut remaining optional features.
- [ ] **By 5:30 p.m.:** freeze features, verify failure paths, deploy, reset demo data, and rehearse twice.
- [ ] **By 6 p.m.:** record a backup demo with audible input/output and readable text. Keep it locally available and label recorded/fallback material honestly.
- [ ] **By 6:30 p.m.:** make the submission ready: project name, pitch, team, repository, demo link/video, sponsor integration explanation, and any required disclosures.
- [ ] **Before the confirmed deadline:** submit through the actual organizer link and retain confirmation. Do not wait for the live-demo slot to submit.
- [ ] **Before presenting:** open the correct tab, select the tested audio device, warm up the app, reset data, and keep the backup one click away.

### Demo script template

1. **0–15 seconds:** state the user and problem.
2. **15–60 seconds:** perform the interaction; include a correction or interruption and show the result.
3. **60–75 seconds:** explain the actual roles of SambaNova, Hume, and Pipecat/EVI in the working system.
4. **75–90 seconds:** state what was built, one observed reliability/latency result, and the next useful improvement.

Shorten this to the host's actual time limit. Demonstrate measured behavior; do not substitute advertised model throughput for measured conversation delay.

## 13. Final agent handoff

- [x] **F01:** `README.md` contains exact install, configure, run, verify, and stop commands.
- [x] **F02:** `.env.example` lists required variables for the chosen route with no real secrets.
- [x] **F03:** lockfiles and runtime requirements reproduce the tested environment.
- [x] **F04:** `docs/event-brief.md` contains sourced facts, host clarifications, the final deadline, and unresolved questions.
- [ ] **F05:** `docs/readiness.md` contains test evidence, the real provider/model/route used, and human audio observations.
- [x] **F06:** `docs/demo.md` contains the pitch, demo steps, reset instructions, and backup location.
- [x] **F07:** known failures have an owner, a next action, and a realistic fallback. Clearly identify any mocked or untested component.
- [x] **F08:** the lead agent reports “ready” only for the tasks verified; event-only tasks remain pending until performed.

Use this entry format for each meaningful verification:

```markdown
### Task ID — short name
- Status: PASS / FAIL / BLOCKED / NOT RUN
- Owner:
- Route / commit / runtime:
- Command or manual action:
- Expected outcome:
- Observed outcome and sanitized evidence:
- Remaining blocker and next action:
```

**Preparation is complete when:** a live Hume conversation and a real SambaNova stream work, Pipecat prerequisites and missing credentials are understood, one deployment/run path has been rehearsed, and the user has a short demo plan. **Event readiness additionally requires** the assigned starter/endpoints, required sponsor integrations, confirmed submission rules, and a successful final-route voice test.
