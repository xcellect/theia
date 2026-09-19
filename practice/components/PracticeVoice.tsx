"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";

// The SDK owns browser audio APIs; it is deliberately loaded only in the browser.
const VoiceSession = dynamic(() => import("./VoiceSession"), {
  ssr: false,
  loading: () => <div className="loading-panel" role="status">Opening the practice space…</div>,
});

const PipecatSession = dynamic(() => import("./PipecatSession"), {
  ssr: false,
  loading: () => <div className="loading-panel" role="status">Opening the Pipecat practice space…</div>,
});

type Route = "hume" | "pipecat" | "gradium";

export default function PracticeVoice() {
  const [route, setRoute] = useState<Route>("hume");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const onBusyChange = (value: boolean) => {
    busyRef.current = value;
    setBusy(value);
  };
  const choose = (value: Route) => {
    if (!busyRef.current) setRoute(value);
  };

  return <>
    <section className="route-picker" aria-label="Choose a voice route">
      <div className="route-picker-heading"><p className="eyebrow">THREE WAYS TO TALK</p><p aria-live="polite">{busy ? "End or cancel this session before switching routes." : "Choose a route, then start a conversation."}</p></div>
      <div className="route-options">
        <button type="button" className={`route-option${route === "hume" ? " route-selected" : ""}`} aria-pressed={route === "hume"} disabled={busy && route !== "hume"} onClick={() => choose("hume")}>
          <span className="route-option-top"><strong>Hume EVI</strong><span className="route-badge">ALL IN ONE</span></span>
          <span className="route-flow">Your voice <span aria-hidden="true">→</span> Hume EVI <span aria-hidden="true">→</span> Spoken reply</span>
          <span className="route-description">Hume handles the conversation and voice in one session.</span>
        </button>
        <button type="button" className={`route-option${route === "pipecat" ? " route-selected" : ""}`} aria-pressed={route === "pipecat"} disabled={busy && route !== "pipecat"} onClick={() => choose("pipecat")}>
          <span className="route-option-top"><strong>Modular Pipecat</strong><span className="route-badge">STT + LLM + TTS</span></span>
          <span className="route-flow">Your voice <span aria-hidden="true">→</span> Deepgram <span aria-hidden="true">→</span> SambaNova <span aria-hidden="true">→</span> Hume TTS</span>
          <span className="route-description">Separate speech recognition, reply generation, and speech playback.</span>
        </button>
        <button type="button" className={`route-option${route === "gradium" ? " route-selected" : ""}`} aria-pressed={route === "gradium"} disabled={busy && route !== "gradium"} onClick={() => choose("gradium")}>
          <span className="route-option-top"><strong>Gradium + General Compute</strong><span className="route-badge">STT + LLM + TTS</span></span>
          <span className="route-flow">Your voice <span aria-hidden="true">→</span> Gradium STT <span aria-hidden="true">→</span> General Compute <span aria-hidden="true">→</span> Gradium TTS</span>
          <span className="route-description">Gradium handles speech while General Compute generates the reply.</span>
        </button>
      </div>
    </section>
    {route === "hume" ? <VoiceSession onBusyChange={onBusyChange} /> : <PipecatSession key={route} variant={route} onBusyChange={onBusyChange} />}
  </>;
}
