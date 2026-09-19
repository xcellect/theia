# Voice AI hackathon practice

This workspace implements the **preparation** checklist in [voice-ai-hackathon-agent-checklist.md](voice-ai-hackathon-agent-checklist.md). It is not the official event starter or a completed hackathon submission. Initial preparation was recorded on September 18, 2026; the third provider stack was added on September 19. Confirm reuse rules before porting any code.

The browser offers three voice modes:

- **Hume EVI** is the default. It uses Hume's speech-to-speech service, server-issued temporary tokens, connection controls, and a transcript. The user has reported this route working.
- **Pipecat** connects the browser over Small WebRTC to a local Python pipeline: **Deepgram speech recognition → SambaNova replies → Hume text-to-speech**. The backend lives in `pipecat-readiness/` and requires a second running process.
- **Gradium + General Compute** uses **Gradium speech recognition → General Compute replies → Gradium text-to-speech**, sharing that Pipecat backend. It uses its own two API keys, model, and voice; no Hume, Deepgram, or SambaNova credentials are needed for this route.

`practice/scripts/sambanova-smoke.mjs` separately checks text inference from the command line; it is not the browser conversation. The sample transcript and fake inference are labeled **DEMO DATA** and make no provider calls.

Each modular route needs valid provider credentials, available credit, a usable model/voice, and a human headset check before claiming a working live demo. See [General Compute + Gradium setup](docs/generalcompute-gradium.md) for the new stack, [original Pipecat setup](docs/pipecat.md), [EVI controls](docs/voice.md), and [readiness evidence](docs/readiness.md). Hosting, reuse rules, and the official starter remain separate decisions.

## Install

Run from this workspace. The tested runtime is Node **23.11.0**, npm **10.9.2**, Python **3.12.10**, and uv **0.5.5**. Next.js requires Node >=20.9; `.node-version` records the locally tested version, not an event requirement. Use the event starter's own pins at kickoff.

```sh
cd practice
npm ci
cp -n .env.example .env.local
```

Edit `practice/.env.local` in a local editor; do not send credentials in chat. Existing shell variables take precedence, then `.env.local`, then `.env`. Next.js loads environment files for its server; CLI scripts explicitly load the practice directory's files regardless of the terminal's current directory. `.gitignore` excludes real environment files and includes the example.

| Route | Required variables | Optional settings |
| --- | --- | --- |
| Hume EVI | `HUME_API_KEY`, `HUME_SECRET_KEY`, `HUME_CONFIG_ID` | `HUME_CONFIG_VERSION` to pin a version; `PROVIDER_TIMEOUT_MS` |
| Pipecat voice | `DEEPGRAM_API_KEY`, `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL`, `HUME_API_KEY`, `HUME_VOICE_ID` | `DEEPGRAM_MODEL` (default `nova-3-general`), `SAMBANOVA_BASE_URL` (default `https://api.sambanova.ai/v1`), `PROVIDER_TIMEOUT_MS` (default `60000` in Python) |
| Gradium + General Compute | `GENERALCOMPUTE_API_KEY`, `GENERALCOMPUTE_MODEL`, `GRADIUM_API_KEY`, `GRADIUM_VOICE_ID` | `GENERALCOMPUTE_BASE_URL` (default `https://api.generalcompute.com/v1`), `GRADIUM_REGION` (`auto`, `us`, `eu`; default `auto`), `PROVIDER_TIMEOUT_MS` (default `60000`) |
| Real SambaNova CLI | `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL` | `SAMBANOVA_BASE_URL` (practice default `https://api.sambanova.ai/v1`), `PROVIDER_TIMEOUT_MS` |
| Fake transcript/inference | None | Never proves provider access or audio |
| Pipecat import/offline checks | None | Do not establish provider access or microphone/audio behavior |

`HUME_VOICE_ID` is a TTS voice UUID for Pipecat; it is different from `HUME_CONFIG_ID`. Pipecat reuses `HUME_API_KEY` and does not need `HUME_SECRET_KEY` or an EVI configuration. Keep the existing EVI variables to use both modes. No Pipecat Cloud, Daily, OpenAI, or Cartesia account is required for this local pipeline. Follow the [step-by-step key setup](docs/pipecat.md#configure-the-five-required-values).

`CLM_ENDPOINT_URL` and `CLM_AUTH_SECRET` are reserved for an EVI custom-language-model bridge that is **not implemented**. `DEPLOYMENT_URL` only adds an authorized host to the connectivity probe; hosted token issuance also requires `APP_ORIGIN` set to that app's exact HTTPS origin (for example `https://your-authorized-host.example`). Local practice does not need `APP_ORIGIN`. No provider key belongs in a browser-public environment variable.

## Run and stop

From `practice/`:

```sh
npm run check:config -- evi
npm run dev
```

Open **http://127.0.0.1:3000**. In **Hume EVI**, use **Prepare session**, then **Start voice**; the second click starts browser audio with a fresh user gesture. Allow the microphone, speak three turns, interrupt, mute/unmute, then **End**. Each new preparation requests a fresh token. Without credentials, use the explicitly labeled transcript demo; Prepare session reports missing variable names. Stop the server with **Ctrl+C** after ending voice. No background daemon is required.

To use **Pipecat**, keep that frontend running. In a second terminal, from `practice/`:

```sh
npm run setup:pipecat
npm run dev:pipecat
```

`setup:pipecat` installs the locked Python dependencies with `uv sync --frozen`; it is needed once and after dependency changes. `dev:pipecat` keeps the backend running at **http://127.0.0.1:7860**. In the browser choose **Modular Pipecat**, use **Check setup again**, select **Start Pipecat voice**, and speak. Deepgram supplies the speech-to-text service. Both servers read the same `practice/.env.local`; restart the Python process after changing that file, and restart Next.js for EVI environment changes. End the browser session before changing modes or stopping both terminals with **Ctrl+C**. See [Pipecat setup](docs/pipecat.md) for keys, troubleshooting, and human verification.

For the third route, configure its four values following [the new setup guide](docs/generalcompute-gradium.md), then choose **Gradium + General Compute** in the browser. Use the same running Next.js and Python processes. `npm run check:config -- gradium` validates the local settings without a provider call; `npm run smoke:gradium` makes small real requests to check the three stages. The server permits one modular voice session at a time across both routes.

Production run path (same directory):

```sh
npm run build
npm start
```

`npm start` uses port 3000 on loopback. To choose another local port, use `npm start -- --port 3001`. The frontend calls same-origin `/api/hume/token`; the browser then connects directly to Hume's WebSocket service. `/api/health` reports app availability/config presence, never verifies credentials or makes paid requests. There is no local Python server to start for EVI.

## Verify

From `practice/`:

```sh
npm test
npm run typecheck
npm run check:secrets
npm run check:network
npm run smoke:fake -- --tools
curl --fail http://127.0.0.1:3000/api/health
# After building: starts an isolated local test server on port 3100, then stops it.
npm run verify:http
```

`check:network` sends unauthenticated HEAD requests; HTTP 404/405 still demonstrate domain reachability. The intended host remains BLOCKED unless configured. A successful build or fake smoke does not satisfy real-provider or microphone acceptance.

After verifying account credit/quota and configuring the **exact available model ID**, run:

```sh
npm run check:config -- sambanova
npm run smoke:sambanova
# Optional additional smoke: 4 requests total, including a local-only tool round trip.
npm run smoke:sambanova -- --tools
```

The ordinary real smoke makes **two requests**. It prints text as it arrives and reports first nonempty text latency separately from completion time. This is a scripted CLI check, not an interactive chat or a voice session. The optional tool smoke adds two requests, validates arguments, mutates only an in-memory tutorial task, and prints the actual structured result. No retries run automatically. Ctrl+C cancels; the configured timeout bounds each request. Check credit first. [Inference details](docs/inference.md).

Pipecat install and offline checks, from `practice/`:

```sh
npm run setup:pipecat
npm run check:pipecat
npm run test:pipecat
# Local UDP sockets; synthetic audio, no microphone or provider calls.
npm run smoke:transport
```

These commands exit after completion and do not start a conversation. The Python package is pinned to `pipecat-ai` **1.11.0**, with Deepgram, Gradium, Hume, SambaNova, Small WebRTC, runner, CLI, and Silero extras; frontend clients are pinned in `practice/package-lock.json`. EVI and both modular pipelines need Internet access to their providers. Offline checks cannot prove audible output or credential validity; record live results in [readiness.md](docs/readiness.md).

After configuring all five Pipecat variables, `npm run smoke:providers` makes small real requests to isolate provider failures without microphone capture. It checks a Deepgram connection, a short SambaNova response, and Hume synthesis; provider usage may incur charges. To recheck only SambaNova after restoring credits, use `npm run smoke:providers -- --provider sambanova`. HTTP 402 is a billing/credit rejection; increasing the timeout does not resolve it. See [Pipecat troubleshooting](docs/pipecat.md#troubleshooting).

Copy `docs/latency.example.json` to a private observation file and record ten aligned `userSpeechEndMs` / `assistantAudioStartMs` pairs with route, exact model, and network. Then run `npm run measure:latency -- /path/to/observed-turns.json`. For transcript-only timing, set `measurement` to `transcript-proxy` and use `assistantTranscriptMs`; the report labels that limitation. The empty template intentionally fails rather than inventing measurements.

## Deployment and rollback

Local build/start is the available rehearsal path. **Hosted rehearsal is BLOCKED:** no authorized host, configured hosted secrets, or approved budget has been supplied. No site was published. The Hume official Next.js example targets a Node-capable host; this project retains actual Next.js rather than silently changing frameworks. Sites hosting was assessed but this Node build is not its required Worker bundle. See [deployment runbook](docs/deployment.md) before selecting the event's supported host.

The token endpoint is a local practice endpoint: same-origin checks prevent cross-site browser use but are not user authentication. Keep both servers on their loopback defaults. An authorized hosted rehearsal needs private host access on **all routes**, HTTPS, server-side secrets, and a fresh audio test from that URL. Pipecat also needs a persistent Python process and a supported public signaling/media transport. A static-only host cannot serve either backend. No public deployment is included in the local setup.

The source snapshot `artifacts/local/practice-baseline.tar.gz` and `artifacts/source-manifest.sha256` identify the locally verified baseline without requiring Git identity. They omit secret files, dependency directories, build output, and observations. Regenerate them with `python3 scripts/record-baseline.py` only after verifying new changes. To restore without overwriting current work, from workspace root:

```sh
mkdir -p /tmp/voice-ai-practice-restore
tar -xzf artifacts/local/practice-baseline.tar.gz -C /tmp/voice-ai-practice-restore
cd /tmp/voice-ai-practice-restore/practice
npm ci
cp -n .env.example .env.local
# Configure secrets again; the snapshot intentionally contains none.
npm run build
npm start
```

Use a new empty restore directory if that path already contains work. Reset the transcript through the app's reset control or refresh after ending voice. The fake/local tool board resets whenever its CLI process exits. A backup audio/video recording has **not** been created; [demo.md](docs/demo.md) records the intended location and human rehearsal steps.
