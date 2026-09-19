# Readiness evidence — September 19, 2026

**Three browser routes are implemented.** Hume EVI, Deepgram → SambaNova → Hume TTS, and the new **Gradium STT → General Compute → Gradium TTS** route are selectable independently. The user reported working Hume EVI. Real provider checks and a complete synthetic spoken turn through Next.js, WebRTC, and Pipecat now pass for the new route. A human headset check is still needed to establish browser microphone and speaker acceptance.

This is a **practice workspace**, with initial preparation recorded September 18. A route switch requires ending the current session. Both modular stacks share one Python server and permit only one modular session at a time. The SambaNova CLI remains a separate text test. The optional EVI custom-model bridge is not selected. See [new stack setup](generalcompute-gradium.md), [event facts](event-brief.md), [demo procedure](demo.md), [original Pipecat setup](pipecat.md), and [deployment procedure](deployment.md).

## Latest verification — General Compute and Gradium

- **PASS:** primary provider documentation and installed Pipecat 1.11 service contracts inspected. General Compute's unauthenticated public catalog returned `gpt-oss-120b`, `deepseek-v3.1`, `deepseek-v3.2`, `gemma-4-31B-it`, and `minimax-m2.7`; this is not account access or inference evidence. Sources, key creation, exact model/voice examples, region choices, and startup steps are in [the setup guide](generalcompute-gradium.md).
- **PASS:** 54 JavaScript tests and TypeScript. Third-route proxy tests cover route-specific configuration, fixed signaling targets, same-origin restrictions, response filtering, and safe provider messages. The existing EVI and original modular checks still pass.
- **PASS:** 49 Python tests, frozen dependency resolution, and runtime imports. New tests cover native Gradium semantic turns and final transcripts, interruption, late audio suppression, setup cancellation/socket cleanup, TTS deadlines, documented integer flush IDs, reasoning-field filtering, route isolation, and the provider probe protocol. Provider replies are simulated in these tests.
- **PASS:** production Next.js build with two new synthetic secret canaries. HTTP verification rendered all three route choices and checked both modular endpoints' origin/body/method restrictions. The temporary port-3100 listener required the approved sandbox retry and was stopped after the check. No provider calls occurred in this HTTP check.
- **PASS:** source/browser assets scanned for all six configured secrets, plus a separate scan with synthetic General Compute and Gradium build canaries. No exposure found.
- **PASS:** refreshed source archive contains 72 files matching both the manifest and workspace; secrets and runtime paths excluded. Manifest SHA-256: `b22ec6351a46985061d769e57c2fddf3a91d010d84324739fd076cdde675c217`.
- **IMPLEMENTED:** native Gradium STT with semantic turn detection, General Compute streaming text, Gradium 48 kHz TTS, bounded calls, safe diagnostics, and cleanup. New-route settings do not require Hume, Deepgram, or SambaNova keys. Cross-route peer reuse and concurrent modular sessions are rejected.
- **PASS — real providers:** after the user saved credentials/model/voice, the approved network retry returned a General Compute reply with 34 text characters and a normal `stop`; Gradium TTS generated 76,800 PCM bytes at 48 kHz; Gradium STT accepted setup, 100 ms synthetic silence, and clean end-of-stream. An overly strict probe assumption was fixed: 16 kHz input is explicitly requested, while Gradium's setup reports 24 kHz separately. All eight probe regression tests pass, including this actual rate combination. No raw provider bodies, audio, or secret values were printed.
- **PASS — running app:** Next.js `/api/gradium/health` and the corresponding authenticated Python health endpoint both return HTTP 200, configured true, no missing variables, and zero active sessions. An older Python process initially returned 404 for the new route; a guarded restart attempt changed no process because its PID had already changed. The newer running backend resolves the mismatch.
- **PASS — real integrated voice:** `npm run smoke:gradium:voice` synthesized one known phrase and sent it through the running Next.js `/api/gradium/offer` route, actual WebRTC/RTVI connection, and native Pipecat pipeline. Gradium recognized the known input (39 transcript characters), General Compute generated the reply (42 characters), and at least five non-silent 48 kHz audio frames returned. POST/PATCH signaling succeeded and teardown returned active sessions to zero. The run used real providers after approved network access; all audio stayed in memory, with no microphone recording or speaker playback. The initial restricted run failed before any provider call.
- **LIMITATION:** browser automation again failed during plugin startup because its runtime disallowed an imported module. Actual route clicks, microphone permission, audible speech, and live interruption still need a human browser check.

## Previous verification — September 18 Pipecat provider failure diagnosis

- **PASS:** 50 JavaScript tests; TypeScript; production Next.js build. Added provider-specific browser error tests that reject raw provider text. Earlier production HTTP verification covered both route choices, same-origin signaling, missing EVI config, invalid requests, and no-store responses.
- **PASS:** 29 Python tests covering configuration, safe startup and stopped messages, signaling/reconnect/cleanup, provider-service construction, SambaNova deadline, provider classification, and a real PipelineWorker/RTVI flow using simulated providers. An HTTP 402 exception through the worker produces the same fixed SambaNova billing message in the terminal and browser event; raw provider content is withheld. The system prompt now uses `Settings.system_instruction` instead of the deprecated initial system message.
- **PASS:** real local WebRTC negotiation, data-channel round trip, synthetic 48 kHz audio frames, PATCH, and teardown via `npm run smoke:transport`. Local UDP required the approved sandbox retry. This uses neither provider APIs nor a microphone/speaker.
- **PASS:** source/browser bundle secret scan included the configured Hume, SambaNova, and Deepgram secrets and found no exposure.
- **PASS:** all five modular settings are now present. Live `provider_probe.py` checks opened a Deepgram WebSocket and sent 100 ms of synthetic silence; Hume TTS generated 88,320 PCM bytes for “Hello.” This establishes connection/synthesis only, not spoken recognition or audible browser playback.
- **FAIL / ACCOUNT BLOCKER:** the same live probe received HTTP 402 from SambaNova for `MiniMax-M2.7`; a targeted check classified the provider response as `CREDITS_EXHAUSTED`. Restore credits for the account behind the configured key, then run `npm run smoke:providers -- --provider sambanova` from `practice/`. No billing setting or balance was changed.
- **PASS:** source snapshot refreshed after these fixes; all 67 archived files match both the manifest and current source. Manifest SHA-256: `6b52b73b628cd012968f763ce49088615ca97603c17f4cd4966f8db2ec982a6e`. Secret files and runtime directories are excluded.
- **LIMITATION:** browser automation still cannot initialize because the installed plugin imports a module disallowed by its runtime. Visual interaction, microphone permission, audible response, interruption, and cleanup need human browser verification. No new real Pipecat-provider conversation is claimed.

Use [the detailed setup guide](pipecat.md) to resolve SambaNova credits. Restart the existing Python process with `npm run dev:pipecat`, refresh the browser to load the diagnostic fixes, and test **Modular Pipecat** after the targeted provider probe passes. Hume EVI remains the default route and uses its existing three Hume variables.

Statuses mean: **PASS** = the stated scope was observed; **FAIL** = an observed check failed; **BLOCKED** = a named prerequisite prevents acceptance; **NOT RUN** = optional, future, or unperformed work. An automated PASS never substitutes for an actual microphone/playback check. Results below were collected by the coordinator and delegated implementation/review lanes; all provider values shown are public endpoints or synthetic fixtures.

## Tested environment and configuration

| Item | Observed value |
| --- | --- |
| Initial workspace | Checklist only; no existing app, repository Git metadata, or applicable `AGENTS.md` found. Practice code was created separately. |
| Git executable | 2.50.1; no project commit exists. Use the source snapshot below. |
| JavaScript | Node 23.11.0; npm 10.9.2; Next.js 16.3.5; React/React DOM 19.3.0 |
| Voice dependencies | `@humeai/voice-react` 0.3.0-beta.6; `hume` 0.16.1; Pipecat client 1.13.1; Small WebRTC 1.10.8; Daily media SDK 0.90.0 |
| Supporting dependencies | TypeScript 7.0.2; dotenv 18.0.0; `practice/package-lock.json` retained |
| Python | Isolated environment Python 3.12.10; machine default `python3` 3.13.3; uv 0.5.5 |
| Pipecat | `pipecat-ai` 1.11.0 pinned; `cli,deepgram,gradium,hume,runner,sambanova,silero,webrtc` extras; `pipecat-readiness/uv.lock` retained |
| Real provider/model/config | Hume token issued; selected EVI config read successfully (EVI 3, revision 1, default language model, no custom endpoint). Current SambaNova `MiniMax-M2.7` returns HTTP 402 / exhausted credits. Deepgram `nova-3-general` connection succeeded; configured Hume TTS voice synthesized audio. Earlier user's DeepSeek-V3.2 CLI attempt timed out. |
| Public practice endpoint | `https://api.sambanova.ai/v1`; not proof of an assigned event endpoint |
| Local application | Next.js `http://127.0.0.1:3000`; Pipecat `http://127.0.0.1:7860`; isolated HTTP production check uses port 3100 |
| Hosted URL / official starter | UNKNOWN / **TBD — obtain at kickoff** |
| Human audio / latency | User reports Hume EVI worked; no detailed acceptance record or modular voice check. Timed sample count 0; median and slowest delay N/A |

The ignored `practice/.env.local` now contains the user-supplied Hume EVI and modular Pipecat configuration. Secret values have not been printed. Existing process variables take precedence over `.env.local`, then `.env`. Next.js, CLI scripts, and the Python backend load this shared configuration; restart the relevant process after changing it. Fake checks require no provider variables.

## Initial preparation verification records (historical)

These original records describe the earlier blank-credential baseline. The latest verification and current ledger supersede their missing-credential and import-only statements.

### A02–A07 / F01–F03 — Reproducible local preparation

- Status: **PASS**, local practice scope.
- Owner: Coordinator.
- Route / commit / runtime: Practice EVI frontend/server, independent inference scripts, isolated Pipecat imports; no Git commit; versions above.
- Command or manual action: Workspace/instruction inspection; `git --version`, `node --version`, `npm --version`, Python/uv version checks; from `practice/`, `npm ci --offline`; from `pipecat-readiness/`, `uv sync --frozen --offline --cache-dir .cache/uv --python 3.12`.
- Expected outcome: Preserve the checklist, install from retained lockfiles, and reproduce the selected practice environment.
- Observed outcome and sanitized evidence: Clean cached npm install succeeded: 39 packages installed, 0 audit vulnerabilities reported. Frozen cached uv sync succeeded. The voice SDK's nested React dependencies use a narrow override to the app's React/React DOM versions; one React runtime was verified. Versions, environment contract, install/start/stop commands, and route-specific checks are documented in [README](../README.md).
- Remaining blocker and next action: Event starter pins are UNKNOWN; coordinator must inspect and use the actual starter at kickoff. Local caches do not contain that starter's future speech/turn models.

### A07 / B02 / B07 — Missing configuration and token fixtures

- Status: **PASS** for configuration/error tests; **BLOCKED** for real token issuance and EVI connection.
- Owner: Coordinator for code; Aishik for account access and credentials.
- Route / commit / runtime: Next.js server token endpoint, Node 23.11.0; synthetic provider responses only.
- Command or manual action: `npm run check:config -- evi`; `npm run check:config -- sambanova`; `npm test`; fake-fetch cancellation probe.
- Expected outcome: Missing variables fail before a provider call; only temporary access tokens and public configuration IDs enter successful browser responses; cancellation is bounded and errors reveal no secret values.
- Observed outcome and sanitized evidence: EVI reports missing `HUME_API_KEY`, `HUME_SECRET_KEY`, `HUME_CONFIG_ID`. SambaNova reports missing `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL`. Token fixtures exercise fresh requests, no-store headers, same-origin rejection, malformed responses, auth/quota errors, timeout, and sanitized transport failure. Caller cancellation propagated to the injected provider signal and returned a sanitized 502. An oversized `HUME_CONFIG_VERSION` validation defect was fixed; safe nonnegative integers are now required.
- Remaining blocker and next action: Aishik must supply real account configuration locally and confirm quota; then verify active EVI config/version and repeat the real three-turn test. Until then, use only the visibly labeled transcript fixture.

### A09 / Failure matrix — Secret boundaries

- Status: **PASS** for source/static bundle checks; live browser request inspection **BLOCKED**.
- Owner: Coordinator.
- Route / commit / runtime: Production Next.js build with synthetic canaries; no real secrets.
- Command or manual action: Production build with three synthetic provider-secret canaries; `npm run check:secrets`; inspect ignore rules and local secret-file permissions.
- Expected outcome: Long-lived provider values do not appear in source/public browser assets; token responses remain private and uncacheable.
- Observed outcome and sanitized evidence: Source and `.next/static` scan checked 66 files without finding the three canaries. A later scan checked 67 files with zero configured real secret values; that second scan is not evidence of detecting absent credentials. No actual provider keys were used. Real `.env` files are ignored; `.env.example` remains trackable. Server routes hold long-lived keys; successful token response fixtures contain only temporary access token/config fields. The HTTP test confirms `Cache-Control: no-store, private` on token errors.
- Remaining blocker and next action: Coordinator/Aishik must inspect requests during an actual session without sharing token-bearing HAR files. This static result does not prove future hosted secrets or live browser traffic are correct.

### A08 — Network reachability

- Status: **PASS** for listed public domains; **BLOCKED** for the intended host.
- Owner: Coordinator; Aishik supplies the authorized host.
- Route / commit / runtime: Unauthenticated HEAD requests from the development machine.
- Command or manual action: `npm run check:network`; after sandbox DNS failure, approved machine-network retry.
- Expected outcome: Provider/package domains can be contacted; no credentials or paid provider request are required.
- Observed outcome and sanitized evidence: `api.hume.ai` HTTP 404, `api.sambanova.ai` HTTP 405, npm registry HTTP 200, and PyPI HTTP 200. HTTP 404/405 prove server reachability only. Initial sandbox DNS failure did not persist on the approved retry.
- Remaining blocker and next action: Intended host/domain UNKNOWN. Aishik must name an authorized host and budget; set the optional `DEPLOYMENT_URL` and repeat connectivity. No inference, credential validity, or quota is established by HEAD.

### C03–C08 — Inference/parser/tool preparation

- Status: **PASS** for deterministic fake streaming, failure handling, and sandbox tools; **BLOCKED** for real-provider acceptance.
- Owner: Inference lane; Aishik supplies account/model access.
- Route / commit / runtime: Node 23.11.0; explicit fake provider or configured real SambaNova CLI; separate from EVI.
- Command or manual action: `npm run smoke:fake -- --tools`; `npm run smoke:sambanova`; `npm test`.
- Expected outcome: Fake text arrives incrementally; first nonempty text time is separate from completion; stream parser handles control/empty chunks and termination; validated local actions deduplicate repeated operation IDs. Real smoke must refuse missing credentials without requesting the provider.
- Observed outcome and sanitized evidence: Fake/tool smoke passed. One synthetic run reported first text **78.6 ms**, total **211.6 ms**. These values are **DEMO DATA**, not SambaNova performance or speech-to-speech latency. The tool fixture updates an in-memory `practice-task` from `todo` to `done`, returns a structured result, and consumes that result in its fake continuation. Process exit discards state. Real smoke exited 1 with only missing variable names and made no request. Tests exercise parsing, stream termination, unavailable/auth/quota/transport errors, timeout/cancellation, schema validation, and duplicate/conflicting operation IDs.
- Remaining blocker and next action: Aishik must confirm credit and an exact available model ID. Run both real request modes, then optional `--tools`; record public endpoint/model and sanitized text/timings. Normal smoke makes two requests; `--tools` makes four total. The fake fixture remains a learning aid and does not prove voice-controlled app actions.

### B01 / B03–B07 — Voice implementation and transcript verification

- Status: **PASS** for installed SDK/build and transcript fixtures; **BLOCKED** for browser interactions and live voice acceptance.
- Owner: Voice lane for implementation; Aishik for real laptop/headset observation.
- Route / commit / runtime: Hume EVI practice UI, SDK versions above; no SambaNova connection in this UI.
- Command or manual action: SDK source/type inspection; `npm run typecheck`; `npm run build`; six transcript tests included in `npm test`.
- Expected outcome: Real user/assistant message types display in order, partials remain distinguishable, Start follows a user gesture, and new preparations request fresh tokens.
- Observed outcome and sanitized evidence: Implementation uses **Prepare session → Start voice → End session**, mute/unmute, status/error controls, final/interim transcript handling, and fresh-token preparation. Automated transcript tests passed. Framework/type/build checks passed. Browser skill bootstrap failed with `Importing module node:process is not allowed in node_repl` before browser interaction; no page clicks, microphone permissions, sound, interruption, or resource cleanup were observed in a real browser.
- Remaining blocker and next action: Restore browser-tool availability or have Aishik perform [manual checks](demo.md) after supplying Hume credentials/config. Mark B03–B07 complete only after their observed acceptance; implemented code alone is insufficient.

### P01 / P04 — Pipecat prerequisites and explicit service gaps

- Status: **PASS** for prerequisites/imports and documenting the unavailable live configuration; live Pipecat **BLOCKED**.
- Owner: Coordinator; Aishik obtains starter/service access.
- Route / commit / runtime: Python 3.12.10, Pipecat 1.11.0, uv 0.5.5, isolated `pipecat-readiness/`.
- Command or manual action: Frozen uv sync; `uv run --frozen --cache-dir .cache/uv python check_runtime.py`; `uv run --frozen --cache-dir .cache/uv pipecat --help`; `npm run check:pipecat` from `practice/`; inspect installed Hume/SambaNova constructor/settings APIs.
- Expected outcome: CLI and service imports work without provider requests; missing STT/transport/voice/model access is explicitly named.
- Observed outcome and sanitized evidence: Both `SambaNovaLLMService` and `HumeTTSService` import successfully; CLI help and the npm wrapper succeed. Installed `Settings(model=...)`, `Settings(voice=...)`, and SambaNova `base_url` match [pipecat.md](pipecat.md). Hume output is documented as 48 kHz PCM; actual transport/audio compatibility is NOT RUN. No STT is selected; Small WebRTC is only a candidate pending the starter. Official URL stays **TBD — obtain at kickoff**.
- Remaining blocker and next action: Obtain the actual starter, STT, transport/relay setup, endpoint/model/voice IDs, and credentials. Run it unchanged before porting any permitted feature. Hume TTS does not transcribe incoming speech.

### D02 / D03 / D06 — Build and production HTTP rehearsal

- Status: **PASS**, local Node deployment/run path only.
- Owner: Coordinator.
- Route / commit / runtime: Production Next.js/Node on loopback, isolated port 3100 for verification; no hosted URL.
- Command or manual action: `npm test`; `npm run typecheck`; `npm run build`; `npm run verify:http`.
- Expected outcome: Tests/type/build succeed; production process starts, serves app/health/error routes, and stops without an unexplained background daemon.
- Observed outcome and sanitized evidence: **35 tests passed**: 7 configuration/token, 20 inference, 2 latency, 6 transcript. Typecheck and webpack production build passed. HTTP rehearsal passed: page 200; health 200 with no-store and both configuration flags false; same-origin token 503 with missing names and private/no-store headers; cross-origin token 403; token GET 405; microphone policy present. The runner starts/stops its own production process. An initial localhost/127.0.0.1 origin mismatch was fixed and covered by regression/HTTP checks. Hosted use requires exact HTTPS `APP_ORIGIN`; loopback uses validated local Host handling.
- Remaining blocker and next action: Browser bootstrap, provider credentials, human audio, and authorized hosting remain missing. HTTP HTML success is not visual/browser/microphone QA. Public hosting is not rehearsed.

### D07 — Source baseline and rollback

- Status: **PASS**, source identity/restore comparison and tutorial reset scope.
- Owner: Coordinator.
- Route / commit / runtime: Practice source snapshot; no Git repository/commit.
- Command or manual action: `python3 scripts/record-baseline.py`; extract the resulting archive into a fresh temporary directory with the safe data filter; compare every restored file against the SHA-256 source manifest and current source.
- Expected outcome: Identify the tested source without secrets and restore it without overwriting the workspace.
- Observed outcome and sanitized evidence: Final baseline contains **48 files**, including the updated source checklist. Every restored file matched both its manifest hash and current source. No real `.env` file, dependency directory, build output, or private observation was archived. Evidence: [source manifest](../artifacts/source-manifest.sha256) and [local baseline archive](../artifacts/local/practice-baseline.tar.gz). This readiness ledger is intentionally outside the archive as an observation record. Exact separate-directory restore commands are in [README](../README.md). No second install was needed after the byte-identical restore; clean cached installation was already verified separately.
- Remaining blocker and next action: Re-record the baseline after future source changes; do not overwrite current work or use a destructive reset. CLI sandbox state resets on process exit; voice transcript resets after ending the session and using Clear. A live task-board reset and backup recording remain unperformed event work.

### Q01–Q04 — Latency collection

- Status: **BLOCKED** for real measurements; helper validation **PASS**.
- Owner: Aishik records audio; coordinator summarizes aligned measurements.
- Route / commit / runtime: No real final-route observations; `docs/latency.example.json` contains an empty turns array.
- Command or manual action: `npm test` latency fixtures; planned `npm run measure:latency -- /path/to/observed-turns.json`.
- Expected outcome: Distinguish speech-end → audible playback from LLM request → first nonempty text and transcript-arrival proxies. Report count, median, and slowest observed turn without inventing samples.
- Observed outcome and sanitized evidence: Two helper tests passed, including even-sample median, invalid timestamps, empty observations, and explicit proxy labeling. Live sample count **0**; median **N/A**; slowest **N/A**. Synthetic inference timings above are excluded.
- Remaining blocker and next action: After live audio works, Aishik records ten ordinary turns with a shared timeline and route/model/network metadata. Under two seconds median is a project target only. Diagnose the largest observed contributor if delay is disruptive.

## Blockers, ownership, next actions, and fallbacks

| Code | Blocker | Owner / next action | Honest fallback |
| --- | --- | --- | --- |
| K1 | Registration, travel/equipment, final agenda, submission URL, team/rubric/AI/reuse rules UNKNOWN | Aishik confirms with hosts and records answers in event brief. No one has been contacted on the user's behalf. | Preserve pre-event practice provenance; arrive for 10 a.m.; target submission-ready 6:30 p.m. until final rules are known. |
| K2 | Detailed Hume browser acceptance/quota record incomplete | Hume keys/config and token issuance are present; Aishik repeats three-turn, interruption, and reconnect checks. | User-reported working EVI; sample transcript remains labeled. |
| K3 | SambaNova account returns HTTP 402 / exhausted credits for configured `MiniMax-M2.7`; assigned event endpoint still unknown | Aishik restores account credits; rerun targeted provider probe, then real nonstream/stream/tool checks. | Deterministic DEMO DATA CLI; no successful sponsor-inference claim. |
| K4 | Modular practice awaits funded SambaNova and full voice acceptance; official starter still pending | Configuration is present; Deepgram connection and Hume synthesis passed. Resolve K3 and complete headset checks. Obtain actual event starter at kickoff. | Implemented combined pipeline and simulated checks; no real modular conversation claim. |
| K5 | Browser tool cannot bootstrap; detailed headset acceptance incomplete | Aishik performs laptop/headset checks in demo.md for both modes. | HTTP/build, worker fixtures, and synthetic local WebRTC evidence; no automated browser/audio PASS. |
| K6 | Authorized compatible host, public URL, hosted secrets, and budget UNKNOWN | Aishik selects authorized host; coordinator follows deployment.md and rehearses HTTPS/audio there. | Local production run on loopback; still needs network/API access. |
| K7 | Event has not occurred; baseline feature, submission, and recording not performed | Aishik/coordinator follow event-day milestones after rules and baseline are known. | Written plan; planned recording path is NOT CREATED. |

## Checklist task ledger

The scopes below are deliberately narrower than full preparation completion. Each BLOCKED row refers to the owner/next action/fallback in the blocker table. The source checklist is maintained separately by the coordinator.

### Human and coordinator tasks

| ID | Status | Evidence / remaining work |
| --- | --- | --- |
| H01 | BLOCKED | K1: personal registration, travel, arrival, and equipment checks are UNKNOWN. |
| H02 | BLOCKED | K1: final agenda, submission link/limit, team rules, and rubric UNKNOWN. |
| H03 | BLOCKED | K1: required sponsor services/starter and AI agent permission UNKNOWN. |
| H04 | BLOCKED | K1: pre-event reuse rules UNKNOWN; provenance retained. |
| H05 | BLOCKED | Credentials are supplied; SambaNova credits are exhausted (K3). |
| A01 | PASS | Event brief records sourced facts, UNKNOWNs, and host questions; no outreach. |
| A02 | PASS | Initial workspace/instructions inspected; separate practice directories preserve checklist. |
| A03 | PASS | Git, Node/npm, Python, and uv versions observed; runtime compatibility documented. |
| A04 | PASS | npm and uv lockfiles retained; cached clean installs verified; coordinator owns manifests. |
| A05 | PASS | Placeholder env example; real local env ignored and mode 600. |
| A06 | PASS | Next.js server env loading and explicit script env loading documented/implemented. |
| A07 | PASS | Selected-route validation fails with names only; fake route needs no secrets. |
| A08 | BLOCKED | Public service/registry reachability PASS; intended host UNKNOWN (K6). |
| A09 | PASS | Server-only provider use, secret-free example/log fixtures, and synthetic bundle scan verified; actual browser requests remain K2/K5. |
| A10 | PASS | README, readiness ledger, and event brief distinguish practice/event configurations. |

### Inference and voice tasks

| ID | Status | Evidence / remaining work |
| --- | --- | --- |
| C01 | BLOCKED | Account returns exhausted-credit error (K3). No paid plan started. |
| C02 | BLOCKED | `MiniMax-M2.7` is configured; usable access remains unproven until funded inference passes (K3). |
| C03 | BLOCKED | Script implemented/fake tested; real nonstream request requires K3. |
| C04 | BLOCKED | Incremental parser/fake stream pass; real stream requires K3. |
| C05 | BLOCKED | Separate first-text/total metrics implemented; no real endpoint/model result (K3). |
| C06 | PASS | Bounded timeout/cancellation, readable sanitized failures, no unbounded retries; automated fixtures pass. |
| C07 | BLOCKED | Validated sandbox round trip passes with fake; exact real model/tool round trip requires K3. |
| C08 | PASS | Separate deterministic fake provider and real smoke commands; fake outputs visibly labeled. |
| B01 | PASS | Separate Next.js app, actual Hume SDK dependencies and npm lockfile installed. |
| B02 | PASS | User-supplied Hume credentials present; real server-issued temporary token verified; browser response exposes only token/config. |
| B03 | BLOCKED | Explicit Start/End/status/error controls implemented; browser interaction not observed (K2/K5). |
| B04 | BLOCKED | Provider/transcript implementation and fixtures pass; live message flow not observed (K2/K5). |
| B05 | BLOCKED | Mute/cleanup/reconnect code exists; actual capture/playback cleanup not observed (K2/K5). |
| B06 | BLOCKED | Configured EVI 3 revision 1 was read successfully; detailed active-browser-session confirmation remains K2/K5. |
| B07 | BLOCKED | Fresh/no-store token fixtures pass; real reconnect/token lifecycle not observed (K2/K5). |
| B08 | BLOCKED | No person has completed the laptop/headset three-turn test (K2/K5). |

### Pipecat and optional bridge

| ID | Status | Evidence / remaining work |
| --- | --- | --- |
| P01 | PASS | Python/uv/CLI/imports ready; responsibilities and actual-starter placeholder documented. |
| P02 | NOT RUN | Optional generic scaffold not selected; no extra provider accounts created. |
| P03 | PASS | Modular practice pipeline uses installed SambaNovaLLMService/HumeTTSService with pinned extras; real service construction and simulated worker flow pass. Live conversation still needs K4/K5. |
| P04 | PASS | Deepgram STT and Small WebRTC selected and implemented; live STT connection passed. Spoken transcription still needs headset acceptance (K4/K5). |
| P05 | BLOCKED | Configured Hume voice generated PCM successfully; browser audio playback and full integration still need headset acceptance (K4/K5). |
| P06 | NOT RUN | At kickoff: actual starter URL pending; clone/read/run unchanged first (K4/K7). |
| P07 | NOT RUN | At kickoff: inventory actual services/endpoints/IDs and prove assigned SambaNova calls (K4/K7). |
| P08 | BLOCKED | No final Pipecat three-turn transcript/interruption test (K4/K5). |
| P09 | NOT RUN | Port permitted small feature only after unchanged baseline; then retest (K1/K4/K7). |
| I01 | NOT RUN | Optional EVI bridge not selected; no custom-model endpoint implemented. |
| I02 | NOT RUN | Optional bridge SSE endpoint not selected. CLI SSE testing is separate. |
| I03 | NOT RUN | Optional public bridge/tunnel not selected; no host provisioned. |
| I04 | NOT RUN | No EVI custom-backend configuration or live integrated routing verified. |
| I05 | NOT RUN | No bridge/control-plane credential setup selected or performed. |
| I06 | NOT RUN | No spoken EVI → bridge → SambaNova → audio path demonstrated. |

### Demo scope, deployment, measurements, and handoff

| ID | Status | Evidence / remaining work |
| --- | --- | --- |
| M01 | PASS | One-person/one-result task-board pitch written as PLAN. |
| M02 | PASS | Proposed voice-controlled-software track and small local board scope written; host fit remains K1. |
| M03 | NOT RUN | Conversation-coaching product not selected. |
| M04 | PASS | Three utterances, correction/interruption, and visible outcome scripted for 60–90 seconds; actual limit/rehearsal pending. |
| M05 | PASS | Concise spoken-response/tool-truthfulness prompt written as proposed configuration; not applied to a real session. |
| M06 | BLOCKED | Final demo action not implemented pending reuse rules; generic sandbox validation is not the product (K1/K7). |
| M07 | BLOCKED | No integrated task board/action UI; sample transcript is labeled fake (K7). |
| M08 | PASS | Explicit cut list in demo.md. |
| D01 | BLOCKED | Host/runtime needs documented; authorized host, credentials, and budget absent (K6). |
| D02 | PASS | Lockfile install/start/stop commands and secret-free health endpoint exist; HTTP rehearsal passed. |
| D03 | PASS | Practice variables, loopback ports, token routing, stop/reset steps documented; public URL explicitly UNKNOWN. |
| D04 | BLOCKED | No hosted provider/audio rehearsal (K2/K3/K5/K6). |
| D05 | BLOCKED | Real local WebRTC/synthetic audio smoke passes; browser and venue network/relay checks remain K4/K5/K7. |
| D06 | PASS | 50 JS and 29 Python tests, typecheck, and production build pass. Earlier HTTP checks and local synthetic WebRTC smoke passed; scope is stated above. |
| D07 | PASS | Source snapshot refreshed after the dual-mode checks; archive hashes match manifest/current source; no Git commit or live task-board baseline claimed. |
| D08 | PASS | Practice dependencies cached/reinstalled offline. External APIs still required; event assets unavailable until K4. |
| Q01 | BLOCKED | Ten real aligned speech/audio observations absent; n=0 (K2/K4/K5). |
| Q02 | BLOCKED | Real first-text latency absent; fake metric and transcript proxy explicitly distinguished (K3/K5). |
| Q03 | BLOCKED | No real median/slowest/sample result; helper tests only (K2/K3/K5). |
| Q04 | NOT RUN | Diagnose/tune only after real measured delay reveals a contributor. |
| F01 | PASS | README contains exact local install/configure/run/verify/stop commands. |
| F02 | PASS | Env example names route-specific placeholders without real secrets. |
| F03 | PASS | JS/Python lockfiles and tested runtimes retained; cached reinstall passed. |
| F04 | PASS | Event brief contains sources, conflicts, host questions, and explicitly UNKNOWN final rules/deadline. |
| F05 | BLOCKED | This ledger has automated and individual-provider evidence; full modular voice and human audio acceptance remain K2/K3/K4/K5. |
| F06 | PASS | Demo document includes pitch, steps, reset, and planned backup location explicitly NOT CREATED. |
| F07 | PASS | Known blockers have named owners, next actions, and truthful fallbacks above. |
| F08 | PASS | Current handoff explicitly distinguishes verified local tasks, mocks, blockers, and future event work; no claim of full readiness. |

## Final-route voice and failure matrix

The final event route has not been configured. Every live/manual row remains blocked. Automated fixture evidence is listed separately to avoid counting it as a microphone or hosted result.

| Check | Status | Automated / actual evidence | Owner, next action, and mitigation |
| --- | --- | --- | --- |
| Normal conversation | BLOCKED | No spoken turns or intelligibility observation. | Aishik: K2/K4/K5, three turns on actual headset; labeled transcript fallback. |
| Turn detection | BLOCKED | No short-pause trial. | Aishik/voice lane: run pause test on chosen route; shorten utterances if needed. |
| Interruption | BLOCKED | Lifecycle implementation exists; no heard interruption. | Aishik/voice lane: speak over reply and confirm stale speech stops; End/restart fallback. |
| Self-correction | BLOCKED | Scripted correction only; no real stored outcome. | Aishik/inference lane: verify final value on real route; ask clarification rather than claim success. |
| Silence | BLOCKED | No live idle/reprompt observation. | Aishik: 20-second silence trial; end session if reprompt loops. |
| Background noise | BLOCKED | No headset/noisy-room trial. | Aishik: repeat ordinary turns with actual equipment; quieter placement fallback. |
| Microphone denied / missing | BLOCKED | Error paths implemented; browser tool cannot start. | Aishik/voice lane: deny permission/remove device and recover; labeled fixture until verified. |
| Start → End → Start | BLOCKED | SDK cleanup code inspected; no browser/audio lifecycle observation. | Aishik/voice lane: repeat with one voice and stopped capture; close tab if cleanup fails. |
| Expired / invalid auth | BLOCKED | Auth/token fixtures PASS, real reconnect NOT RUN. | Coordinator/Aishik: controlled invalid-token trial and fresh preparation; restore config then retry once. |
| Quota / timeout / lost connection | BLOCKED | Sanitized timeout/quota/transport fixtures PASS; live UI recovery unobserved. | Coordinator/Aishik: controlled failure on actual route; bounded restart or labeled fallback. |
| Tool failure / repeated request | BLOCKED | Fake tool validation/deduplication PASS; integrated voice action absent. | Inference lane: real model round trip then actual board; demonstrate fixture only with label. |
| Transcript correctness | BLOCKED | Six transcript fixtures PASS; real ordered transcript unobserved. | Voice lane/Aishik: compare spoken turns/finals/partials on actual route; avoid claiming live transcript accuracy. |
| Secret handling | BLOCKED | Source/static-canary scan and token no-store/error fixtures PASS; live requests/host not checked. | Coordinator: inspect actual requests without exporting tokens; keep loopback until authorized host configured. |
| Hosted rehearsal | BLOCKED | Local production HTTP PASS; no public deployment or audio. | Coordinator/Aishik: K6, deploy/retest chosen route; known local process path as fallback. |

## Event-day tasks — all future

All times are September 19, 2026, America/Los_Angeles. These are working milestones, not verified organizer deadlines. The final deadline remains UNKNOWN.

| Milestone | Status | Owner / next action |
| --- | --- | --- |
| 10–10:30 a.m. check-in | NOT RUN | Aishik confirms final rules, deadline, equipment/network, sponsor support. |
| Kickoff | NOT RUN | Aishik/coordinator obtain actual starter, endpoints/IDs/credits; run unchanged baseline. |
| By noon | NOT RUN | Coordinator chooses permitted use case, assigns files, records baseline or sponsor-access blocker. |
| By 2 p.m. | NOT RUN | Voice/inference lanes produce one spoken request with visible result; seek sponsor support if blocked. |
| By 4 p.m. | NOT RUN | Coordinator freezes core scope and cuts optional features. |
| By 5:30 p.m. | NOT RUN | QA/Aishik verify failures, deploy, reset, rehearse twice. |
| By 6 p.m. | NOT RUN | Aishik records and plays back audible/readable backup. Planned `artifacts/backup-demo.mp4` does not exist. |
| By 6:30 p.m. | NOT RUN | Coordinator/Aishik prepare actual submission fields and disclosures. |
| Before confirmed deadline | NOT RUN | Aishik submits through real organizer URL and retains confirmation. Conservative planning cutoff 7 p.m. until clarified. |
| Before presenting | NOT RUN | Aishik opens tested tab/device, warms route, resets data, and opens verified backup. |

**Next required human action:** restore SambaNova credits, rerun the targeted provider probe, restart the Python backend, refresh the browser, and test both routes on a headset. Event rules, registration, and any public host/budget remain separate decisions. No organizer permissions, credits, or completed voice acceptance have been invented.
