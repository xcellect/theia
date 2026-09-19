# Browser voice practice

This is reusable practice work created before event reuse rules are known. The app offers **Hume EVI** (default), **Modular Pipecat**, and **Gradium + General Compute**. Hume EVI uses Hume's speech-to-speech service. The two modular modes share a local Pipecat backend: Deepgram → SambaNova → Hume TTS, or Gradium STT → General Compute → Gradium TTS. The user has reported EVI working; modular conversations still need real-provider and human headset verification.

The standalone SambaNova CLI is a separate, scripted text check. Its output is not connected to either browser transcript, and its local tool fixture is not exposed by the voice pipeline. This practice application is not the official event starter.

## Choose and start a mode

Follow the root [README](../README.md) to install and start the frontend with `npm run dev` from `practice/`. Open **http://127.0.0.1:3000**. End an active session before switching modes so only one mode uses the microphone.

| Mode | Values in `practice/.env.local` | Running processes |
| --- | --- | --- |
| Hume EVI | `HUME_API_KEY`, `HUME_SECRET_KEY`, `HUME_CONFIG_ID`; optional `HUME_CONFIG_VERSION` | Next.js frontend/server on 127.0.0.1:3000 |
| Pipecat | `DEEPGRAM_API_KEY`, `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL`, `HUME_API_KEY`, `HUME_VOICE_ID` | Next.js plus Python on 127.0.0.1:7860 |
| Gradium + General Compute | `GENERALCOMPUTE_API_KEY`, `GENERALCOMPUTE_MODEL`, `GRADIUM_API_KEY`, `GRADIUM_VOICE_ID` | Same Next.js and Python processes |

For Pipecat, run `npm run setup:pipecat` once, then keep `npm run dev:pipecat` running in a second terminal from `practice/`. Follow [Pipecat setup](pipecat.md) for API keys, credits, exact model/voice IDs, and troubleshooting. It reads the same environment file; restart Python after edits. The Hume TTS voice UUID is different from the EVI config ID, and Pipecat does not need the EVI secret/config. Local Small WebRTC requires no additional transport account.

Do not put credentials in chat, screenshots, or browser-public environment variables. Restart Next.js after changing its EVI environment. The UI reports configuration presence; a successful preparation does not certify live provider access or account credit.

## Hume EVI controls

1. Choose **Hume EVI**. Select **Prepare session** to request a temporary token from the local server.
2. Select **Start voice** to connect, then allow microphone access. These are separate clicks so waiting for the token cannot consume the browser user gesture needed to start audio. The token is held only in component memory and discarded if unused for 60 seconds.
3. Speak. The transcript shows both speakers. Use **Mute microphone** / **Unmute microphone** to control input.
4. Select **End session**. It remains disabled while cleanup finishes. If you selected End while a microphone permission dialog was open, dismiss that dialog to let pending browser work settle.
5. Prepare a new session to reconnect with a fresh token. A new preparation clears the previous transcript. **Clear** removes the transcript when idle.

**Preview a sample transcript** is a deterministic text-only preview marked **DEMO DATA**. It does not request microphone access, generate speech, or call a provider. **Practice setup** shows credential presence and the requested configuration ID/version after preparation; it does not claim a successful provider test. A live session also displays the chat ID received from the SDK. That metadata does not echo the configuration version, so pin the version and verify it in the Hume control plane during the real check.

## Pipecat controls

1. Keep both local servers running and select **Modular Pipecat**.
2. Select **Check setup again**. If the backend is unavailable, start `npm run dev:pipecat`; if it lists missing variables, update `practice/.env.local` and restart Python.
3. Select **Start Pipecat voice** and allow the microphone. Speak first; Deepgram transcribes your turn, SambaNova generates the reply, and Hume synthesizes it. The transcript shows the two speakers.
4. Use mute/unmute, interrupt a spoken reply, then select End. The client disconnects its transport and the backend tears down the session. Wait for cleanup before reconnecting or changing modes.
5. Start a fresh session to retry after a provider failure. Check the selected providers' credentials, quota, exact SambaNova model, and Hume TTS voice when errors persist.

The provider timeout defaults to 60 seconds. The Python session also ends after 120 seconds of inactivity or 600 seconds total. A new session begins with fresh context. There is no automatic fallback to EVI or demo data if a provider fails. End the session before stopping the local servers with **Ctrl+C**.

## Gradium + General Compute controls

Configure the four values using [the setup guide](generalcompute-gradium.md). Keep the existing frontend and Python backend running, end any active session, and select **Gradium + General Compute**. Check setup, select **Start Gradium voice**, allow microphone access, and speak first. Gradium supplies transcription and speech; General Compute generates the response. Mute, End, transcript scrolling, and reconnect behave like the other modular mode. End releases microphone capture before route switching becomes available. The same Gradium key serves both speech stages, and the new route does not require any of the older providers' keys.

## Hume SDK source decisions

Implemented against the installed `@humeai/voice-react` 0.3.0-beta.6 and `hume` 0.16.1 types and source, with the [official Next.js guide](https://dev.hume.ai/docs/speech-to-speech-evi/quickstart/nextjs), [actual Messages component](https://github.com/HumeAI/hume-api-examples/blob/main/evi/evi-next-js-app-router-quickstart/components/Messages.tsx), and [React SDK](https://github.com/HumeAI/hume-react-sdk) as references.

- Browser code mounts `VoiceProvider` and calls `useVoice().connect` from the Start button. `connect` receives only the temporary access token plus the server-selected configuration. No credentials are embedded in the page or client environment.
- The positive transcript filter includes `user_message` and `assistant_message`. The guide's displayed filter was inverted at inspection; the actual example includes those events. SDK history replaces interim user events and associates assistant transcripts with playback. The helper deduplicates assistant IDs and user utterance start times while preserving repeated phrases in separate turns.
- SDK `disconnect()` stops captured tracks, recorder, socket, player queue, and shared audio context. It cannot cancel a pending native microphone permission dialog. End invalidates the token request, serializes new attempts behind cleanup, and repeats disconnect after a pending microphone/player initialization settles, releasing a stream that arrived late. Navigation/unmount also initiates cleanup.
- A stale `closed` socket state from a previous session must not cancel a new microphone request. The controller only treats a close during connection as current after observing `connecting` or `open` for that attempt. Once the socket has started, explicit disconnect aborts it; cleanup does not wait indefinitely for an SDK connection promise after a server close.
- The SDK routes some server JSON error messages to `VoiceProvider.onError` without setting `useVoice().error`. Both paths are handled. The UI uses fixed, actionable error categories; it neither renders nor logs raw SDK errors. Preparation times out after 15 seconds, connection after 30 seconds, and there are no automatic reconnect retries.
- A previous failure is cleared by the next preparation. SDK error state is reset by its next `connect` call. The SDK dependency's nested React 18 copies are resolved by the coordinator's React overrides; one React runtime is required.

## Evidence and remaining checks

The EVI route uses `@humeai/voice-react` **0.3.0-beta.6** and `hume` **0.16.1**. Pipecat uses `@pipecat-ai/client-js` **1.13.1** with `@pipecat-ai/small-webrtc-transport` **1.10.8** and Python `pipecat-ai` **1.11.0**. The client exchanges signaling/session information with the local backend; provider keys remain in the server processes.

Use `npm test`, `npm run typecheck`, and `npm run test:pipecat` from `practice/` for the relevant automated checks. See [readiness.md](readiness.md) for observed results and browser-test limitations. Offline tests do not emulate or certify real audio. The user's working EVI report does not establish Deepgram, SambaNova, or Hume TTS behavior for the modular mode.

Record human checks separately for each mode in `docs/readiness.md`: three intelligible turns, both transcripts, interruption stopping speech, mute/unmute, permission-denial recovery, offline recovery, End while preparing/connecting, microphone indicator off after End, repeated Prepare/Start/End without overlapping sessions, mode switching, and narrow-screen layout. For EVI, record the configuration/version. For Pipecat, record the Deepgram model, SambaNova endpoint/model, and Hume voice UUID. Public hosting and the official event starter remain separate work.
