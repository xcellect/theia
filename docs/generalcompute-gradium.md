# General Compute and Gradium voice setup

The third browser voice route keeps Pipecat and Small WebRTC and uses **Gradium speech-to-text → General Compute reply generation → Gradium text-to-speech**. It shares the local Python server on port 7860 with the SambaNova/Hume modular route. Hume EVI remains a separate selectable mode.

Provider documentation and the public General Compute model catalog were checked on September 19, 2026. Public documentation does not establish access or credit for your account. Record live provider and headset results separately in [readiness.md](readiness.md).

## 1. Get the General Compute key

1. Open the [General Compute dashboard](https://app.generalcompute.com/dashboard) and sign in or create your account.
2. Follow **Developers → API keys**, generate a key, and copy it immediately. General Compute's [key guide](https://docs.generalcompute.com/api-keys) says it will not be shown again.
3. Save that value as `GENERALCOMPUTE_API_KEY` in the existing ignored `practice/.env.local` file. Use a local editor; do not paste it into chat or browser-public variables.
4. Check your dashboard's balance, billing access, and usage limits. Use any event credits supplied to your account. The [plan documentation](https://docs.generalcompute.com/rate-limits) describes pay-as-you-go and paid tiers, but promotional credit offers differ between public pages; use the balance actually shown in your account.

The signed-in dashboard could not be inspected through the documentation reader or the requested `https://r.jina.ai/` fallback. The menu path above comes from the official key guide, rather than an observed account session.

## 2. Choose an available General Compute model

Set `GENERALCOMPUTE_MODEL` to an exact API ID. The public catalog returned these IDs when checked:

```text
gpt-oss-120b
deepseek-v3.1
deepseek-v3.2
gemma-4-31B-it
minimax-m2.7
```

For initial conversation practice, `minimax-m2.7` is a reasonable explicit starting choice: General Compute currently recommends it for general chat and uses it in the [quickstart](https://docs.generalcompute.com/quickstart). Confirm that it is available to your account. The application requires you to set a model rather than silently selecting one. [Models and pricing](https://docs.generalcompute.com/models).

You can refresh the public model list without a key:

```sh
curl --fail --silent --show-error https://api.generalcompute.com/v1/public/models
```

Copy an exact `id` from that response. A public listing confirms a model is advertised; a successful authenticated inference check confirms your account can call it. Older General Compute blog examples use model names that no longer appear in this catalog.

Keep the optional base URL at **`https://api.generalcompute.com/v1`**. The OpenAI-compatible client adds `/chat/completions`; do not add that suffix to `GENERALCOMPUTE_BASE_URL`. Authentication uses a Bearer key, and replies support normal streamed `choices[].delta.content`. [Official API key and URL examples](https://docs.generalcompute.com/api-keys).

General Compute describes DeepSeek V3.1/V3.2 as reasoning models with more thinking time. These can be less suitable for a first conversational latency check. The inspected [API schema](https://docs.generalcompute.com/api-reference/openapi.json) documents `max_tokens` and streaming but no portable `reasoning_effort`, `enable_thinking`, or reasoning-budget control. Do not assume another provider's reasoning flags work here. [Capability notes](https://docs.generalcompute.com/features).

## 3. Get the Gradium key and voice ID

1. Open [Gradium Studio](https://studio.gradium.ai/) and sign in or create an account.
2. Generate an API key from your account dashboard and save it as `GRADIUM_API_KEY`. The same key authenticates the STT and TTS services. Pipecat's [Gradium integration guide](https://docs.pipecat.ai/api-reference/server/services/tts/gradium) identifies the dashboard as the key source; the signed-in menu labels could not be verified through the reader or Jina fallback.
3. Open Gradium's [flagship voice library](https://docs.gradium.ai/guides/voices/flagship-voices). Choose a language and voice, preview it through the linked Studio control, and use **Copy voice ID**. Put that identifier in `GRADIUM_VOICE_ID`. Voice cloning is optional; a catalog voice is sufficient.
4. For a concrete English example, the current library lists **Russell** as `_6Aslh2DxfmnRLmP`. Copy your selected voice's exact ID, including any leading underscore. A Gradium voice ID is neither a Hume voice UUID nor an EVI configuration ID.
5. Check your Gradium account balance before starting speech sessions. Gradium's [credit API](https://docs.gradium.ai/api-reference/endpoint/get-credits) returns the authenticated subscription's remaining credits and plan information; an API key by itself does not prove available usage.

If you need to inspect voices programmatically, the official [Get Voices API](https://docs.gradium.ai/api-reference/endpoint/get-voices) uses `GET https://api.gradium.ai/api/voices/?include_catalog=true` with an `x-api-key` header. Copy the selected response object's `uid`. The catalog flag matters: `include_catalog` defaults to false, so a new account can otherwise appear to have no voices. Do not print or share your key while making the request.

The public voice page's text extraction omitted its interactive table. Its official Markdown source was read to verify the copy control and example ID; Jina did not expose the signed-in Studio.

## 4. Add the four values to the shared environment file

Preserve the existing EVI and SambaNova route settings in `practice/.env.local`, and add:

```dotenv
GENERALCOMPUTE_API_KEY=your_general_compute_key
GENERALCOMPUTE_MODEL=minimax-m2.7
GRADIUM_API_KEY=your_gradium_key
GRADIUM_VOICE_ID=your_selected_gradium_voice_id

# Optional settings:
GENERALCOMPUTE_BASE_URL=https://api.generalcompute.com/v1
GRADIUM_REGION=auto
PROVIDER_TIMEOUT_MS=60000
```

Replace placeholder values. `minimax-m2.7` is an explicit example, not an account-access guarantee. This route does not require Deepgram, SambaNova, or Hume credentials; those remain associated with the other modes. Both local servers use the same practice environment file, and existing shell exports take precedence over file values. Restart the Python process after editing it.

`GRADIUM_REGION` accepts `auto`, `us`, or `eu`. The default `auto` uses `api.gradium.ai`, which routes to a nearby cluster. The other choices use the regional hosts. A regional hostname alone does not establish a data-residency guarantee; Gradium's [region guide](https://docs.gradium.ai/guides/data-residency) explains the account-level enrollment needed for that guarantee.

## 5. Start and check the route

From `practice/`, keep the frontend running in one terminal:

```sh
npm run dev
```

In a second terminal, also from `practice/`, install the updated locked Python dependencies and start the backend:

```sh
npm run setup:pipecat
npm run dev:pipecat
```

The frontend is at **http://127.0.0.1:3000** and the shared Pipecat backend listens on **127.0.0.1:7860**. Do not start a second Python backend for this route. Open the browser, end any existing voice session, choose **Gradium + General Compute**, check setup, and start voice. Allow microphone access and speak first. End the session before switching routes or stopping either server with **Ctrl+C**.

To check the external services before a browser conversation, run this from `practice/` after confirming credits:

```sh
npm run smoke:gradium
```

These are real provider checks and can consume usage. For a narrower check, select one service:

```sh
npm run smoke:gradium -- --provider generalcompute
npm run smoke:gradium -- --provider gradium-stt
npm run smoke:gradium -- --provider gradium-tts
```

The provider probes do not establish working browser microphone capture, intelligible transcription of your speech, playback, or interruption. Verify those with three spoken turns, mute/unmute, an interruption, End, and reconnect. Confirm the browser microphone indicator turns off after End. The local transport needs no Pipecat Cloud or Daily account; Gradium and General Compute still require Internet access.

For one integrated synthetic voice turn, keep both servers running, end any browser voice session, and run `npm run smoke:gradium:voice`. It generates a short spoken test phrase, sends it through the web app's WebRTC signaling path, and checks the user transcript, reply text, returned audio, and cleanup. This uses real provider credits and opens local media sockets. It does not record your microphone or play audio through your speakers, so headset acceptance remains separate.

The STT probe sends `pcm_16000` audio. Gradium currently reports 24 kHz in its accepted setup metadata; the probe records that separately rather than treating it as a rejected input format. The pipeline continues to send 16 kHz input, matching the explicit format declaration and Pipecat's native integration.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing configuration | Enter the named variables in `practice/.env.local`, restart Python, then check setup again. |
| Provider authentication/credit error | Verify the key and balance in the matching provider's account. A working older route does not validate these new keys. |
| Model unavailable | Refresh the public catalog, check your General Compute account, and copy the exact model ID. |
| No user transcript | Check the selected microphone, mute state, browser permission, and Gradium STT probe. |
| Reply text appears without audio | Check speaker output and the Gradium TTS probe; verify `GRADIUM_VOICE_ID`. |
| Reply is slow or absent after a recognized turn | Check the General Compute probe, account limits, model choice, and provider deadline. |
| Backend unavailable | Keep `npm run dev:pipecat` running and use the existing loopback ports. |

The route is local practice. It does not provision hosting, guarantee account credits, or replace the organizer's unknown event starter. Use [Pipecat migration notes](pipecat.md#hosting-and-kickoff-migration) before transferring this work into the event project.
