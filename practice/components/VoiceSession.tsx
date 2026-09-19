"use client";

import { VoiceProvider, useVoice, type VoiceContextType } from "@humeai/voice-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { DEMO_TRANSCRIPT, transcriptLines } from "./transcript";

type Phase = "idle" | "preparing" | "ready" | "connecting" | "connected" | "stopping";
type Token = { accessToken: string; configId: string; configVersion?: string };
type Configuration = Omit<Token, "accessToken">;
type Health = { evi: boolean; sambanova: boolean };
type Attempt = { promise: Promise<void>; socketStarted: boolean };
type ProviderFailure = { sequence: number; message: string };

function safeVoiceError(error: NonNullable<VoiceContextType["error"]>): string {
  if (error.reason === "mic_permission_denied") return "Microphone access was denied. Allow it in your browser’s site settings, then prepare a new session.";
  if (error.type === "mic_error") return "The microphone could not start. Check that your headset is connected and another app is not using it, then try again.";
  if (error.type === "audio_error") return "Audio playback could not start. Check your output device and browser audio permissions, then try again.";
  return "The voice connection failed. Check your network and Hume configuration, then prepare a new session. Your provider may also require available credit.";
}

function WaveIcon({ muted = false }: { muted?: boolean }) {
  return <span className={`microphone-symbol${muted ? " microphone-muted" : ""}`} aria-hidden="true"><i /><b /></span>;
}

function Session({ providerFailure, onBusyChange }: { providerFailure: ProviderFailure | null; onBusyChange?: (busy: boolean) => void }) {
  const voice = useVoice();
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const mounted = useRef(true);
  const generation = useRef(0);
  const phaseRef = useRef<Phase>("idle");
  const token = useRef<Token | null>(null);
  const tokenRequest = useRef<AbortController | null>(null);
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attempt = useRef<Attempt | null>(null);
  const stopInFlight = useRef<Promise<void> | null>(null);
  const [phase, setPhaseState] = useState<Phase>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [demo, setDemo] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const followTranscript = useRef(true);
  const busyCallback = useRef(onBusyChange);
  busyCallback.current = onBusyChange;

  const setPhase = useCallback((value: Phase) => {
    phaseRef.current = value;
    if (mounted.current) {
      setPhaseState(value);
      busyCallback.current?.(value !== "idle");
    }
  }, []);

  const end = useCallback((reason?: string): Promise<void> => {
    if (reason && mounted.current) setProblem(reason);
    if (stopInFlight.current) return stopInFlight.current;
    const id = ++generation.current;
    tokenRequest.current?.abort();
    tokenRequest.current = null;
    token.current = null;
    if (expiryTimer.current) clearTimeout(expiryTimer.current);
    if (connectionTimer.current) clearTimeout(connectionTimer.current);
    const pending = attempt.current;
    setPhase("stopping");
    const cleanup = async () => {
      let clean = true;
      // disconnect() stops captured tracks, recording, socket, queued audio and
      // the shared AudioContext. It cannot abort the browser permission dialog.
      try { await voiceRef.current.disconnect(); } catch { clean = false; }
      if (pending && !pending.socketStarted) {
        // If End wins a getUserMedia/player-init race, a stream can arrive after
        // the SDK's first cleanup. Serialize new sessions behind a second pass.
        await pending.promise.catch(() => undefined);
        try { await voiceRef.current.disconnect(); } catch { clean = false; }
      }
      if (generation.current === id) {
        attempt.current = null;
        if (!clean && mounted.current) setProblem("Audio cleanup did not finish normally. Close this tab before starting another voice session.");
        if (clean) setPhase("idle");
      }
    };
    const task = cleanup().finally(() => { if (stopInFlight.current === task) stopInFlight.current = null; });
    stopInFlight.current = task;
    return task;
  }, [setPhase]);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    fetch("/api/health", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Health unavailable");
        const data = await response.json();
        if (typeof data.configured?.evi !== "boolean" || typeof data.configured?.sambanova !== "boolean") throw new Error("Invalid health response");
        if (!controller.signal.aborted) setHealth(data.configured);
      })
      .catch(() => { if (!controller.signal.aborted) setHealthFailed(true); });
    const onPageHide = () => { void end(); };
    window.addEventListener("pagehide", onPageHide);
    return () => {
      mounted.current = false;
      controller.abort();
      window.removeEventListener("pagehide", onPageHide);
      void end();
    };
  }, [end]);

  useEffect(() => {
    if (attempt.current && (voice.readyState === "connecting" || voice.readyState === "open")) attempt.current.socketStarted = true;
    if (voice.error && (phaseRef.current === "connecting" || phaseRef.current === "connected")) {
      void end(safeVoiceError(voice.error));
    } else if (voice.status.value === "connected" && phaseRef.current === "connecting") {
      if (connectionTimer.current) clearTimeout(connectionTimer.current);
      setPhase("connected");
    } else if (voice.readyState === "closed" && (phaseRef.current === "connected" || (phaseRef.current === "connecting" && attempt.current?.socketStarted))) {
      void end("The session ended. Prepare a new session to reconnect with a fresh token.");
    }
  }, [voice.error, voice.status.value, voice.readyState, end, setPhase]);

  useEffect(() => {
    // Server JSON error events invoke VoiceProvider.onError without setting the
    // SDK context's error field. Handle that channel too, without raw messages.
    if (providerFailure && (phaseRef.current === "connecting" || phaseRef.current === "connected")) void end(providerFailure.message);
  }, [providerFailure, end]);

  const prepare = async () => {
    if (phaseRef.current !== "idle" || stopInFlight.current) return;
    const id = ++generation.current;
    const controller = new AbortController();
    tokenRequest.current = controller;
    setProblem(null);
    setDemo(false);
    setConfiguration(null);
    voiceRef.current.clearMessages();
    setPhase("preparing");
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch("/api/hume/token", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      const data = await response.json();
      if (generation.current !== id || !mounted.current) return;
      if (!response.ok) {
        // This same-origin endpoint guarantees sanitized, actionable errors.
        setProblem(typeof data.error === "string" ? data.error : "Could not prepare the session. Check the server’s Hume configuration.");
        setPhase("idle");
        return;
      }
      if (typeof data.accessToken !== "string" || !data.accessToken || typeof data.configId !== "string" || !data.configId) {
        setProblem("The server returned an incomplete session. Check HUME_CONFIG_ID and the token endpoint.");
        setPhase("idle");
        return;
      }
      const config = { configId: data.configId, ...(data.configVersion !== undefined && { configVersion: String(data.configVersion) }) };
      token.current = { accessToken: data.accessToken, ...config };
      setConfiguration(config);
      setPhase("ready");
      // A prepared token is held in memory for one click, never local storage.
      // Expire it early so an idle tab cannot later start with a stale token.
      expiryTimer.current = setTimeout(() => {
        if (generation.current !== id || phaseRef.current !== "ready") return;
        token.current = null;
        setProblem("The prepared session expired. Prepare a new one when you are ready.");
        setPhase("idle");
      }, 60_000);
    } catch {
      if (generation.current === id && mounted.current) {
        setProblem(controller.signal.aborted ? "Session preparation timed out. Check your connection and try again." : "Could not reach the session server. Check your network and try again.");
        setPhase("idle");
      }
    } finally {
      clearTimeout(timeout);
      if (tokenRequest.current === controller) tokenRequest.current = null;
    }
  };

  const start = () => {
    if (phaseRef.current !== "ready" || !token.current || stopInFlight.current) return;
    const credentials = token.current;
    token.current = null;
    if (expiryTimer.current) clearTimeout(expiryTimer.current);
    const id = generation.current;
    setPhase("connecting");
    // Called directly by the Start button, preserving the audio user gesture.
    const promise = voiceRef.current.connect({
      auth: { type: "accessToken", value: credentials.accessToken },
      configId: credentials.configId,
      ...(credentials.configVersion && { configVersion: credentials.configVersion }),
      verboseTranscription: true,
    });
    const pending = { promise, socketStarted: false };
    attempt.current = pending;
    connectionTimer.current = setTimeout(() => {
      if (generation.current === id && phaseRef.current === "connecting") void end("Connection timed out. If a microphone permission dialog is open, dismiss it so cleanup can finish.");
    }, 30_000);
    void promise.catch(() => {
      if (generation.current === id && mounted.current) void end("Voice could not start. Check microphone permissions, your network, and the configured Hume session.");
    }).finally(() => {
      if (attempt.current === pending) attempt.current = null;
    });
  };

  const lines = demo ? DEMO_TRANSCRIPT : transcriptLines(voice.messages);
  const lastText = lines.at(-1)?.text;
  useEffect(() => {
    const panel = transcriptRef.current;
    if (panel && followTranscript.current) panel.scrollTop = panel.scrollHeight;
  }, [lines.length, lastText, demo]);

  const active = phase !== "idle";
  const connected = phase === "connected";
  const labels: Record<Phase, string> = { idle: "Ready when you are", preparing: "Preparing a session", ready: "Session prepared", connecting: "Connecting your voice", connected: voice.isMuted ? "Microphone muted" : voice.isPlaying ? "Assistant is speaking" : "Listening to you", stopping: "Ending the session" };
  const descriptions: Record<Phase, string> = {
    idle: "Prepare a fresh session, then start your microphone with a click.",
    preparing: "Requesting temporary access from your local server. Your microphone is still off.",
    ready: "Press Start voice to allow your microphone and begin the conversation.",
    connecting: "Allow microphone access in your browser. We’re opening the voice connection.",
    connected: "Speak naturally. You can interrupt a reply or mute your microphone at any time.",
    stopping: "Releasing the microphone and audio. Dismiss any open microphone permission dialog to finish.",
  };

  return (
    <>
      <div className="session-grid">
        <section className="voice-panel" aria-labelledby="voice-heading">
          <div className="panel-topline"><span className="eyebrow">VOICE SESSION</span><span className={`state-tag ${connected ? "is-connected" : ""}`}><span />{connected ? "CONNECTED" : phase === "connecting" ? "CONNECTING" : phase === "stopping" ? "ENDING" : "MIC OFF"}</span></div>
          <div className={`voice-orbit ${connected && !voice.isMuted ? "orbit-active" : ""}`} aria-hidden="true"><div className="orbit-inner"><span /><span /><span /><span /><span /><span /><span /></div><span className="orbit-dot" /></div>
          <div className="session-copy" aria-live="polite" aria-atomic="true"><h2 id="voice-heading">{labels[phase]}</h2><p>{descriptions[phase]}</p></div>

          <div className="session-controls">
            {phase === "idle" && <button className="button button-primary" onClick={() => void prepare()}><WaveIcon /> Prepare session <span aria-hidden="true">↗</span></button>}
            {phase === "ready" && <button className="button button-primary" onClick={start}><WaveIcon /> Start voice <span aria-hidden="true">↗</span></button>}
            {connected && <button className="button button-primary" onClick={() => voice.isMuted ? voice.unmute() : voice.mute()} aria-pressed={voice.isMuted}><WaveIcon muted={voice.isMuted} />{voice.isMuted ? "Unmute microphone" : "Mute microphone"}</button>}
            {(phase === "preparing" || phase === "connecting" || phase === "stopping") && <button className="button button-primary" disabled><span className="spinner" aria-hidden="true" />{phase === "preparing" ? "Preparing…" : phase === "connecting" ? "Connecting…" : "Ending…"}</button>}
            {active && <button className="button button-secondary" onClick={() => void end()} disabled={phase === "stopping"}>{phase === "ready" || phase === "preparing" ? "Cancel" : "End session"}</button>}
          </div>
          <p className="session-fineprint">{connected ? "Audio is sent to Hume while connected." : "Microphone access begins only after Start voice."}</p>
          {problem && <div className="error-notice" role="alert"><strong>Session needs attention</strong><p>{problem}</p></div>}
        </section>

        <section className="transcript-panel" aria-labelledby="transcript-heading">
          <div className="transcript-header"><div><p className="eyebrow">THE CONVERSATION</p><h2 id="transcript-heading">Transcript <span>{String(lines.length).padStart(2, "0")}</span></h2></div><button className="text-button" disabled={active || (!demo && lines.length === 0)} onClick={() => { setDemo(false); voice.clearMessages(); }}>Clear</button></div>
          {demo && <div className="demo-banner"><span>DEMO DATA</span> Sample text only · no microphone or provider call</div>}
          <div className="transcript-scroll" ref={transcriptRef} tabIndex={0} role="region" aria-label="Conversation transcript" onScroll={() => { const panel = transcriptRef.current; if (panel) followTranscript.current = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 80; }}>
            {lines.length === 0 ? <div className="transcript-empty"><div className="empty-icon" aria-hidden="true"><span /><span /><span /></div><h3>A conversation starts here.</h3><p>Your words and the assistant’s replies will appear as you speak.</p><button className="text-button demo-link" disabled={active} onClick={() => setDemo(true)}>Preview a sample transcript <span aria-hidden="true">↗</span></button></div> : <ol className="transcript-messages" aria-live="polite" aria-relevant="additions text">{lines.map((line) => <li key={line.id} className={line.role === "You" ? "message-user" : "message-assistant"}><div className="message-meta"><span className="speaker-avatar" aria-hidden="true">{line.role === "You" ? "Y" : "↗"}</span><span>{line.role}</span>{line.interim && <span className="interim-label">Transcribing…</span>}</div><p>{line.text}</p></li>)}</ol>}
          </div>
          <div className="transcript-footer"><span className="small-dot" />{demo ? "Sample conversation · live audio has not been tested" : connected ? "Live session transcript · held in this tab" : "Session text stays here until cleared or the next session"}</div>
        </section>
      </div>

      <details className="setup-details"><summary><span>Practice setup</span><span className="setup-summary">{health ? health.evi ? "Hume configured" : "Hume needs credentials" : healthFailed ? "Server status unavailable" : "Checking server…"}<span aria-hidden="true"> +</span></span></summary><div className="setup-body"><dl><div><dt>Hume EVI</dt><dd>{health ? health.evi ? "Credentials present; live audio unverified" : "Add HUME_API_KEY, HUME_SECRET_KEY and HUME_CONFIG_ID in the server environment" : "Configuration status unavailable"}</dd></div><div><dt>Requested configuration</dt><dd>{configuration ? <><code>{configuration.configId}</code> · version {configuration.configVersion ?? "latest (not pinned)"}</> : "Shown after a session is prepared"}</dd></div><div><dt>Session connection</dt><dd>{voice.chatMetadata ? <code>{voice.chatMetadata.chatId}</code> : "No active session metadata"}</dd></div><div><dt>SambaNova</dt><dd>{health?.sambanova ? "Credentials present for Modular Pipecat and the CLI smoke test" : "Add credentials and an exact model ID to use Modular Pipecat"}. This Hume EVI route uses its own configured language model.</dd></div></dl><p>This practice app is not the official event starter. A configured key does not prove working audio, quota, or an integrated sponsor pipeline.</p></div></details>
    </>
  );
}

export default function VoiceSession({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [providerFailure, setProviderFailure] = useState<ProviderFailure | null>(null);
  const reportError = useCallback((error: NonNullable<VoiceContextType["error"]>) => {
    setProviderFailure((previous) => ({ sequence: (previous?.sequence ?? 0) + 1, message: safeVoiceError(error) }));
  }, []);
  return <VoiceProvider onError={reportError} clearMessagesOnDisconnect={false} messageHistoryLimit={200}><Session providerFailure={providerFailure} onBusyChange={onBusyChange} /></VoiceProvider>;
}
