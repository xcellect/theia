# Research Orb

A local voice research assistant built on the **Gradium + General Compute** starter stack. Speak or type a question, watch Jev interpret it, and follow paper discovery, PDF preparation and agent findings as they stream into a cited Markdown report.

Conversations persist across restarts. Ask follow-ups about individual papers, compare findings, reopen a report to restore its analysis panels, inspect Markdown source excerpts, export reports or delete a conversation.

## Stack

| Component | Role |
| --- | --- |
| Next.js + React + TypeScript | Glowing orb, conversation history, live analysis and report UI. |
| Python FastAPI + Pipecat | Research orchestration, WebRTC voice transport and streamed events. |
| Gradium | Streaming speech recognition and spoken responses. |
| General Compute | Voice replies, a reader agent per paper and final research reports. |
| Jev / TypeSafe AI | Live intent previews, request routing, paper selection and report evidence checks. |
| Exa | Paper search, source-text extraction and associated code discovery. |
| Paper2Agent → Paper2Skill | Local PDF conversion into reading packages; no separate PDF-service API key. |
| SQLite + files | Session memory, papers, cited excerpts, reports and replayable events. |

Jev selects **up to five relevant papers**, or one specific paper when requested. Up to two readers run concurrently. Paper2Agent prepares PDF evidence; General Compute agents analyze it.

## Quick setup

Prerequisites: **Node.js 20.9+**, npm, **Python 3.12**, **uv** and Git.

Run from this repository's root (`voice-ai-hackathon/`):

```bash
# Use the sibling Paper2Agent checkout, or clone it if absent.
test -d ../Paper2Agent || git clone https://github.com/jmiao24/Paper2Agent.git ../Paper2Agent

cd practice
npm ci
test -f .env.local || cp .env.example .env.local
npm run setup:pipecat
```

`setup:pipecat` installs the locked Python dependencies, including PDF libraries. If Paper2Agent is elsewhere, set `PAPER2AGENT_ROOT` to its absolute checkout path instead of cloning another copy.

Edit **`practice/.env.local`**, preserving existing values:

```dotenv
GENERALCOMPUTE_API_KEY=your_general_compute_key
GENERALCOMPUTE_MODEL=your_exact_available_model_id
GRADIUM_API_KEY=your_gradium_key
GRADIUM_VOICE_ID=your_gradium_voice_id
TYPESAFE_API_KEY=your_typesafe_key
EXA_API_KEY=your_exa_key

# Optional defaults:
GENERALCOMPUTE_BASE_URL=https://api.generalcompute.com/v1
GRADIUM_REGION=auto
TYPESAFE_MODEL=jev-latest
# PAPER2AGENT_ROOT=/absolute/path/to/Paper2Agent
```

Use a model ID available to your General Compute account and a Gradium voice ID. Typed research needs General Compute and TypeSafe; discovery also needs Exa. Gradium enables voice. Keys stay on the server in the ignored environment file.

## Start two servers

Run both commands from **`voice-ai-hackathon/practice/`**, in separate terminals:

```bash
# Terminal 1 — webapp
npm run dev -- --port 3000
```

```bash
# Terminal 2 — Pipecat/research backend
npm run dev:pipecat
```

Open **http://127.0.0.1:3000/**. The backend listens on **127.0.0.1:7860**; both processes must stay running. `/research` opens the same workspace; `/practice` retains the optional starter voice playground.

End voice before stopping either process with **Ctrl+C**. Restart Pipecat after Python code or environment changes. Frontend UI edits reload automatically during development.

## Try the demo

1. Keep **Search for papers** and **Prepare full papers** enabled. Ask: “Find three relevant papers on sliding-window attention and compare their methods.”
2. Watch Jev selection, Exa discovery, per-paper preparation, streamed findings and the cited report. Open a citation to inspect its source.
3. Select a saved paper and ask “Explain this paper's limitations,” or name the paper directly. Click **Start voice** and allow microphone access to speak instead.
4. Refresh to recover this tab's conversation. Use **Resume a saved conversation** for older work; click a report to restore its analysis. **New research** starts an empty conversation.

## Check setup

From `practice/`:

```bash
npm run check:config -- gradium  # Voice settings only; no provider requests.
curl --fail http://127.0.0.1:3000/api/research/health
curl --fail http://127.0.0.1:3000/api/research/voice/health
npm run smoke:gradium           # Optional real STT/LLM/TTS checks; uses provider credits.
```

Health reports missing research settings, Exa readiness and PDF-worker availability. If the backend is offline, start terminal 2. If PDF preparation is unavailable, check `PAPER2AGENT_ROOT` and rerun `setup:pipecat`. For provider/model/voice failures, check the corresponding settings and restart Pipecat. Existing terminal environment variables override `.env.local`.

## Storage and limits

- Workspaces persist in **`pipecat-readiness/.data/research/`** (SQLite and session files); override with `RESEARCH_WORKSPACE_ROOT`. Shared PDF cache: **`pipecat-readiness/.cache/paper2agent/`**. Conversation deletion removes its workspace while retaining the shared cache.
- PDF preparation supports resolved arXiv papers, including arXiv DOI and ar5iv links, up to **20 MB / 60 pages** each. Drafts are unreviewed. Missing PDFs are reported explicitly; eligible Exa excerpts can still supply evidence.
- Repository discovery, pinned checkout and compute inspection work. Scientific experiments and generated Paper2MCP tools await an isolated executor.
- This is a **local, single-user demo**; public hosting and multi-user authentication remain future work.

Code: [frontend](practice/), [voice/research backend](pipecat-readiness/), [environment template](practice/.env.example).
