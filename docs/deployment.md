# Deployment rehearsal runbook

Status: local install/build/start is verified in [readiness.md](readiness.md); hosted rehearsal is **BLOCKED**, owner: user + deployment lane. No authorized host, hosted URL, credentials, or budget was supplied. No paid resource or public endpoint was created. The organizer starter remains UNKNOWN.

## Practice components

| Component | Run / stop | Connectivity and secrets |
| --- | --- | --- |
| Next.js EVI practice | `cd practice && npm ci && npm run build && npm start`; Ctrl+C to stop | Loopback `127.0.0.1:3000`; same-origin token and health HTTP routes. Long-lived Hume credentials exist only in the Node server. |
| Browser EVI | Prepare session → Start voice → End | Microphone capture and audible playback on laptop; outbound Hume WebSocket. Temporary token only. HTTPS required away from localhost. |
| SambaNova CLI | `cd practice && npm run smoke:sambanova`; exits or Ctrl+C | Outbound HTTPS to configured endpoint; server-side key. Separate from EVI. |
| Pipecat backend | `cd practice && npm run setup:pipecat && npm run dev:pipecat`; Ctrl+C to stop | Persistent Python server on `127.0.0.1:7860`; Deepgram STT → SambaNova → Hume TTS. Reads `practice/.env.local`; Next.js proxies local signaling and health. |
| Browser Pipecat | Select Modular Pipecat → Start Pipecat voice → End | Small WebRTC carries audio/data directly to local Python. Requires both processes. No transport provider account/key. |

The optional custom-language-model bridge is not selected. There is no `/chat/completions` public backend for Hume to call, and no combined EVI→SambaNova proof.

## Hosted rehearsal once a host is authorized

1. Confirm the host supports the actual Next.js version and dynamic Node routes, private access covering frontend **and API paths**, HTTPS, and expected usage within authorized budget. Record its exact install/build/start commands, public URL, revision, and stop/rollback controls here. Do not publish the local token issuer openly.
2. Install with `npm ci`, build with `npm run build`; configure EVI's required server-side variables using the host secret manager. Set `APP_ORIGIN` to the exact authorized HTTPS origin (no path/query); the token route otherwise allows only localhost/loopback hostnames. Keep local files out of uploads. Pin the tested EVI config/version. Use the assigned event endpoint/model only when available.
3. If running as a generic Node service, use the host's required listen interface and port (for example `npx next start --hostname 0.0.0.0 --port 3000`, only behind the host's private access). The local `npm start` intentionally binds loopback. Verify the reverse proxy preserves request origin correctly and does not cache `/api/hume/token`.
4. Visit the protected HTTPS URL from the presentation laptop. Check `/api/health` and confirm the token response has `Cache-Control: no-store, private`. Inspect browser requests and bundles for long-lived credentials without copying tokens into reports.
5. Perform the entire [manual failure/audio matrix](demo.md) with the headset: permission denied/recovery, three turns, pauses, noise, interruption, mute, End, and Start again. Record observed config/chat identifiers where safe; never record tokens. Verify End stops the microphone indicator and provider activity.
6. Rehearse twice, capture ten aligned speech-to-playback measurements, record a truthful backup, and save the known-working deployed revision. Reset demo state and confirm rollback before feature freeze.

The [official Hume Next.js quickstart](https://dev.hume.ai/docs/speech-to-speech-evi/quickstart/nextjs) links a Next.js deployment starter. The Sites skills were evaluated, but this actual Next.js Node output is not Sites' required Cloudflare Worker `dist/server/index.js` bundle. No new deployment target or framework migration is assumed merely to publish practice code.

## Event-first Pipecat hosting

The practice pipeline has a concrete local run path above; its proxy and Python server intentionally accept local use only. Public deployment needs additional configuration and access controls. The official starter dictates the event deployment path: a persistent Python process plus its actual signaling/audio transport; a static frontend cannot run it. Inventory WebRTC/UDP/STUN/TURN or WebSocket needs, relay configuration, frontend backend URL, and stream timeouts. Test at the venue. Event ports, public URLs, and relay settings remain UNKNOWN until the starter is available. See [pipecat.md](pipecat.md).

Fallback: verified local practice commands, internet access for real APIs, or a clearly labeled recording **only after one exists**. Eligibility of any missing sponsor integration remains a host question. Fake transcripts and inference fixtures are for testing, not a working voice demo.
