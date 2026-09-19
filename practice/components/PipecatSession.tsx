"use client";

import Daily, { type DailyCall } from "@daily-co/daily-js";
import { LogLevel, PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { useCallback, useEffect, useRef, useState } from "react";
import { updatePipecatTranscript, type PipecatLine } from "./pipecat-transcript";
import { pipecatErrorMessage } from "./pipecat-errors.mjs";

type Phase = "idle" | "connecting" | "connected" | "stopping";
type Health = { configured: boolean; missing: string[]; activeSessions: number; configError?: string };
type Attempt = { client: PipecatClient; mediaOwner: DailyCall; promise: Promise<void>; cancelConnection: () => void };

const SESSION_VARIANTS = {
  pipecat: {
    label: "Modular Pipecat",
    eyebrow: "PIPECAT SESSION",
    startLabel: "Start Pipecat voice",
    readyLabel: "Ready to test Pipecat",
    healthEndpoint: "/api/pipecat/health",
    offerEndpoint: "/api/pipecat/offer",
    connectionFailure: "The Pipecat session could not start. Check the Python server, provider keys and credits, and the SambaNova model, then try again.",
    liveDescription: "Speak naturally. Deepgram transcribes, SambaNova replies, and Hume speaks.",
    privacy: "Audio goes to Deepgram; conversation text goes to SambaNova and Hume TTS.",
    stt: "Deepgram STT", sttKey: "DEEPGRAM_API_KEY",
    llm: "SambaNova", llmKey: "SAMBANOVA_API_KEY", llmModel: "SAMBANOVA_MODEL",
    tts: "Hume TTS", ttsKey: "HUME_API_KEY", voiceId: "HUME_VOICE_ID",
    setupNote: "This route uses a Hume TTS voice ID; your Hume EVI configuration remains separate.",
  },
  gradium: {
    label: "Gradium + General Compute",
    eyebrow: "GRADIUM SESSION",
    startLabel: "Start Gradium voice",
    readyLabel: "Ready to test Gradium",
    healthEndpoint: "/api/gradium/health",
    offerEndpoint: "/api/gradium/offer",
    connectionFailure: "The Gradium session could not start. Check the Python server, Gradium and General Compute keys and credits, and the General Compute model, then try again.",
    liveDescription: "Speak naturally. Gradium transcribes and speaks; General Compute generates the reply.",
    privacy: "Audio goes to Gradium; conversation text goes to General Compute and Gradium TTS.",
    stt: "Gradium STT", sttKey: "GRADIUM_API_KEY",
    llm: "General Compute", llmKey: "GENERALCOMPUTE_API_KEY", llmModel: "GENERALCOMPUTE_MODEL",
    tts: "Gradium TTS", ttsKey: "GRADIUM_API_KEY", voiceId: "GRADIUM_VOICE_ID",
    setupNote: "This route uses your Gradium API key for speech recognition and playback, plus General Compute for replies.",
  },
} as const;

function stopTracks(client: PipecatClient) {
  // SDK disconnect handles the transport. Stop any exposed tracks as well so
  // a late permission result cannot leave microphone capture running.
  try {
    const tracks = client.tracks();
    for (const track of Object.values(tracks.local)) track?.stop();
    for (const track of Object.values(tracks.bot ?? {})) track?.stop();
  } catch { /* A client that failed before device initialization has no tracks. */ }
}

export default function PipecatSession({ onBusyChange, variant = "pipecat" }: { onBusyChange?: (busy: boolean) => void; variant?: keyof typeof SESSION_VARIANTS }) {
  const settings = SESSION_VARIANTS[variant];
  const mounted = useRef(true);
  const generation = useRef(0);
  const phaseRef = useRef<Phase>("idle");
  const busyCallback = useRef(onBusyChange);
  busyCallback.current = onBusyChange;
  const attempt = useRef<Attempt | null>(null);
  const stopInFlight = useRef<Promise<void> | null>(null);
  const healthRequest = useRef<AbortController | null>(null);
  const healthGeneration = useRef(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const followTranscript = useRef(true);
  const [phase, setPhaseState] = useState<Phase>("idle");
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [healthProblem, setHealthProblem] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [lines, setLines] = useState<PipecatLine[]>([]);

  const setPhase = useCallback((value: Phase) => {
    phaseRef.current = value;
    if (mounted.current) {
      setPhaseState(value);
      busyCallback.current?.(value !== "idle");
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    const id = ++healthGeneration.current;
    healthRequest.current?.abort();
    const controller = new AbortController();
    healthRequest.current = controller;
    setChecking(true);
    setHealthProblem(null);
    const timeout = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch(settings.healthEndpoint, { cache: "no-store", signal: controller.signal });
      const data = await response.json();
      if (!mounted.current || healthGeneration.current !== id) return;
      if (!response.ok) {
        setHealth(null);
        setHealthProblem("Start the Pipecat server in a second terminal with npm run dev:pipecat, then check again.");
        return;
      }
      if (typeof data.configured !== "boolean" || !Array.isArray(data.missing)) throw new Error("Invalid health response");
      setHealth({ configured: data.configured, missing: data.missing.filter((name: unknown): name is string => typeof name === "string" && /^[A-Z][A-Z0-9_]{0,80}$/.test(name)), activeSessions: Number.isSafeInteger(data.activeSessions) ? data.activeSessions : 0, ...(typeof data.configError === "string" && { configError: data.configError }) });
    } catch {
      if (mounted.current && healthGeneration.current === id) {
        setHealth(null);
        setHealthProblem("Could not reach the Pipecat server. Run npm run dev:pipecat in a second terminal and check again.");
      }
    } finally {
      clearTimeout(timeout);
      if (healthRequest.current === controller) healthRequest.current = null;
      if (mounted.current && healthGeneration.current === id) setChecking(false);
    }
  }, [settings.healthEndpoint]);

  const end = useCallback((reason?: string): Promise<void> => {
    if (reason && mounted.current) setProblem(reason);
    if (stopInFlight.current) return stopInFlight.current;
    const id = ++generation.current;
    const pending = attempt.current;
    setPhase("stopping");
    const audio = audioRef.current;
    if (audio) { audio.pause(); audio.srcObject = null; }
    if (mounted.current) { setSpeaking(false); setAudioBlocked(false); }
    if (pending) { pending.cancelConnection(); stopTracks(pending.client); }
    const cleanup = async () => {
      let clean = true;
      if (pending) {
        try { await pending.client.disconnect(); } catch { clean = false; }
        // getUserMedia cannot be cancelled. Wait for permission to resolve,
        // then release anything that arrived after the first disconnect.
        await pending.promise.catch(() => undefined);
        stopTracks(pending.client);
        try { await pending.client.disconnect(); } catch { /* Explicit owner cleanup below also handles an absent peer. */ }
        // SmallWebRTC's default media manager uses a shared Daily call object.
        // Destroy the instance we created to remove its device listeners and
        // release capture even when cancellation happened before a peer existed.
        try { await pending.mediaOwner.destroy(); clean = true; } catch { clean = false; }
      }
      if (generation.current === id) {
        attempt.current = null;
        if (clean) {
          setPhase("idle");
          if (mounted.current) void refreshHealth();
        } else if (mounted.current) setProblem("Audio cleanup did not finish. Close this tab before starting another session.");
      }
    };
    const task = cleanup().finally(() => { if (stopInFlight.current === task) stopInFlight.current = null; });
    stopInFlight.current = task;
    return task;
  }, [refreshHealth, setPhase]);

  useEffect(() => {
    mounted.current = true;
    void refreshHealth();
    const onPageHide = () => { void end(); };
    window.addEventListener("pagehide", onPageHide);
    return () => {
      mounted.current = false;
      ++healthGeneration.current;
      healthRequest.current?.abort();
      window.removeEventListener("pagehide", onPageHide);
      void end();
    };
  }, [end, refreshHealth]);

  const start = () => {
    if (phaseRef.current !== "idle" || stopInFlight.current || !health?.configured || checking) return;
    const id = ++generation.current;
    const isCurrent = () => mounted.current && generation.current === id;
    setProblem(null);
    setLines([]);
    setMuted(false);
    setSpeaking(false);
    setAudioBlocked(false);
    setPhase("connecting");
    let userUtterance = 0;
    let anonymousSegment = 0;
    let connectTimeout: ReturnType<typeof setTimeout> | undefined;
    let mediaOwner: DailyCall | undefined;
    let client: PipecatClient;
    try {
      if (Daily.getCallInstance()) throw new Error("Previous media owner still active");
      mediaOwner = Daily.createCallObject();
      client = new PipecatClient({
      transport: new SmallWebRTCTransport({ iceServers: [], waitForICEGathering: true }),
      enableMic: true,
      enableCam: false,
      enableScreenShare: false,
      callbacks: {
        onBotReady: () => { if (isCurrent()) setPhase("connected"); },
        onDisconnected: () => { if (isCurrent()) void end("The session ended. Start a new session to reconnect."); },
        onTransportStateChanged: (state) => { if (isCurrent() && state === "error") void end(settings.connectionFailure); },
        onDeviceError: () => { if (isCurrent()) void end("The microphone could not start. Allow microphone access in your browser and check your input device."); },
        onError: (message) => { if (isCurrent()) void end(pipecatErrorMessage(message)); },
        onBotStartedSpeaking: () => { if (isCurrent()) setSpeaking(true); },
        onBotStoppedSpeaking: () => { if (isCurrent()) setSpeaking(false); },
        onTrackStarted: (track, participant) => {
          if (!isCurrent()) { track.stop(); return; }
          if (participant?.local || track.kind !== "audio") return;
          const audio = audioRef.current;
          if (!audio) return;
          audio.srcObject = new MediaStream([track]);
          void audio.play().then(() => { if (isCurrent()) setAudioBlocked(false); }).catch(() => { if (isCurrent()) setAudioBlocked(true); });
        },
        onTrackStopped: (track, participant) => {
          if (!isCurrent() || participant?.local || track.kind !== "audio") return;
          const audio = audioRef.current;
          if (audio?.srcObject instanceof MediaStream && audio.srcObject.getTracks().some((playing) => playing.id === track.id)) { audio.pause(); audio.srcObject = null; }
        },
        onUserTranscript: (data) => {
          if (!isCurrent() || !data.text.trim()) return;
          const event = { type: "user" as const, id: String(userUtterance), text: data.text, final: data.final };
          setLines((previous) => updatePipecatTranscript(previous, event));
          if (data.final) userUtterance += 1;
        },
        onBotOutput: (data) => {
          if (!isCurrent() || !data.text.trim() || data.aggregated_by === "word") return;
          const segment = data.segment_id ?? `fallback-${anonymousSegment++}`;
          setLines((previous) => updatePipecatTranscript(previous, { type: "bot", id: String(segment), text: data.text }));
        },
      },
      });
      client.setLogLevel(LogLevel.ERROR);
    } catch {
      setProblem("The browser audio client could not initialize. Check microphone support, then reload this tab and try again.");
      if (mediaOwner) {
        setPhase("stopping");
        void mediaOwner.destroy().then(() => { if (isCurrent()) setPhase("idle"); }).catch(() => { if (isCurrent()) setProblem("Audio cleanup did not finish. Close this tab before starting another session."); });
      } else setPhase("idle");
      return;
    }

    let finishAttempt!: () => void;
    let cancelConnection!: () => void;
    const pendingPromise = new Promise<void>((resolve) => { finishAttempt = resolve; });
    const cancelled = new Promise<void>((resolve) => { cancelConnection = resolve; });
    attempt.current = { client, mediaOwner, promise: pendingPromise, cancelConnection };

    // Begin device initialization on the Start gesture. Check the generation
    // before signaling so cancelling a permission prompt never starts a bot.
    const connect = async () => {
      try {
        await client.initDevices();
        if (!isCurrent()) return;
        const deadline = new Promise<never>((_, reject) => {
          connectTimeout = setTimeout(() => reject(new Error("Connection timeout")), 45_000);
        });
        const connecting = client.connect({ webrtcRequestParams: { endpoint: settings.offerEndpoint, timeout: 30_000 } });
        // If a transport finishes after cancellation, close its late result too.
        void connecting.then(() => { if (!isCurrent()) { stopTracks(client); void client.disconnect().catch(() => undefined); } }, () => undefined);
        await Promise.race([connecting, deadline, cancelled]);
        if (isCurrent()) setPhase("connected");
      } catch {
        if (isCurrent()) void end(settings.connectionFailure);
      } finally {
        if (connectTimeout) clearTimeout(connectTimeout);
      }
    };
    void connect().finally(finishAttempt);
  };

  const toggleMute = () => {
    const client = attempt.current?.client;
    if (!client || phaseRef.current !== "connected") return;
    try { client.enableMic(muted); setMuted(!muted); }
    catch { void end("The microphone could not be updated. Check your input device and start a new session."); }
  };

  const enablePlayback = () => {
    const audio = audioRef.current;
    if (!audio || phaseRef.current !== "connected") return;
    const id = generation.current;
    const isCurrent = () => mounted.current && generation.current === id && phaseRef.current === "connected";
    // Ending a session aborts pending play(). Its late rejection must not replace
    // the provider failure that caused the session to end.
    void audio.play()
      .then(() => { if (isCurrent()) setAudioBlocked(false); })
      .catch(() => { if (isCurrent()) setProblem("Audio playback is blocked. Check your browser sound permission and output device."); });
  };

  const lastText = lines.at(-1)?.text;
  useEffect(() => {
    const panel = transcriptRef.current;
    if (panel && followTranscript.current) panel.scrollTop = panel.scrollHeight;
  }, [lines.length, lastText]);

  const connected = phase === "connected";
  const active = phase !== "idle";
  const title = phase === "connecting" ? "Connecting the pipeline" : phase === "stopping" ? "Ending the session" : connected ? muted ? "Microphone muted" : speaking ? "Assistant is speaking" : "Listening to you" : health?.configured ? settings.readyLabel : "Set up the voice pipeline";
  const description = phase === "connecting" ? "Allow microphone access. Connecting to the local Pipecat server." : phase === "stopping" ? "Releasing audio. Dismiss any open microphone permission dialog to finish." : connected ? settings.liveDescription : "Start the Python server and check its configuration, then start your microphone.";

  return <>
    <audio ref={audioRef} autoPlay hidden />
    <div className="session-grid">
      <section className="voice-panel" aria-labelledby="pipecat-heading">
        <div className="panel-topline"><span className="eyebrow">{settings.eyebrow}</span><span className={`state-tag ${connected ? "is-connected" : ""}`}><span />{connected ? "CONNECTED" : phase === "connecting" ? "CONNECTING" : phase === "stopping" ? "ENDING" : "MIC OFF"}</span></div>
        <div className={`voice-orbit ${connected && !muted ? "orbit-active" : ""}`} aria-hidden="true"><div className="orbit-inner"><span /><span /><span /><span /><span /><span /><span /></div><span className="orbit-dot" /></div>
        <div className="session-copy" aria-live="polite" aria-atomic="true"><h2 id="pipecat-heading">{title}</h2><p>{description}</p></div>
        <div className="session-controls">
          {phase === "idle" && <button className="button button-primary" onClick={start} disabled={!health?.configured || checking}>{settings.startLabel} <span aria-hidden="true">↗</span></button>}
          {connected && <button className="button button-primary" onClick={toggleMute} aria-pressed={muted}>{muted ? "Unmute microphone" : "Mute microphone"}</button>}
          {(phase === "connecting" || phase === "stopping") && <button className="button button-primary" disabled><span className="spinner" aria-hidden="true" />{phase === "connecting" ? "Connecting…" : "Ending…"}</button>}
          {active && <button className="button button-secondary" onClick={() => void end()} disabled={phase === "stopping"}>End session</button>}
          {!active && <button className="button button-secondary" onClick={() => void refreshHealth()} disabled={checking}>{checking ? "Checking setup…" : "Check setup again"}</button>}
          {audioBlocked && connected && <button className="button button-secondary" onClick={enablePlayback}>Enable reply audio</button>}
        </div>
        <p className="session-fineprint">{connected ? settings.privacy : `Microphone access begins only after ${settings.startLabel}.`}</p>
        {problem && <div className="error-notice" role="alert"><strong>Session needs attention</strong><p>{problem}</p></div>}
        {healthProblem && <div className="error-notice" role="status"><strong>Pipecat server needed</strong><p>{healthProblem}</p></div>}
        {health && !health.configured && <div className="error-notice" role="status"><strong>Configuration needed</strong><p>{health.missing.length ? <>Add these variables to <code>practice/.env.local</code>: {health.missing.map((name, index) => <span key={name}>{index > 0 && ", "}<code>{name}</code></span>)}.</> : health.configError ?? "Check the Pipecat server configuration."} Restart the Python server, then check setup again.</p></div>}
      </section>

      <section className="transcript-panel" aria-labelledby="pipecat-transcript-heading">
        <div className="transcript-header"><div><p className="eyebrow">THE CONVERSATION</p><h2 id="pipecat-transcript-heading">Transcript <span>{String(lines.length).padStart(2, "0")}</span></h2></div><button className="text-button" disabled={active || lines.length === 0} onClick={() => setLines([])}>Clear</button></div>
        <div className="transcript-scroll" ref={transcriptRef} tabIndex={0} role="region" aria-label={`${settings.label} conversation transcript`} onScroll={() => { const panel = transcriptRef.current; if (panel) followTranscript.current = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 80; }}>
          {lines.length === 0 ? <div className="transcript-empty"><div className="empty-icon" aria-hidden="true"><span /><span /><span /></div><h3>Hear each piece work together.</h3><p>Your recognized speech and the assistant’s reply text will appear here.</p></div> : <ol className="transcript-messages" aria-live="polite" aria-relevant="additions text">{lines.map((line) => <li key={line.id} className={line.role === "You" ? "message-user" : "message-assistant"}><div className="message-meta"><span className="speaker-avatar" aria-hidden="true">{line.role === "You" ? "Y" : "↗"}</span><span>{line.role}</span>{line.interim && <span className="interim-label">Transcribing…</span>}</div><p>{line.text}</p></li>)}</ol>}
        </div>
        <div className="transcript-footer"><span className="small-dot" />{connected ? `Live ${settings.label} transcript · held in this tab` : "Session text stays here until cleared, switched, or the next session"}</div>
      </section>
    </div>

    <details className="setup-details" open={!health?.configured}>
      <summary><span>{settings.label} setup</span><span className="setup-summary">{checking ? "Checking server…" : health?.configured ? "Configuration present" : health?.configError ? "Configuration invalid" : health ? "Credentials needed" : "Server unavailable"}<span aria-hidden="true"> +</span></span></summary>
      <div className="setup-body">
        <dl>
          <div><dt>Start the server</dt><dd>In a second terminal, run <code>npm run dev:pipecat</code> from <code>practice/</code>. Keep it running alongside this web app.</dd></div>
          <div><dt>Speech recognition</dt><dd>{settings.stt} · <code>{settings.sttKey}</code></dd></div>
          <div><dt>Reply generation</dt><dd>{settings.llm} · <code>{settings.llmKey}</code> and <code>{settings.llmModel}</code></dd></div>
          <div><dt>Speech playback</dt><dd>{settings.tts} · <code>{settings.ttsKey}</code> and <code>{settings.voiceId}</code></dd></div>
          <div><dt>Server status</dt><dd>{health ? `${health.activeSessions} active session${health.activeSessions === 1 ? "" : "s"}. ${health.configured ? "Configuration is present; start a session to test the providers." : "Required configuration is missing."}` : "The local Pipecat server has not responded."}</dd></div>
        </dl>
        <p>Store keys in <code>practice/.env.local</code>, then restart the Python server after changes. {settings.setupNote}</p>
      </div>
    </details>
  </>;
}
