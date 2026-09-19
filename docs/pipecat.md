# Pipecat voice setup and starter migration

The browser's **Pipecat** mode connects to a local Python pipeline: **Deepgram STT → SambaNova LLM → Hume TTS**. The existing **Hume EVI** mode remains the default and uses its own speech-to-speech service. Changing modes changes the backend that handles the conversation; the standalone SambaNova CLI remains a separate text-inference check.

The third browser mode, **Gradium + General Compute**, uses the same Python server with different providers and independent configuration. Follow its [dedicated setup guide](generalcompute-gradium.md); this page covers the original Deepgram/SambaNova/Hume route.

This is generic practice work prepared on September 18, 2026. The official event starter URL remains **TBD — obtain at kickoff**. The user has reported Hume EVI working; the new modular pipeline's real provider access and headset behavior still need validation. Refer to [readiness.md](readiness.md) for observed checks rather than treating these instructions as proof of a live session.

## Configure the five required values

Use the existing ignored `practice/.env.local`. Preserve your working EVI values and add the missing modular values in a local editor:

```dotenv
# Required for the Pipecat voice mode:
DEEPGRAM_API_KEY=your_deepgram_key
SAMBANOVA_API_KEY=your_sambanova_key
SAMBANOVA_MODEL=your_exact_available_model_id
HUME_API_KEY=your_existing_hume_api_key
HUME_VOICE_ID=your_hume_tts_voice_uuid

# Optional overrides; these are the Python route's defaults:
DEEPGRAM_MODEL=nova-3-general
SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1
PROVIDER_TIMEOUT_MS=60000
```

Replace placeholders with your real values. `HUME_SECRET_KEY`, `HUME_CONFIG_ID`, and `HUME_CONFIG_VERSION` belong to EVI and are not required by Pipecat. `HUME_VOICE_ID` is a TTS voice identifier, not an EVI configuration identifier. Keep secrets out of browser-public variables, source control, screenshots, and chat.

Both backends load `practice/.env.local`; there is no second secrets file to maintain in `pipecat-readiness/`. Existing shell environment values take precedence, then `.env.local`, then `.env`. Restart Python after editing the file; restart Next.js if changing EVI settings. Starting either server or inspecting configuration does not validate credit or provider permissions.

### 1. Get the Deepgram speech-recognition key

1. Sign in or create an account at the [Deepgram Console](https://console.deepgram.com/).
2. Use the **Projects** dropdown at the top left to select your project. Deepgram creates an initial project at signup.
3. Open **Settings → API Keys → Create a New API Key**.
4. Give the key a recognizable name such as `voice-hackathon-practice`, select permissions that allow transcription, and choose an expiry covering your practice/event dates. The form also supports optional tags.
5. Select **Create Key**, copy the secret immediately, and save it as `DEEPGRAM_API_KEY`. Deepgram will not display the secret again. These steps follow its [API key instructions](https://developers.deepgram.com/docs/create-additional-api-keys).
6. Check that the selected project has credit or billing access. Keys and balances belong to projects; a balance in a different project does not establish access for this key. See [Deepgram project management](https://developers.deepgram.com/guides/deep-dives/managing-projects).

This implementation uses `DeepgramSTTService` with `nova-3-general` by default. It transcribes microphone audio before SambaNova receives the conversation. Change `DEEPGRAM_MODEL` only to a compatible model available to your account. This service is distinct from Deepgram's Voice Agent API. [Pipecat Deepgram service](https://docs.pipecat.ai/api-reference/server/services/stt/deepgram).

### 2. Get the SambaNova key and exact model ID

1. Sign in or register at [SambaNova Cloud](https://cloud.sambanova.ai/).
2. Open [API Keys](https://cloud.sambanova.ai/apis), choose **Create API Key**, and save the secret as `SAMBANOVA_API_KEY`. It cannot be viewed again after creation. [Official key guide](https://docs.sambanova.ai/docs/en/get-started/api-keys-urls).
3. Check [Billing](https://cloud.sambanova.ai/plans/billing) and [Commits and Credits](https://cloud.sambanova.ai/plans/credits). Use any organizer-provided credits first if supplied. The current [Plans page](https://cloud.sambanova.ai/plans) says to add a payment method and purchase credits to make initial requests; an account or key alone does not establish funded access.
4. Open [Playground](https://cloud.sambanova.ai/playground), select an available text model, and open **View Code**. Copy the exact `model` string into `SAMBANOVA_MODEL`. For example, `Meta-Llama-3.3-70B-Instruct` is currently listed as a production model; use it only if your account/endpoint offers it. See the [current model list](https://docs.sambanova.ai/docs/en/models/sambacloud-models).
5. Keep `SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1` for public-cloud practice. Do not add `/chat/completions`; the client appends that path. Substitute the organizer's base URL and model for a dedicated event endpoint. [API URLs](https://docs.sambanova.ai/docs/en/get-started/api-keys-urls).

To check SambaNova independently, from `practice/` run:

```sh
npm run check:config -- sambanova
npm run smoke:sambanova
```

The first command checks local settings. The second sends **two real requests**, one non-streaming and one streaming; it prints replies and timing, then exits. It is a scripted terminal check, not an interactive chat or microphone test. Optional `npm run smoke:sambanova -- --tools` makes four requests total and exercises only the CLI's in-memory action fixture. Those tools are not part of the modular voice conversation. See [inference.md](inference.md).

### 3. Reuse the Hume API key and choose a TTS voice

1. Keep the `HUME_API_KEY` already used by your working EVI route. Pipecat's Hume TTS integration authenticates with that API key; it does not need the EVI secret or configuration.
2. Open the [Hume Voice Library](https://app.hume.ai/voices) using the same account. Choose an accessible library voice or saved custom voice, and copy its **voice ID** into `HUME_VOICE_ID`.
3. Use the UUID itself, not the voice's display name or the EVI config ID. Hume's [voice guide](https://dev.hume.ai/docs/text-to-speech-tts/voice) identifies the Voice Library and `/v0/tts/voices` as sources for IDs. Pipecat's [Hume TTS service](https://docs.pipecat.ai/api-reference/server/services/tts/hume) accepts voice IDs only.
4. Confirm TTS access and remaining usage in your Hume account. A working EVI session confirms that route; it does not prove a particular TTS voice is accessible. Hume distinguishes Octave 1 and Octave 2 voice compatibility in its voice guide.

Public documentation was checked for these instructions. Signed-in Voice Library and account billing details were not inspectable; the requested `https://r.jina.ai/` fallbacks also did not expose those pages. Follow the account UI for your current balance and available voices rather than assuming an account-specific result.

## Start both local processes

Requirements are Node >=20.9 for the frontend, Python 3.11–3.13 for this Python project, and `uv`. Existing practice runtime records are in the [README](../README.md). Install the frontend with `npm ci` from `practice/` if needed.

Terminal 1, from `practice/`:

```sh
npm run dev
```

Terminal 2, also from `practice/`:

```sh
npm run setup:pipecat
npm run dev:pipecat
```

`setup:pipecat` installs from the committed Python lockfile with `uv sync --frozen`. Run it once and after dependency changes. The second command keeps Python listening on **127.0.0.1:7860**. Keep both terminals open.

Open **http://127.0.0.1:3000**, select **Modular Pipecat**, use **Check setup again**, then **Start Pipecat voice**. Allow microphone access, then speak; the route listens for your first turn. It streams recognized speech and the assistant's response into the transcript and plays Hume's generated audio. Use mute/unmute and End from the app. End the session before switching modes. Stop each server with **Ctrl+C** in its terminal after ending the session.

The route uses [Small WebRTC](https://docs.pipecat.ai/api-reference/server/services/transport/small-webrtc), so local practice requires no Pipecat Cloud or Daily account/key. The hosted AI providers still require Internet access. There is no OpenAI or Cartesia key requirement in this pipeline; those providers appear in Pipecat's generic quickstart, not this implementation.

## Implementation and checks

Python is pinned to `pipecat-ai==1.11.0` with `cli`, `deepgram`, `hume`, `runner`, `sambanova`, `silero`, and `webrtc` extras. The browser pins `@pipecat-ai/client-js` **1.13.1** and `@pipecat-ai/small-webrtc-transport` **1.10.8**. Follow these lockfiles for practice; the event starter may use different pins.

The pipeline is transport input → Deepgram STT → user context → SambaNova → Hume TTS → transport output → assistant context. Silero detects speech activity, and Pipecat handles turn completion and interruption. Audio uses 16 kHz input and 48 kHz Hume output. The provider deadline defaults to 60 seconds, with no automatic SambaNova retry. Sessions have an idle timeout of 120 seconds and a maximum duration of 600 seconds. End/disconnect tears down the Python session and browser transport.

From `practice/`, run the offline checks:

```sh
npm run check:pipecat
npm run test:pipecat
```

The import check and offline tests do not verify keys, quota, WebRTC across networks, or audio. Record actual test results in [readiness.md](readiness.md).

To isolate a live provider failure after configuring the five variables, run:

```sh
# Real requests: a short Deepgram connection, a small SambaNova reply,
# and Hume synthesis of "Hello.". These can consume provider credit.
npm run smoke:providers
# Check only SambaNova after fixing account credits:
npm run smoke:providers -- --provider sambanova
```

The probe reports fixed error categories and HTTP status without printing keys, response bodies, transcripts, or audio. A Deepgram connection PASS verifies its WebSocket setup, not spoken transcription. Hume PASS verifies receipt of audio bytes, not audible browser playback.

`npm run smoke:transport` additionally opens local UDP sockets and verifies an actual WebRTC connection, a data-channel round trip, synthetic 48 kHz audio, and teardown. It makes no provider requests and does not use the microphone or speakers. It cannot certify the browser, venue network, or intelligible speech.

Before relying on Pipecat for a demo, use a headset to verify three intelligible turns, both transcripts, interruption, mute/unmute, End/reconnect, and the browser microphone indicator disappearing after End. Check permission-denial recovery, closing the tab, and provider failure. Record the Deepgram model, SambaNova endpoint/model, Hume voice UUID, device/network, and observed latency. EVI's working-session result is separate evidence.

### Troubleshooting

| Symptom | Next step |
| --- | --- |
| Backend unavailable | Keep `npm run dev:pipecat` running in the second terminal; inspect that terminal for the startup result. |
| Missing variable names | Add those names to `practice/.env.local`, save, and restart Python. Check for old shell exports overriding the file. |
| Provider/connection failure after starting | Verify all three providers' keys, access, and credits; verify the exact SambaNova model and Hume voice ID. |
| SambaNova credit/quota error or HTTP 402 | Open SambaNova **Plans → Commits and Credits** for the account behind the key. Add or redeem available credits and confirm a usable balance; check billing if payment is required. A larger timeout will not fix a credit rejection. |
| You speak but see no user transcript | Check microphone permission, mute state, selected input device, and Deepgram key/project access. |
| A reply is visible but inaudible | Check speaker/headset output, browser audio permissions, and Hume TTS voice/access. |
| WebRTC fails to connect | Confirm both loopback servers are running. Check VPN/firewall interference; media connectivity is separate from loading the page. |
| Session ends after silence or a long conversation | Start a new session; idle and maximum-duration limits bound abandoned provider usage. |

Provider failures now identify the affected service and category in both the app and terminal, for example `[PIPECAT:SAMBANOVA:QUOTA]`. The system prompt uses Pipecat's current `system_instruction` setting, removing the deprecated initial system-message warning. After code or environment changes, end the session, press **Ctrl+C** in the Python terminal, rerun `npm run dev:pipecat`, and refresh the app. The Python server must remain running; a return to the shell prompt means it stopped.

## Hosting and kickoff migration

The supplied setup is local only. Keep both servers bound to loopback. Public deployment requires a persistent Python backend, private access controls, HTTPS, and compatible signaling/media connectivity; a static host cannot run the voice pipeline. Choose a supported transport/relay arrangement and test at the venue before exposing it. No public host or paid relay was provisioned.

1. Obtain the organizer's real repository URL and record reuse rules in [event-brief.md](event-brief.md). Preserve this practice code's provenance and clone the starter separately.
2. Read its instructions, `AGENTS.md`, lockfile, `.env.example`, and deployment model. Record its initial commit before changing code.
3. Inventory its STT, LLM, TTS, transport, audio formats, environment names, endpoints, and model/voice IDs. Practice defaults are not event requirements.
4. Configure its credentials and install its locked dependencies. Run the starter unchanged before porting permitted practice code.
5. Complete a headset conversation and capture sanitized evidence that the assigned SambaNova endpoint was used. Verify pauses, interruptions, End, and reconnect.
6. Port the agreed feature after baseline success and reuse permission. Repeat voice/failure checks and record start/stop instructions, commit, URL, and latency in [readiness.md](readiness.md).
