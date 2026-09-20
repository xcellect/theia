"use client";

import { useEffect, useRef, useState } from "react";
import ResearchMarkdown from "./ResearchMarkdown";

export type ConversationTurn = { runId: string; question: string; markdown?: string; status: string; done?: boolean; partial?: boolean };
type ConversationPage = { sessionId: string; runs: ConversationTurn[]; hasMore?: boolean; nextBefore?: string | null };
type Props = {
  sessionId: string;
  selectedRunId: string | null;
  currentTurn?: ConversationTurn;
  busy: boolean;
  refreshToken: number;
  onOpenRun: (runId: string) => void;
  onSource: (runId: string, sourceId: string) => void;
};

const statusLabel = (status: string) => ({ completed: "Complete", partial: "Partial report", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted", clarification: "More context needed", running: "In progress", queued: "Queued" }[status] || status);

export default function ResearchConversation({ sessionId, selectedRunId, currentTurn, busy, refreshToken, onOpenRun, onSource }: Props) {
  const [page, setPage] = useState<ConversationPage | null>(null);
  const [problem, setProblem] = useState("");
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [retry, setRetry] = useState(0);
  const earlierRequest = useRef<AbortController | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const scrolledRun = useRef("");
  const currentSession = useRef(sessionId);
  currentSession.current = sessionId;

  useEffect(() => {
    earlierRequest.current?.abort();
    setLoadingEarlier(false);
    setPage(null);
    return () => earlierRequest.current?.abort();
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    setProblem("");
    void fetch(`/api/research/sessions/${encodeURIComponent(sessionId)}`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Conversation history is temporarily unavailable.");
        const data: ConversationPage = await response.json();
        if (data.sessionId !== sessionId || !Array.isArray(data.runs)) throw new Error("Conversation history could not be read.");
        if (controller.signal.aborted) return;
        setPage(previous => {
          if (previous?.sessionId !== sessionId) return data;
          const latestIds = new Set(data.runs.map(run => run.runId));
          const earlier = previous.runs.filter(run => !latestIds.has(run.runId));
          return { ...data, runs: [...earlier, ...data.runs], ...(earlier.length ? { hasMore: previous.hasMore, nextBefore: previous.nextBefore } : {}) };
        });
      }).catch(error => {
        if (!controller.signal.aborted) setProblem(error instanceof Error ? error.message : "Conversation history is temporarily unavailable.");
      });
    return () => controller.abort();
  }, [sessionId, refreshToken, busy, retry]);

  const loadEarlier = async () => {
    if (loadingEarlier || !page?.nextBefore) return;
    const controller = new AbortController();
    earlierRequest.current?.abort(); earlierRequest.current = controller;
    setLoadingEarlier(true); setProblem("");
    try {
      const response = await fetch(`/api/research/sessions/${encodeURIComponent(sessionId)}?before=${encodeURIComponent(page.nextBefore)}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("Earlier turns could not be loaded. Try again.");
      const data: ConversationPage = await response.json();
      if (data.sessionId !== sessionId || !Array.isArray(data.runs)) throw new Error("Earlier turns could not be read.");
      if (controller.signal.aborted || currentSession.current !== sessionId) return;
      setPage(previous => {
        if (previous?.sessionId !== sessionId) return previous;
        const ids = new Set(previous.runs.map(run => run.runId));
        return { ...previous, hasMore: data.hasMore, nextBefore: data.nextBefore, runs: [...data.runs.filter(run => !ids.has(run.runId)), ...previous.runs] };
      });
    } catch (error) {
      if (!controller.signal.aborted) setProblem(error instanceof Error ? error.message : "Earlier turns could not be loaded.");
    } finally {
      if (earlierRequest.current === controller && !controller.signal.aborted) setLoadingEarlier(false);
    }
  };

  const turns = page?.sessionId === sessionId ? [...page.runs] : [];
  if (currentTurn?.question) {
    const index = turns.findIndex(turn => turn.runId === currentTurn.runId);
    if (index >= 0) {
      // Keep the persisted report visible while the selected run's events replay.
      if (currentTurn.markdown || !turns[index].markdown) turns[index] = currentTurn;
    } else turns.push(currentTurn);
  }
  useEffect(() => {
    const key = `${sessionId}:${selectedRunId}`;
    if (scrolledRun.current === key || !selectedRunId) return;
    const container = viewport.current;
    const turn = container && Array.from(container.querySelectorAll<HTMLElement>(".conversation-turn")).find(item => item.dataset.runId === selectedRunId);
    if (container && turn) {
      container.scrollTop += turn.getBoundingClientRect().top - container.getBoundingClientRect().top - 12;
      scrolledRun.current = key;
    }
  }, [sessionId, selectedRunId, turns.length]);
  if (!turns.length && !problem) return null;

  return <section className="research-conversation research-surface" aria-label="Conversation history">
    <header className="research-surface-heading"><h2>Conversation</h2><span className="conversation-hint">Select a report to explore its analysis</span></header>
    {problem && <p className="conversation-problem" role="status">{problem} <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    <div className="conversation-turns" ref={viewport}>
      {page?.hasMore && <button className="conversation-load" disabled={loadingEarlier} onClick={() => void loadEarlier()}>{loadingEarlier ? "Loading earlier turns…" : "Load earlier turns"}</button>}
      {turns.map(turn => {
        const selected = turn.runId === selectedRunId;
        return <article className={`conversation-turn${selected ? " is-selected" : ""}`} key={turn.runId} data-run-id={turn.runId}>
          <div className="conversation-question"><span className="research-eyebrow">YOU</span><p>{turn.question}</p></div>
          <div className="conversation-answer" onClick={event => {
            if (busy || (event.target as HTMLElement).closest("a,button") || !window.getSelection()?.isCollapsed) return;
            onOpenRun(turn.runId);
          }}>
            <div className="conversation-answer-heading"><span className="research-eyebrow">RESEARCH ORB</span><span className="conversation-turn-status">{statusLabel(turn.status === "completed" && turn.partial ? "partial" : turn.status)}</span></div>
            {turn.markdown ? <div className="conversation-report" tabIndex={0} aria-label={`Report for: ${turn.question}`}><ResearchMarkdown text={turn.markdown} onSource={id => onSource(turn.runId, id)} /></div>
              : <p className="conversation-no-report">{turn.status === "running" || turn.status === "queued" ? "The agents are preparing this report. Follow their progress below." : turn.status === "clarification" ? "The assistant requested more context. Open the analysis to see the details." : "No completed report for this turn. Open the analysis to review its progress and any partial findings."}</p>}
            <button className="conversation-open-report" disabled={busy} aria-pressed={selected} onClick={() => onOpenRun(turn.runId)}>{selected ? "Viewing analysis" : "View analysis"} <span aria-hidden="true">↓</span></button>
          </div>
        </article>;
      })}
    </div>
  </section>;
}
