# Practice demo plan and event-day runbook

**State: PLAN, not a completed voice-controlled product.** The current preparation has a Hume EVI practice UI and separate SambaNova smoke commands. The final task-board feature, combined sponsor pipeline, microphone rehearsal, and hosted demonstration require the evidence listed in [readiness.md](readiness.md). Pre-event reuse permission is UNKNOWN; see [event-brief.md](event-brief.md).

## Proposed 60–90 second demo

**Pitch:** For a presenter preparing a demo, this voice agent helps organize rehearsal work by creating, renaming, and completing a task while the audience sees each change.

**Proposed track:** software controlled by voice, subject to host confirmation. One person, one local task board, one completed task. Conversation coaching is not selected.

| Time | Presenter / utterance | Required visible proof |
| --- | --- | --- |
| 0–15 s | “I can organize a rehearsal while keeping my hands free. Watch the board as I speak.” | Empty board and connection status. |
| 15–30 s | “Create a task called Prepare Tuesday demo.” | One task appears only after a successful action result. |
| 30–45 s | Interrupt the assistant: “Rename it Prepare Wednesday demo—sorry, Rehearse Wednesday demo.” | Stale playback stops; the same task has the final corrected title. |
| 45–60 s | “Mark that task complete.” | Exactly one task is complete; action status confirms the actual result. |
| 60–75 s | Explain the components actually observed in the working route. | Pipecat: STT → SambaNova → Hume TTS, plus transport/orchestration, only if proven. An EVI-only practice session must be described as EVI. |
| 75–90 s | State one measured result, its sample count, and a useful next improvement. | Use real evidence; if none exists, say latency has not been measured. |

Adjust to the host's actual limit: **UNKNOWN**. The three utterances and correction above are a rehearsal specification. The practice UI does not implement this board interaction, and a generic sandbox tool fixture is not proof that voice controls it.

**Proposed spoken-response prompt (not yet applied to an event configuration):**

> You help manage this local rehearsal task board. Reply in one short spoken sentence, ask one question at a time, and avoid Markdown. Use the validated tools for changes. Confirm success only after a successful tool result. If a tool fails, explain that nothing was confirmed and offer one next step. Resolve corrections to the user's final intent. Never pretend a task changed because you described the change.

The eventual action layer must validate names/IDs server-side, keep stable task IDs, and deduplicate retries using an operation identifier. Require confirmation before adding any consequential external action. Show pending/succeeded/failed state and the resulting board separately from model speech.

**Cut list:** no multiple personas, user accounts, billing, vector database, telephony, multiple deployment targets, real calendar/email/order integrations, or extra models/providers. Keep tutorial learning code separate until reuse rules are answered.

## Current practice commands

From the repository root, use the exact environment and runtime requirements in [README.md](../README.md). Enter provider secrets only in `practice/.env.local` or an authorized host's secret manager. The browser reaches the token route on the same Next.js origin; that server exchanges long-lived Hume credentials for a temporary browser token. There is no selected custom-model bridge endpoint.

```sh
cd practice
npm ci
npm run check:config -- evi
npm run dev
```

Open `http://127.0.0.1:3000` on the presentation laptop. The EVI check requires `HUME_API_KEY`, `HUME_SECRET_KEY`, and `HUME_CONFIG_ID`. Use an explicit Hume configuration and record its ID/version in readiness evidence without recording credentials. For a production-mode local rehearsal, stop the development server first:

```sh
npm run build
npm run start
```

In a second terminal, from `practice/`:

```sh
npm run check:config -- sambanova
npm run smoke:sambanova
# Optional real tool-call round trip with the chosen model:
npm run smoke:sambanova -- --tools
```

These require `SAMBANOVA_API_KEY` and an actually available `SAMBANOVA_MODEL`. `SAMBANOVA_BASE_URL` uses the documented public-cloud default when unset; replace it with the assigned event endpoint when supplied. Do not infer a model ID from event marketing. Confirm credit/quota before live calls. Stop each server with **Ctrl+C in the terminal that started it**; click **End session** in the UI first to terminate its active voice session. Smoke commands exit on completion or failure.

The deterministic fake command is a separate test fixture:

```sh
npm run smoke:fake
# Generic action validation, still entirely fake:
npm run smoke:fake -- --tools
```

Treat its output as **DEMO DATA**. It does not contact SambaNova, exercise a microphone, or prove Hume audio playback. Each `--tools` run creates a fresh in-memory board with one task, `practice-task`, and changes its status from `todo` to `done`. Process exit discards the board; rerun the command to reset. Repeated operation IDs are deduplicated. This fixture is not connected to an event board. Real `smoke:sambanova -- --tools` makes four model requests (nonstreaming, streaming, tool request, and tool-result follow-up), so account for those in the authorized quota.

**Practice reset:** click **End session**, wait for **Ready when you are**, verify the microphone indicator stops, then click **Clear**. Begin again with **Prepare session → Start voice**; verify only one assistant voice is heard. No final task-board reset command exists yet. At kickoff, add one only for the local/sandbox data store and record the exact command here after observing its effect.

**Known working version / rollback:** use the recorded commit or source snapshot and exact restore instructions in [readiness.md](readiness.md). Until a known working version is recorded, rollback rehearsal is NOT RUN. Preserve practice changes and create a separate checkout for rollback; do not reset an active dirty workspace.

## Human laptop/headset rehearsal

Owner: **Aishik**. Status for every manual check below: **NOT RUN** until observed; missing live credentials make the corresponding provider checks **BLOCKED**. Automated tests and rendered pages cannot mark these PASS.

1. Select the actual presentation headset for both input and output in the operating system and browser. Load the intended URL, grant microphone permission, and use **Prepare session**, then **Start voice**. Record URL, browser, device, route, configuration/model IDs, commit, and network.
2. Make a three-turn EVI practice conversation: “Suggest one way to rehearse a short presentation”; “Keep the suggestion under ten words”; “Repeat the final suggestion once.” Hear each reply and read each speaker's transcript. This checks conversation infrastructure, not task-board actions or SambaNova integration.
3. Interrupt a longer answer with “Stop; give me one short sentence.” Confirm old speech stops rather than continuing behind the new reply.
4. Perform the failure matrix below, recording the observed behavior. Repeat the full three-turn check on the final integrated route and from the hosted URL after deployment.
5. Capture ten ordinary turns for latency measurement only after basic audio works. Reset the demo and rehearse the actual 60–90 second sequence twice.

| Check | Manual procedure and passing observation | If it fails |
| --- | --- | --- |
| Normal turns / transcript | Three turns; intelligible output; each final user/assistant message appears once in order. | Record route and symptom; fix before labeling live voice ready. |
| Pause / turn detection | Pause briefly inside a sentence, then finish it; no repeated premature replies. | Keep test utterances concise; investigate turn strategy before tuning. |
| Interruption | Speak during a response; stale playback stops and next turn is coherent. | Shorten replies; use End/restart as an explicitly disclosed fallback. |
| Self-correction | Say “Make it Tuesday—sorry, Wednesday”; the response uses the final value. On the board route, inspect stored state. | Ask one clarification; do not claim the earlier action was corrected unless it was. |
| Silence | Remain silent for 20 seconds; no crash or repeated reprompt loop. | End the session and record any unbounded behavior. |
| Background noise | Repeat ordinary turns with the headset in a moderately noisy room; note false turns. | Move to quieter placement and retry the actual device. |
| Mic denied / missing | Deny microphone permission, then test with no input device; UI reports recovery instead of hanging. Restore permission/device and restart. | Demonstrate text/recording only with a clear label until corrected. |
| Prepare → Start voice → End session → Prepare → Start voice | Use End session while speaking, observe Ready when you are and stopped capture, then Prepare session and Start voice again. Only one session/voice remains. | Refresh and rerun; do not leave a stale provider session active. |
| Invalid / expired auth | In an isolated practice configuration, test invalid credentials or an expired test token; do not print them. A bounded error appears; a new session requests a new token. | Restore local config and reconnect; count no failed attempt as audio proof. |
| Quota / timeout / disconnect | Use controlled fixture failures; separately interrupt connectivity during an authorized live practice session. Loading ends and retry is bounded. | Restore the network and restart once; use the labeled backup if unresolved. |
| Tool failure / retry | On the implemented action route, induce one validation failure and repeat one operation ID. Report failure truthfully; successful retry creates no duplicate. | Use generic fixture evidence only; omit an unproven voice-action claim. |
| Secret handling | Inspect sanitized requests, browser bundles, and logs. Browser may hold temporary access tokens; it must not hold long-lived provider keys. Do not export tokens in shared HAR files. | Stop sharing artifacts and fix server/client boundaries. |
| Hosted / network | Run the entire interaction on the intended HTTPS URL and presentation network. For Pipecat verify actual media flow and configured relay support. | Use the known working local route or labeled recording, subject to host rules. |

For each observation, append the checklist's PASS/FAIL/BLOCKED/NOT RUN entry format to [readiness.md](readiness.md). Include sanitized evidence, a named owner, next action, and fallback. Host/account decisions belong to Aishik; code defects belong to the coordinator and the owning implementation lane.

## Latency observation template

Status: **NOT RUN**. Actual sample count **0**; median and slowest observed turn **N/A**.

Measure end-to-end delay as **audible assistant playback start minus actual end of user speech**. Use a recording with a shared timeline or aligned client instrumentation. A transcript arrival time is a **proxy**, not evidence of when speech ended or playback began. Measure LLM latency separately from request start to the first **nonempty text** chunk; ignore empty/control chunks. Do not combine clocks from different machines without alignment.

Record: route ___; commit ___; URL ___; network ___; device/browser ___; provider endpoint/model ___; Hume config/version or voice ___; date ___; measurement method/recording path ___; cold/warm session ___; STT/turn settings ___.

| Turn | End of speech (ms) | Audible reply start (ms) | Speech-to-speech delay (ms) | LLM request → first text (ms) | Evidence / notes |
| --- | --- | --- | --- | --- | --- |
| 1 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 2 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 3 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 4 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 5 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 6 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 7 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 8 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 9 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |
| 10 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | — |

Report valid sample count, median, and maximum separately for each metric. Do not replace failures with zero or silently remove slow turns. Initial project target: speech-to-speech median under 2 seconds; this is not an organizer requirement or achieved result. Inspect turn detection, STT, first text, TTS, buffering, and cold starts before tuning the largest observed contributor.

## Event-day working milestones

All milestones are September 19, 2026, **America/Los_Angeles**. They remain **NOT RUN** until the event. Confirm the final schedule at registration; current source disagreement is documented in [event-brief.md](event-brief.md).

| When | Action / acceptance | Owner |
| --- | --- | --- |
| 10–10:30 a.m. | Check in; confirm rules/deadline/submission link, actual audio device, venue network, and sponsor support location. | Aishik |
| Kickoff | Obtain starter URL, credits, exact endpoints/models; run the unmodified starter. Inventory STT and transport. | Aishik + coordinator |
| By noon | Select the permitted small use case; assign non-overlapping files; preserve baseline commit or document exact access blocker. | Coordinator |
| By 2 p.m. | Complete one spoken request with its visible result; take unresolved integration blockers to sponsor support. | Voice + inference lanes |
| By 4 p.m. | Core interaction complete; cut optional features. | Coordinator |
| By 5:30 p.m. | Freeze features; test failures; deploy through the authorized host; reset data and rehearse twice. | QA + Aishik |
| By 6 p.m. | Record an audible, readable backup and verify playback from the local file. | Aishik |
| By 6:30 p.m. | Prepare pitch, team, repository, actual demo URL/video, integration explanation, and required disclosures. | Coordinator + Aishik |
| Before confirmed deadline | Submit at the actual organizer link; save confirmation. Use 7 p.m. as conservative planning cutoff until clarified. | Aishik |
| Before presenting | Correct tab/device; warm up one turn; reset sandbox data; open tested backup. | Aishik |

**Backup location:** `artifacts/backup-demo.mp4` is the planned local path, **NOT CREATED**. The current fallback is an explicitly labeled practice UI/fake CLI demonstration; it does not satisfy live audio or sponsor-integration acceptance. Recordings must be labeled recorded, and fallback eligibility needs host confirmation. Never state “backup ready” until the file exists and its input/output audio and readable UI have been checked.

**Submission fields still UNKNOWN:** project/team name, team members, repository URL, deployed URL, recording URL, host rubric, submission URL, final deadline, and confirmation receipt. Fill from observed event facts; do not invent them for a complete-looking form.
