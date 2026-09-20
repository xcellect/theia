"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import ResearchLibrary from "./ResearchLibrary";
import ResearchConversation from "./ResearchConversation";
import ResearchOrb, { type OrbState } from "./ResearchOrb";
import ResearchMarkdown from "./ResearchMarkdown";
import type { ResearchIntentPreview, ResearchActivity } from "./PipecatSession";
import "./research.css";

const PipecatSession = dynamic(() => import("./PipecatSession"), { ssr: false, loading: () => <div className="research-voice-loading">Preparing voice controls…</div> });
type Source = { id: string; title: string; kind?: string; description?: string; section?: string; text?: string; url?: string; path?: string; coverage?: string };
type Health = { configured: boolean; missing: string[]; sources: Source[]; configError?: string; activeRunId?: string | null; latestRunId?: string | null; activeSessionId?: string | null; latestSessionId?: string | null; search?: { configured: boolean; provider: string }; paper2agent?: { available: boolean; mode: "draft"; supported: "arxiv" } };
type SearchResult = { title: string; url: string; author?: string; publishedDate?: string; status: string; message?: string };
type PaperPreparation = { state: "working" | "complete" | "failed" | "stopped"; message: string; title?: string; sourceId?: string; cacheHit?: boolean };
type Agent = { title?: string; state: "waiting" | "working" | "complete" | "failed" | "stopped"; text: string };
type RunEvent = { runId: string; seq: number; at: string; type: string; payload: Record<string, unknown> };
type Routing = { answers?: Record<string, unknown>; model?: string; profile?: string; [key: string]: unknown };
const INITIAL_AGENTS: Record<string, Agent> = { evidence: { state: "waiting", text: "" }, critic: { state: "waiting", text: "" } };
const SOURCE_OPTIONS: Source[] = [{ id: "paper2agent-paper", title: "Paper2Agent manuscript", kind: "paper" }, { id: "paper2agent-code", title: "Paper2Agent repository", kind: "code" }];
const EXAMPLES = ["Find recent papers on evaluating research agents.", "Compare retrieval-augmented generation and long-context models.", "What does Paper2Agent actually verify?"];
const SESSION_KEY = "research-orb.session.v1";
const RUN_KEY = "research-orb.run.v1";
const STATE_LABEL: Record<OrbState, string> = { idle: "Ready when you are", listening: "Listening to you", routing: "Jev is routing your question", analyzing: "Following the evidence", speaking: "Talking it through", error: "Let’s try that again" };

function Icon({ name, size = 18 }: { name: "arrow" | "paper" | "code" | "spark" | "copy" | "download" | "close" | "check"; size?: number }) {
  const symbols = { arrow: "↗", paper: "▤", code: "‹/›", spark: "✧", copy: "⧉", download: "↓", close: "×", check: "✓" };
  return <span className="research-icon" style={{ fontSize: size, lineHeight: 1, display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: size }} aria-hidden="true">{symbols[name]}</span>;
}

function SourceDrawer({ source, onClose }: { source: Source; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog className="research-source-dialog" ref={dialog} onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="research-drawer-head"><span className="research-eyebrow">SOURCE {source.id}</span><button className="research-icon-button" onClick={onClose} aria-label="Close source"><Icon name="close" /></button></div>
    <h2>{source.title}</h2><p className="research-source-location">{source.section || source.path || source.description || "Source excerpt"}</p>
    {source.url && /^https?:\/\//.test(source.url) && <a className="research-original-link" href={source.url} target="_blank" rel="noopener noreferrer">Open original source <Icon name="arrow" size={14} /></a>}
    <div className="research-source-text"><ResearchMarkdown text={source.text || "No excerpt is available for this source yet."} /></div>
    <p className="research-source-note">{source.coverage ? `Coverage: ${source.coverage}. ` : ""}This is the text provided to the agents; extracted excerpts may not contain the full paper. Repository analysis is static reading.</p>
  </dialog>;
}

function AgentCard({ id, agent, onSource }: { id: string; agent: Agent; onSource: (id: string) => void }) {
  const viewport = useRef<HTMLDivElement>(null);
  const followOutput = useRef(true);
  useEffect(() => {
    const element = viewport.current;
    if (element && followOutput.current) element.scrollTop = element.scrollHeight;
  }, [agent.text]);
  return <article className={`research-agent-card agent-${agent.state}`}>
    <header className="research-agent-heading">
      <div className="research-agent-icon"><Icon name={id === "evidence" ? "paper" : "spark"} size={17} /></div>
      <div className="research-agent-title"><h3>{agent.title || (id === "evidence" ? "Evidence Analyst" : "Critical Reader")}</h3><p>{agent.title ? "Paper agent · evidence and limitations" : id === "evidence" ? "Methods, evidence & implementation" : "Limitations, gaps & counterevidence"}</p></div>
      <span className="research-agent-state" title={agent.state}>{agent.state === "complete" ? <Icon name="check" size={14} /> : agent.state === "working" ? <span className="research-small-spinner" /> : agent.state === "failed" ? "!" : "·"}</span>
    </header>
    <div className="research-agent-findings" ref={viewport} tabIndex={0} aria-label={`${agent.title || (id === "evidence" ? "Evidence Analyst" : "Critical Reader")} findings`} onScroll={() => { const el = viewport.current; if (el) followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 70; }}>
      {agent.text ? <ResearchMarkdown text={agent.text} onSource={onSource} /> : <p>{agent.state === "working" ? "Reading the supplied evidence. Findings will stream here as they arrive." : "Waiting for a research question. Live findings will appear here."}</p>}
      {agent.state === "working" && <span className="research-writing-cursor" aria-label="Agent is analyzing" />}
    </div>
    <div className="research-agent-footer"><span>{agent.state === "working" ? "Streaming findings" : agent.state === "complete" ? "Analysis complete" : agent.state === "failed" ? "Analysis unavailable" : agent.state === "stopped" ? "Analysis stopped · partial output" : "Awaiting question"}</span><span>{agent.text ? "Scroll to explore" : "Awaiting evidence"}</span></div>
  </article>;
}

export default function ResearchWorkspace() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthProblem, setHealthProblem] = useState("");
  const [checkingHealth, setCheckingHealth] = useState(true);
  const [question, setQuestion] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [paper2agentEnabled, setPaper2agentEnabled] = useState(true);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);
  const [libraryVersion, setLibraryVersion] = useState(0);
  const [paperAgents, setPaperAgents] = useState<Record<string, Agent>>({});
  const [paperJobs, setPaperJobs] = useState<Record<string, string>>({});
  const [viewingHistory, setViewingHistory] = useState(false);
  const [paperPreparation, setPaperPreparation] = useState<PaperPreparation | null>(null);
  const [sessionId, setSessionId] = useState("");
  const sessionRef = useRef("");
  const [previousRunId, setPreviousRunId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchState, setSearchState] = useState<"idle" | "searching" | "reading" | "complete" | "failed" | "stopped">("idle");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [pastedText, setPastedText] = useState("");
  const [pastedKind, setPastedKind] = useState<"paper" | "code">("paper");
  const [showPaste, setShowPaste] = useState(false);
  const researchContext = useMemo(() => ({ sourceIds: selectedSources, pastedText, pastedKind, searchEnabled, paper2agentEnabled, paperIds: selectedPaperIds, sessionId, previousRunId }), [selectedPaperIds, selectedSources, pastedText, pastedKind, searchEnabled, paper2agentEnabled, sessionId, previousRunId]);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<OrbState>("idle");
  const [voiceState, setVoiceState] = useState("idle");
  const [transcript, setTranscript] = useState("");
  const [intentPreview, setIntentPreview] = useState<ResearchIntentPreview | null>(null);
  const [previewSubmitted, setPreviewSubmitted] = useState(false);
  const [workLabel, setWorkLabel] = useState("Waiting for your research question");
  const previewTurn = useRef<string | undefined>(undefined);
  const retiredPreviewTurns = useRef(new Set<string>());
  const reportViewport = useRef<HTMLDivElement>(null);
  const followReport = useRef(true);
  const [runId, setRunId] = useState<string | null>(null);
  const [runQuestion, setRunQuestion] = useState("");
  const [routing, setRouting] = useState<Routing | null>(null);
  const [agents, setAgents] = useState<Record<string, Agent>>(INITIAL_AGENTS);
  const [sources, setSources] = useState<Source[]>([]);
  const [report, setReport] = useState("");
  const [reportDone, setReportDone] = useState(false);
  const [reportPartial, setReportPartial] = useState(false);
  const [runStatus, setRunStatus] = useState("running");
  const [verification, setVerification] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [activity, setActivity] = useState<{ label: string; at: string }[]>([]);
  const [sourceDrawer, setSourceDrawer] = useState<Source | null>(null);
  const [copied, setCopied] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const events = useRef<EventSource | null>(null);
  const streamDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRun = useRef<string | null>(null);
  const lastSeq = useRef(0);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const questionInput = useRef<HTMLTextAreaElement>(null);
  const startedAt = useRef(0);
  const analysisPanel = useRef<HTMLDivElement>(null);
  const sourceRequest = useRef<AbortController | null>(null);

  const refreshHealth = useCallback(async () => {
    setCheckingHealth(true);
    try {
      const response = await fetch("/api/research/health", { cache: "no-store", signal: AbortSignal.timeout(10_000) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || (typeof data.error === "string" ? data.error : null) || data.detail || "Research server is unavailable.");
      if (mounted.current) { setHealth(data); setHealthProblem(""); }
    } catch (error) {
      if (mounted.current) { setHealth(null); setHealthProblem(error instanceof Error ? error.message : "Research server is unavailable."); }
    } finally { if (mounted.current) setCheckingHealth(false); }
  }, []);

  useEffect(() => { mounted.current = true; void refreshHealth(); return () => { mounted.current = false; events.current?.close(); events.current = null; sourceRequest.current?.abort(); activeRun.current = null; if (streamDeadline.current) clearTimeout(streamDeadline.current); }; }, [refreshHealth]);
  useEffect(() => {
    if (!busy) return;
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [busy]);

  useEffect(() => {
    const element = reportViewport.current;
    if (element && followReport.current) element.scrollTop = element.scrollHeight;
  }, [report]);

  const handleResearchTurnStart = useCallback(() => {
    if (previewTurn.current && previewTurn.current !== "awaiting-new-turn") {
      retiredPreviewTurns.current.add(previewTurn.current);
      if (retiredPreviewTurns.current.size > 24) retiredPreviewTurns.current.delete(retiredPreviewTurns.current.values().next().value!);
    }
    previewTurn.current = "awaiting-new-turn";
    setIntentPreview(null); setPreviewSubmitted(false); setTranscript("");
  }, []);
  const handleIntentPreview = useCallback((event: ResearchIntentPreview) => {
    if (event.turnId && retiredPreviewTurns.current.has(event.turnId)) return;
    if (event.phase === "pending") { previewTurn.current = event.turnId; setPreviewSubmitted(false); }
    else if (event.turnId && previewTurn.current && event.turnId !== previewTurn.current) return;
    setIntentPreview((previous) => event.phase === "pending" && previous?.turnId === event.turnId && previous?.answers
      ? { ...event, answers: previous.answers, model: previous.model, profile: previous.profile }
      : event);
    // A slower Jev response must not replace newer words already received from STT.
    // Its snapshot also supplies live text when RTVI does not forward interim events.
    if (event.transcript) setTranscript((current) => !current || event.transcript.startsWith(current) ? event.transcript : current);
    if (event.phase === "ready") setActivity((items) => [...items.slice(-5), { label: "Live Jev intent preview received", at: event.at || new Date().toISOString() }]);
  }, []);
  const handleVoiceActivity = useCallback((event: ResearchActivity) => {
    setActivity((items) => [...items.slice(-5), { label: event.message, at: event.at || new Date().toISOString() }]);
  }, []);

  const stopPendingSearch = useCallback((state: "failed" | "stopped") => {
    const stop = (items: Record<string, Agent>) => Object.fromEntries(Object.entries(items).map(([id, agent]) => [id, agent.state === "working" ? { ...agent, state, text: agent.text || "Analysis ended before findings were available." } : agent]));
    setPaperAgents(stop); setAgents(stop);
    setSearchState((current) => current === "searching" || current === "reading" ? state : current);
    setSearchResults((items) => items.map((item) => item.status === "reading" ? { ...item, status: "stopped" } : item));
    setPaperPreparation((current) => current?.state === "working" ? { ...current, state, message: state === "stopped" ? "Paper preparation stopped." : "Paper preparation could not complete." } : current);
  }, []);

  const followRun = useCallback((id: string, history = false) => {
    setViewingHistory(history);
    if (activeRun.current === id && events.current) return;
    events.current?.close();
    if (streamDeadline.current) clearTimeout(streamDeadline.current);
    activeRun.current = id;
    sourceRequest.current?.abort(); setSourceDrawer(null); if (history) setIntentPreview(null);
    try { sessionStorage.setItem(RUN_KEY, JSON.stringify({ sessionId: sessionRef.current, runId: id })); } catch { /* Research works when browser storage is unavailable. */ }
    setPreviewSubmitted(true); setWorkLabel("Your question is in. Jev is selecting the analysis."); followReport.current = true;
    lastSeq.current = 0;
    startedAt.current = Date.now();
    setElapsed(0); setRunId(id); setBusy(true); setStage("routing"); setRouting(null); setAgents(INITIAL_AGENTS);
    setReport(""); setReportDone(false); setReportPartial(false); setRunStatus("running"); setVerification(""); setSources([]); setProblem(""); setNotice(""); setActivity([]);
    setSearchQuery(""); setSearchState("idle"); setSearchResults([]); setPaperPreparation(null); setRunQuestion(""); setPaperAgents({}); setPaperJobs({});
    const stream = new EventSource(`/api/research/runs/${encodeURIComponent(id)}/events`);
    events.current = stream;
    const finishStream = () => { stream.close(); if (events.current === stream) events.current = null; if (streamDeadline.current) clearTimeout(streamDeadline.current); };
    streamDeadline.current = setTimeout(() => {
      if (activeRun.current !== id || !mounted.current) return;
      finishStream(); stopPendingSearch("failed"); setRunStatus("interrupted"); setBusy(false); setStage("error"); setReportPartial(true);
      setProblem("The research stream timed out. Any visible findings are partial. Retry your question to start a fresh run.");
      void fetch(`/api/research/runs/${encodeURIComponent(id)}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
    }, 375_000);
    stream.onmessage = (message) => {
      if (activeRun.current !== id || !mounted.current) return;
      let event: RunEvent;
      try { event = JSON.parse(message.data); } catch { return; }
      if (event.runId !== id || event.seq <= lastSeq.current) return;
      lastSeq.current = event.seq;
      const p = event.payload || {};
      setNotice((current) => current.startsWith("Connection interrupted") ? "" : current);
      const text = typeof p.text === "string" ? p.text : "";
      const agentId = String(p.agent || "evidence");
      const log = (label: string) => setActivity((items) => [...items.slice(-5), { label, at: event.at }]);
      switch (event.type) {
        case "paper.routing": setWorkLabel(`${String(p.action || "Paper conversation").replace(/_/g, " ")}: retrieving the relevant evidence`); log("Jev selected paper targets"); break;
        case "paper.selection.started": setWorkLabel("Jev is choosing the relevant papers"); log("Evaluating discovered paper identities"); break;
        case "paper.selection.completed": log("Jev selected relevant papers"); break;
        case "paper.selection.failed": setNotice(String(p.message || "PDF selection was unavailable.")); break;
        case "paper.selected": setLibraryVersion((v) => v + 1); log(`Selected ${String(p.title || "a paper")}`); break;
        case "memory.retrieved": setWorkLabel(String(p.message)); log("Retrieved saved paper evidence and conversation memory"); break;
        case "paper.agent.started": setStage("analyzing"); setWorkLabel(`Reading ${String(p.title || "a paper")}`); setPaperAgents((items) => ({ ...items, [String(p.paperId)]: { title: String(p.title), state: "working", text: "" } })); break;
        case "paper.agent.delta": setPaperAgents((items) => ({ ...items, [String(p.paperId)]: { title: String(p.title), state: "working", text: (items[String(p.paperId)]?.text || "") + text } })); break;
        case "paper.agent.completed": setPaperAgents((items) => ({ ...items, [String(p.paperId)]: { title: String(p.title), state: "complete", text } })); log(`Paper agent finished: ${String(p.title)}`); break;
        case "paper.agent.failed": setPaperAgents((items) => ({ ...items, [String(p.paperId)]: { title: String(p.title), state: "failed", text: String(p.message || "Paper analysis failed.") } })); break;
        case "paper.failed": setNotice(String(p.message || "This paper could not be read.")); break;
        case "repo.discovered":
        case "repo.cloned":
        case "repo.cached":
        case "compute.checked":
        case "experiment.blocked":
          setPaperJobs((items) => ({ ...items, [String(p.paperId)]: String(p.reason || p.message || event.type.replace(/\./g, " ")) }));
          setLibraryVersion((v) => v + 1); log(String(p.message || p.reason || event.type.replace(/\./g, " "))); break;
        case "workspace.progress": setWorkLabel(String(p.message || "Saving workspace")); break;
        case "run.started": setRunQuestion(String(p.question || "Voice research question")); log("Research request received"); break;
        case "routing.started": setStage("routing"); setWorkLabel("Jev is understanding and routing your question"); log("Jev is classifying the request"); break;
        case "routing.completed": setRouting(p as Routing); setStage("analyzing"); setWorkLabel(p.acquisition === "search" ? "Finding papers and source text with Exa" : "Reading the selected source excerpts"); log("Jev selected an analysis profile"); break;
        case "search.started": setSearchQuery(String(p.query || "")); setSearchState("searching"); setStage("analyzing"); setWorkLabel("Exa is searching for relevant research"); log("Searching papers with Exa"); break;
        case "search.result": {
          const result = (p.result || p) as SearchResult;
          if (result.url) setSearchResults((items) => items.some((item) => item.url === result.url) ? items : [...items, { ...result, status: "discovered" }]);
          log(`Found ${result.title || "a research source"}`); break;
        }
        case "search.completed": setSearchState("complete"); log(`Search returned ${Number(p.count || 0)} sources`); break;
        case "search.failed": setSearchState("failed"); setNotice(String(p.message || "Paper search was unavailable. Any supplied excerpts can still be analyzed.")); log("Paper search could not complete"); break;
        case "source.fetch.started": {
          const url = String(p.url || (p.source as Source | undefined)?.url || "");
          setSearchState("reading"); setWorkLabel("Extracting source text for the research agents");
          setSearchResults((items) => items.map((item) => !url || item.url === url ? { ...item, status: "reading" } : item));
          log(`Reading ${String(p.title || "a discovered source")}`); break;
        }
        case "source.fetch.completed": {
          const url = String(p.url || (p.source as Source | undefined)?.url || "");
          setSearchResults((items) => items.map((item) => item.url === url ? { ...item, status: p.status === "unavailable" || p.usable === false || p.success === false ? "unavailable" : "extracted", message: typeof p.message === "string" ? p.message : undefined } : item));
          log(`Source extraction ${p.status === "unavailable" || p.usable === false || p.success === false ? "unavailable" : "completed"}`); break;
        }
        case "paper2agent.started":
        case "paper2agent.progress":
        case "paper2agent.completed":
        case "paper2agent.failed": {
          const state = event.type === "paper2agent.completed" ? "complete" : event.type === "paper2agent.failed" ? "failed" : "working";
          const message = String(p.message || (state === "complete" ? "Unreviewed paper draft prepared." : state === "failed" ? "Paper preparation unavailable. Continuing with Exa excerpts." : "Preparing the full paper with Paper2Agent."));
          setPaperPreparation((current) => ({ ...current, state, message, ...(typeof p.title === "string" ? { title: p.title } : {}), ...(typeof p.sourceId === "string" ? { sourceId: p.sourceId } : {}), ...(typeof p.cacheHit === "boolean" ? { cacheHit: p.cacheHit } : {}) }));
          if (state === "working") { setStage("analyzing"); setWorkLabel(message); }
          else setWorkLabel(state === "complete" ? "Reading evidence from the prepared paper draft" : "Continuing with the extracted Exa evidence");
          log(message); break;
        }
        case "source.read": {
          const source = (p.source || p) as Source;
          if (source.id) setSources((items) => items.some((item) => item.id === source.id) ? items.map((item) => item.id === source.id ? source : item) : [...items, source]);
          log(`Read ${source.title || "a source excerpt"}`); break;
        }
        case "agent.started": setSearchState((value) => value === "reading" ? "complete" : value); setStage("analyzing"); setWorkLabel("Two research agents are examining the evidence"); setAgents((items) => ({ ...items, [agentId]: { state: "working", text: "" } })); log(`${agentId === "critic" ? "Critical Reader" : "Evidence Analyst"} started`); break;
        case "agent.delta": setAgents((items) => ({ ...items, [agentId]: { state: "working", text: (items[agentId]?.text || "") + text } })); break;
        case "agent.completed": setAgents((items) => ({ ...items, [agentId]: { state: "complete", text: text || items[agentId]?.text || "" } })); log(`${agentId === "critic" ? "Critical Reader" : "Evidence Analyst"} completed`); break;
        case "agent.failed": setAgents((items) => ({ ...items, [agentId]: { state: "failed", text: items[agentId]?.text || String(p.message || "Analysis unavailable.") } })); log("A specialist could not complete its analysis"); break;
        case "verification.started": setWorkLabel("Jev is checking the draft against its sources"); setVerification("Jev is checking report claims against the evidence."); log("Jev started the evidence check"); break;
        case "verification.completed": setVerification(String(p.message || "Evidence check completed.")); log(String(p.message || "Evidence check completed")); break;
        case "report.delta": setWorkLabel("Writing your sourced research report"); setReport((current) => current + text); break;
        case "report.completed": setWorkLabel(p.partial ? "A partial report is ready — evidence gaps are marked" : "Your cited research report is ready"); setReport(String(p.markdown || text)); setReportDone(true); setReportPartial(Boolean(p.partial)); log(p.partial ? "Partial report ready" : "Cited report ready"); break;
        case "clarification.required": setWorkLabel("A little more context will help"); setNotice(String(p.message || p.question || "Add a relevant source or excerpt to continue.")); break;
        case "run.completed": setRunStatus(p.status === "clarification" ? "clarification" : p.partial ? "partial" : "completed"); setLibraryVersion((v) => v + 1); setWorkLabel(p.status === "clarification" ? "Add a little more context to continue" : p.partial ? "Report saved with evidence gaps marked" : "Research complete · report and paper workspace saved"); stopPendingSearch("stopped"); setPreviousRunId(id); setBusy(false); setStage("idle"); finishStream(); break;
        case "run.cancelled": setRunStatus("cancelled"); setLibraryVersion((v) => v + 1); stopPendingSearch("stopped"); setWorkLabel("Research stopped — partial findings remain below"); setBusy(false); setStage("idle"); setNotice("Research cancelled. Any findings below are partial."); finishStream(); break;
        case "run.failed": setRunStatus("failed"); setLibraryVersion((v) => v + 1); stopPendingSearch("failed"); setWorkLabel("Research paused — review the message below"); setBusy(false); setStage("error"); setReportPartial(true); setProblem(String(p.message || p.error || "The research run could not finish. Please retry.")); finishStream(); break;
      }
    };
    stream.onerror = () => {
      if (activeRun.current !== id || !mounted.current || events.current !== stream) return;
      if (stream.readyState === EventSource.CLOSED) {
        finishStream(); stopPendingSearch("failed"); setRunStatus("interrupted"); setBusy(false); setStage("error"); setReportPartial(true);
        setProblem("This research stream is unavailable or has expired. Please run your question again.");
      } else setNotice("Connection interrupted. Reconnecting to this research run…");
    };
  }, [stopPendingSearch]);

  useEffect(() => {
    let ownedSession = crypto.randomUUID();
    let ownedRun: string | null = null;
    try {
      ownedSession = sessionStorage.getItem(SESSION_KEY) || ownedSession;
      sessionStorage.setItem(SESSION_KEY, ownedSession);
      const stored = JSON.parse(sessionStorage.getItem(RUN_KEY) || "null");
      if (stored?.sessionId === ownedSession && typeof stored.runId === "string") ownedRun = stored.runId;
    } catch { /* A fresh session is still usable without persistence. */ }
    sessionRef.current = ownedSession; setSessionId(ownedSession);
    if (ownedRun && !activeRun.current) followRun(ownedRun, true);
  }, [followRun]);

  useEffect(() => {
    if (!sessionId || (voiceState !== "listening" && voiceState !== "speaking")) return;
    const controller = new AbortController();
    const interval = setInterval(async () => {
      const observedRun = activeRun.current;
      try {
        const response = await fetch("/api/research/health", { cache: "no-store", signal: controller.signal });
        if (!response.ok) return;
        const data: Health = await response.json();
        if (!mounted.current || controller.signal.aborted || submitting.current || activeRun.current !== observedRun) return;
        const ownedRun = data.activeSessionId === sessionId ? data.activeRunId : data.latestSessionId === sessionId ? data.latestRunId : null;
        if (ownedRun && activeRun.current !== ownedRun) followRun(ownedRun);
      } catch { /* Visible controls retain their own error states. */ }
    }, 4000);
    return () => { clearInterval(interval); controller.abort(); };
  }, [sessionId, voiceState, followRun]);

  const newResearch = () => {
    if (busy || submitting.current) return;
    events.current?.close(); events.current = null;
    sourceRequest.current?.abort();
    if (streamDeadline.current) clearTimeout(streamDeadline.current);
    const freshSession = crypto.randomUUID();
    sessionRef.current = freshSession; setSessionId(freshSession);
    try { sessionStorage.setItem(SESSION_KEY, freshSession); sessionStorage.removeItem(RUN_KEY); } catch { /* Persistence is optional. */ }
    activeRun.current = null; setRunId(null); setPreviousRunId(null); setRunQuestion("");
    setQuestion(""); setSelectedSources([]); setPastedText(""); setSearchEnabled(true); setPaper2agentEnabled(true); setSelectedPaperIds([]); setPaperAgents({}); setPaperJobs({}); setViewingHistory(false); setPaperPreparation(null); setShowPaste(false);
    setSearchQuery(""); setSearchState("idle"); setSearchResults([]); setSources([]); setSourceDrawer(null);
    setReport(""); setReportDone(false); setReportPartial(false); setVerification(""); setAgents(INITIAL_AGENTS);
    setRouting(null); setIntentPreview(null); setPreviewSubmitted(false); setTranscript(""); setProblem(""); setNotice(""); setActivity([]);
    setElapsed(0); setStage("idle"); setWorkLabel("Waiting for your research question");
    handleResearchTurnStart(); questionInput.current?.focus();
  };

  const resumeSession = (savedSession: string, savedRun?: string) => {
    if (busy) return;
    newResearch();
    sessionRef.current = savedSession; setSessionId(savedSession);
    try { sessionStorage.setItem(SESSION_KEY, savedSession); } catch { /* Optional tab recovery. */ }
    if (savedRun) { setPreviousRunId(savedRun); followRun(savedRun, true); }
    setLibraryVersion((v) => v + 1);
  };

  const openSavedRun = (id: string) => {
    if (busy) return;
    setPreviousRunId(id);
    if (id !== runId) followRun(id, true);
    analysisPanel.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || submitting.current || busy) return;
    submitting.current = true; setBusy(true); setStage("routing"); setProblem(""); setNotice("");
    startedAt.current = Date.now(); setElapsed(0);
    try {
      const response = await fetch("/api/research/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clientRequestId: crypto.randomUUID(), question: question.trim(), sourceIds: selectedSources, pastedText: pastedText.trim(), pastedKind, sessionId, searchEnabled, paper2agentEnabled, paperIds: selectedPaperIds, previousRunId }), signal: AbortSignal.timeout(15_000) });
      const data = await response.json();
      if (!response.ok || !data.runId) throw new Error(data.error?.message || (typeof data.error === "string" ? data.error : typeof data.detail === "string" ? data.detail : "Could not start research. Check the research server and configuration."));
      if (mounted.current) { setRunQuestion(question.trim()); followRun(data.runId); }
    } catch (error) { if (mounted.current) { setBusy(false); setStage("error"); setProblem(error instanceof Error ? error.message : "Could not start research."); } }
    finally { submitting.current = false; }
  };

  const cancel = async () => {
    if (!runId) return;
    try {
      const response = await fetch(`/api/research/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!response.ok) throw new Error("Could not cancel the run. Please try again.");
      events.current?.close(); events.current = null; if (streamDeadline.current) clearTimeout(streamDeadline.current); stopPendingSearch("stopped"); setRunStatus("cancelled"); setLibraryVersion(value => value + 1); setReportPartial(true); setBusy(false); setStage("idle"); setNotice("Research cancelled. Any findings below are partial.");
    } catch (error) { setProblem(error instanceof Error ? error.message : "Could not cancel research."); }
  };

  const openSource = async (id: string, sourceRunId = runId) => {
    sourceRequest.current?.abort();
    const request = new AbortController(); sourceRequest.current = request;
    const source = sourceRunId === runId ? sources.find((item) => item.id === id) : undefined;
    if (source?.text) { setSourceDrawer(source); return; }
    if (!sourceRunId) return;
    try {
      const response = await fetch(`/api/research/runs/${encodeURIComponent(sourceRunId)}/sources/${encodeURIComponent(id)}`, { signal: request.signal });
      if (!response.ok) throw new Error("This source excerpt is no longer available. Run the question again to refresh it.");
      const data = await response.json(); if (!request.signal.aborted) setSourceDrawer(data.source || data);
    } catch (error) { if (!request.signal.aborted) setProblem(error instanceof Error ? error.message : "Could not load this source."); }
  };

  const copyReport = async () => {
    try { await navigator.clipboard.writeText(report); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { setProblem("Clipboard access is unavailable. Use Download to save the Markdown report."); }
  };
  const downloadReport = () => {
    const url = URL.createObjectURL(new Blob([report], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `research-${runId?.slice(0, 8) || "report"}.md`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const orbState: OrbState = voiceState === "speaking" ? "speaking" : busy ? stage : voiceState === "listening" ? "listening" : stage;
  const intentAnswer = routing?.answers?.intent as { choice?: string; confidence?: number } | undefined;
  const codeAnswer = routing?.answers?.needs_code as { noul?: number } | undefined;
  const intent = intentAnswer?.choice || String(routing?.intent || "Research");
  const sourceOptions = health?.sources?.length ? health.sources : SOURCE_OPTIONS;
  const connectionLabel = checkingHealth ? "Checking connection" : health?.configured ? "Research connected" : health ? "Setup needed" : "Backend offline";
  const selectExample = (text: string) => { setQuestion(text); questionInput.current?.focus(); };

  return <div className="research-app">
    <a className="research-skip" href="#research-question">Skip to research question</a>
    <header className="research-header">
      <a className="research-brand" href="/" aria-label="Research Orb home"><span className="research-brand-orb" /><span>research<span className="research-brand-light">orb</span><sup>LAB</sup></span></a>
      <nav className="research-nav" aria-label="Workspace navigation"><a href="/research" aria-current="page">Workspace</a><a href="/practice">Voice playground <Icon name="arrow" size={13} /></a></nav>
      <button className="research-new" onClick={newResearch} disabled={busy}>+ New research</button>
    </header>
    <main className="research-main">
      <div className="research-page-heading"><div><p className="research-eyebrow"><span className="research-tiny-spark">✦</span> YOUR VOICE. A DEEPER UNDERSTANDING.</p><h1>Think out loud.<br className="research-mobile-break" /> <span>Follow the evidence.</span></h1><p>From a research question to a sourced answer, with every step in view.</p></div><div className="research-stack"><span>POWERED BY</span><b>Jev <i>×</i> Exa</b></div></div>
      <div className="research-grid">
        <aside className="research-input-column" aria-label="Ask your research assistant">
          <section className="research-orb-panel"><div className="research-panel-top"><span className="research-eyebrow">RESEARCH ASSISTANT</span><span className={`research-live-tag ${busy ? "is-live" : ""}`}><i />{busy ? "WORKING" : voiceState === "listening" || voiceState === "speaking" ? "VOICE LIVE" : "STANDBY"}</span></div>
            <ResearchOrb state={orbState} /><div className="research-orb-copy"><h2>{STATE_LABEL[orbState]}</h2><p>{busy ? "Your question is moving through Jev and the research agents." : "Ask a question. Unpack a paper. Connect the dots."}</p></div>
            <div className="research-voice-slot"><PipecatSession variant="gradium" research compact researchContext={researchContext} onResearchRun={followRun} onVoiceState={setVoiceState} onTranscript={setTranscript} onIntentPreview={handleIntentPreview} onResearchActivity={handleVoiceActivity} onResearchTurnStart={handleResearchTurnStart} /></div>
            <p className="research-provider-note">Gradium voice <span>·</span> General Compute intelligence</p>
          </section>
          <div className={`research-transcript ${transcript ? "has-transcript" : ""}`}><div className="research-transcript-heading"><span className="research-eyebrow">LIVE TRANSCRIPT</span><span>{voiceState === "listening" ? "Listening" : voiceState === "speaking" ? "Assistant speaking" : voiceState === "connecting" ? "Connecting" : "Microphone off"}</span></div><p>{transcript ? `“${transcript}”` : "Your words appear here as you speak. Jev previews the intent before the research agents start."}</p></div>
          <form className="research-composer" onSubmit={submit}>
            <div className="research-section-label"><label htmlFor="research-question">Or start with a question</label><span>TEXT INPUT</span></div>
            <div className="research-input-wrap"><textarea id="research-question" ref={questionInput} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What would you like to investigate?" maxLength={4000} rows={3} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><div className="research-input-actions"><button type="button" className="research-add-source" onClick={() => setShowPaste(!showPaste)} aria-expanded={showPaste}><span>{showPaste ? "−" : "+"}</span> Add excerpt</button><button type="submit" className="research-submit" disabled={busy || !question.trim()}>{busy ? "Researching…" : "Investigate"}<Icon name="arrow" size={17} /></button></div></div>
            {showPaste && <div className="research-paste"><div className="research-paste-heading"><label htmlFor="research-excerpt">Source excerpt</label><select aria-label="Excerpt type" value={pastedKind} onChange={(event) => setPastedKind(event.target.value as "paper" | "code")}><option value="paper">Paper / text</option><option value="code">Code</option></select></div><textarea id="research-excerpt" value={pastedText} onChange={(event) => setPastedText(event.target.value)} placeholder="Paste a paper excerpt or code to analyze alongside the selected sources…" maxLength={24000} rows={5} /><span>{pastedText.length.toLocaleString()} / 24,000 characters · excerpt only</span></div>}
            <label className="research-search-toggle"><input type="checkbox" checked={searchEnabled} onChange={(event) => setSearchEnabled(event.target.checked)} /><span><strong>Search for papers</strong><small>{health?.search?.configured === false ? "Exa needs configuration · supplied sources still work" : "Exa finds papers and extracts readable source text"}</small></span><span className="research-search-provider">EXA</span></label>
            <label className={`research-search-toggle research-prepare-toggle ${!health?.paper2agent?.available ? "is-unavailable" : ""}`}><input type="checkbox" checked={paper2agentEnabled} disabled={busy || !health?.paper2agent?.available} onChange={(event) => setPaper2agentEnabled(event.target.checked)} /><span><strong>Prepare full paper</strong><small>{health?.paper2agent?.available ? "Jev selects up to two arXiv papers · unreviewed drafts" : "Paper2Agent preparation is unavailable on this server"}</small></span><span className="research-search-provider">DRAFT</span></label>
            <div className="research-sources-heading"><span>OPTIONAL PREPARED CONTEXT</span><span>{selectedSources.length + (pastedText.trim() ? 1 : 0)} selected</span></div>
            <div className="research-source-options">{sourceOptions.map((source) => <label className={`research-source-option ${selectedSources.includes(source.id) ? "is-selected" : ""}`} key={source.id}><input type="checkbox" checked={selectedSources.includes(source.id)} onChange={() => setSelectedSources((items) => items.includes(source.id) ? items.filter((id) => id !== source.id) : [...items, source.id])} /><Icon name={source.kind === "code" || source.id.endsWith("code") ? "code" : "paper"} size={16} /><span>{source.title}</span><span className="research-source-check"><Icon name="check" size={12} /></span></label>)}</div>
            <p className="research-scope-note">{searchEnabled ? "Ask about any research topic. Add a paper URL to your question, or supply an excerpt." : "Search is off. Select a prepared source or paste an excerpt to analyze."}</p>
          </form>
          <div className="research-suggestions"><span className="research-eyebrow">A LITTLE CURIOSITY TO GET STARTED</span>{EXAMPLES.map((example) => <button key={example} onClick={() => selectExample(example)} disabled={busy}>{example}<Icon name="arrow" size={14} /></button>)}</div>
        </aside>
        <section className="research-results-column" aria-label="Live research and report">
          <ResearchLibrary sessionId={sessionId} busy={busy} selectedPaperIds={selectedPaperIds} onSelect={setSelectedPaperIds} onResume={resumeSession} onOpenRun={openSavedRun} onDeleteSession={id => { if (id === sessionRef.current) newResearch(); setLibraryVersion(value => value + 1); }} refreshToken={libraryVersion} />
          <ResearchConversation sessionId={sessionId} selectedRunId={runId} currentTurn={!viewingHistory && runId && runQuestion ? { runId, question: runQuestion, markdown: report, status: runStatus, done: reportDone } : undefined} busy={busy} refreshToken={libraryVersion} onOpenRun={openSavedRun} onSource={(id, source) => void openSource(source, id)} />
          {viewingHistory && <div className="research-alert" role="status">Saved conversation report. Ask a follow-up to continue with its paper agents.</div>}
          <div className="research-workflow research-surface" ref={analysisPanel}><div className="research-surface-heading"><h2><span className="research-live-dot" />{viewingHistory ? "Saved analysis" : "Live research"}</h2><span className="research-workflow-meta">{busy ? viewingHistory ? "Loading saved analysis…" : `${elapsed}s elapsed` : reportDone ? reportPartial ? "Partial analysis" : "Analysis complete" : "A clear view of the process"}</span>{busy && runId && !viewingHistory && <button className="research-cancel" onClick={() => void cancel()}>Cancel</button>}</div>
            {!viewingHistory && <div className={`research-live-intent preview-${intentPreview?.phase || "idle"}`}>
              <div className="research-preview-heading"><h3><span className="research-live-dot" />Live intent <span>· provisional</span></h3><span className="research-agent-tag">{previewSubmitted ? "TURN SUBMITTED" : intentPreview?.phase === "pending" ? "UPDATING" : intentPreview?.phase === "ready" ? "LIVE PREVIEW" : intentPreview?.phase === "error" ? "UNAVAILABLE" : "AWAITING SPEECH"}</span></div>
              <p>{previewSubmitted ? "Research turn submitted. The final Jev decision appears below." : intentPreview?.phase === "pending" ? "Jev is evaluating what you’re saying. Keep speaking naturally." : intentPreview?.phase === "error" ? intentPreview.message || "Live intent preview is unavailable. Your completed question can still start research." : intentPreview?.phase === "ready" ? "Jev’s current assessment, based on the words received so far." : "Speak to see Jev identify your request before analysis begins."}</p>
              {intentPreview?.answers && intentPreview.phase !== "error" && <div className="research-preview-values">
                {intentPreview.answers?.intent?.choice && <span><small>REQUEST</small><b>{intentPreview.answers.intent.choice.replace(/_/g, " ")}</b></span>}
                {typeof intentPreview.answers?.intent?.confidence === "number" && <span><small>INTENT CONFIDENCE</small><b>{Math.round(intentPreview.answers.intent.confidence * 100)}%</b></span>}
                {typeof intentPreview.answers?.needs_code?.noul === "number" && <span><small>CODE RELEVANCE</small><b>{intentPreview.answers.needs_code.noul.toFixed(2)}</b></span>}
                {intentPreview.profile && <span><small>PROFILE</small><b>{intentPreview.profile.replace(/_/g, " ")}</b></span>}
              </div>}
              {intentPreview?.transcript && <blockquote>“{intentPreview.transcript}”</blockquote>}
              {intentPreview?.answers && intentPreview.phase !== "error" && <small className="research-preview-note">{previewSubmitted ? "Preview from the completed turn; final routing appears below." : intentPreview.phase === "pending" ? "Showing the last received preview while Jev updates this turn." : "Provisional routing only. The full turn determines the final analysis."}</small>}
            </div>}
            {runQuestion && <p className="research-current-question">{runQuestion}</p>}
            <div className="research-stage-label" role="status">{busy && <span className="research-small-spinner" />}<span>{workLabel}</span></div>
            <div className={`research-routing ${routing ? "has-decision" : ""}`}><div className="research-routing-icon">j<span>·</span></div><div className="research-routing-copy"><div><h3>Jev orchestrator</h3><span className="research-agent-tag">{routing ? "ROUTED" : busy && stage === "routing" ? "CLASSIFYING" : "READY"}</span></div><p>{routing ? `${intent.charAt(0).toUpperCase() + intent.slice(1)} · ${String(routing.profile || "Evidence + critical analysis").replace(/_/g, " ")}` : busy ? "Understanding the request and selecting the right analysis." : "Understands your request and selects the analysis profile."}</p>{routing && <div className="research-routing-values">{typeof intentAnswer?.confidence === "number" && <span>{Math.round(intentAnswer.confidence * 100)}% intent confidence</span>}{typeof codeAnswer?.noul === "number" && <span>Code relevance {codeAnswer.noul.toFixed(2)}</span>}</div>}</div></div>
            {routing && <details className="research-decision"><summary>Inspect Jev decision <span>↗</span></summary><p>Intent confidence describes routing, not the accuracy of the research answer.</p><pre>{JSON.stringify(routing, null, 2)}</pre></details>}
            {searchQuery && <section className="research-search-results" aria-label="Paper search results">
              <div className="research-search-heading"><h3>Paper search <span>EXA</span></h3><span>{searchState === "searching" ? "Searching…" : searchState === "reading" ? "Reading sources…" : searchState === "failed" ? "Search incomplete" : searchState === "stopped" ? "Search stopped" : `${searchResults.length} discovered`}</span></div>
              <p className="research-search-query">“{searchQuery}”</p>
              <div className="research-search-list">{searchResults.map((result) => <article key={result.url} className="research-search-result"><div><a href={/^https?:\/\//.test(result.url) ? result.url : undefined} target="_blank" rel="noopener noreferrer">{result.title || result.url}<Icon name="arrow" size={12} /></a><small>{[result.author, result.publishedDate?.slice(0, 10)].filter(Boolean).join(" · ") || (() => { try { return new URL(result.url).hostname; } catch { return "Discovered source"; } })()}</small></div><span className={`research-search-status status-${result.status}`}>{result.status === "reading" ? "Reading…" : result.status === "extracted" ? "Text extracted" : result.status === "unavailable" ? "No readable text" : result.status === "stopped" ? "Reading stopped" : "Discovered"}</span></article>)}</div>
              <p className="research-search-note">Discovery is separate from analysis. Only extracted text listed under Sources examined is passed to the agents.</p>
            </section>}
            {paperPreparation && <section className={`research-paper-preparation preparation-${paperPreparation.state}`} aria-label="Paper2Agent preparation" aria-live="polite">
              <div className="research-paper-preparation-heading"><h3>Paper2Agent <span>Paper preparation</span></h3><span>{paperPreparation.state === "working" ? <><span className="research-small-spinner" />Preparing</> : paperPreparation.state === "complete" ? paperPreparation.cacheHit ? "Cached draft" : "Draft ready" : paperPreparation.state === "stopped" ? "Stopped" : "Using Exa excerpts"}</span></div>
              {paperPreparation.title && <p className="research-paper-preparation-title">{paperPreparation.title}</p>}
              <p>{paperPreparation.message}</p>
              <small>{paperPreparation.state === "complete" ? "Unreviewed extraction draft. Selected passages inform the analysis; the paper and its claims have not been independently verified." : paperPreparation.state === "working" ? "Preparing the selected paper through Paper2Skill. Each paper agent starts when its evidence is ready." : "Available source excerpts can still be used for the research report."}</small>
            </section>}
            <div className="research-flow-connector"><span /><small>Evidence → analysis → cited report</small><span /></div>
            <div className="research-agent-grid">{Object.keys(paperAgents).length > 0 ? Object.entries(paperAgents).map(([id, agent]) => <AgentCard key={`${runId}-${id}`} id={id} agent={agent} onSource={(source) => void openSource(source)} />) : (["evidence", "critic"] as const).map((id) => <AgentCard key={`${runId || "ready"}-${id}`} id={id} agent={agents[id]} onSource={(source) => void openSource(source)} />)}</div>
            {Object.entries(paperJobs).map(([id, message]) => <p className="research-search-note" key={id}>{message}</p>)}
            {activity.length > 0 && <div className="research-activity" aria-label="Research activity">{activity.slice(-3).map((item, index) => <div key={`${item.at}-${index}`}><span className="research-activity-dot" /><span>{item.label}</span><time>{new Date(item.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div>)}</div>}
          </div>
          {problem && <div className="research-alert research-alert-error" role="alert"><strong>Research needs your attention</strong><p>{problem}</p><button onClick={() => { setProblem(""); void refreshHealth(); questionInput.current?.focus(); }}>Review question & retry ↗</button></div>}
          {notice && <div className="research-alert" role="status">{notice}</div>}
          <article className="research-report research-surface"><div className="research-surface-heading"><h2><Icon name="paper" size={16} />Research report</h2><div className="research-report-tools">{report && <><span className={`research-report-status ${reportDone && !reportPartial ? "is-complete" : ""}`}>{reportDone ? reportPartial ? "PARTIAL" : "COMPLETE" : busy ? "DRAFT" : "PARTIAL"}</span><button className="research-icon-button" title="Copy Markdown" aria-label={copied ? "Markdown copied" : "Copy Markdown"} onClick={() => void copyReport()}><Icon name={copied ? "check" : "copy"} size={15} /></button><button className="research-icon-button" title="Download Markdown" aria-label="Download Markdown" onClick={downloadReport}><Icon name="download" size={16} /></button></>}</div></div>
            {report ? <div className="research-report-content" ref={reportViewport} tabIndex={0} aria-label="Research report content" onScroll={() => { const el = reportViewport.current; if (el) followReport.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90; }}><ResearchMarkdown text={report} onSource={(source) => void openSource(source)} />{busy && !reportDone && <span className="research-writing-cursor" aria-label="Report is streaming" />}</div> : <div className="research-report-empty"><div className="research-empty-document"><span /><span /><span /><span /><i><Icon name="spark" size={19} /></i></div><h3>{busy ? "A thoughtful answer takes evidence." : "Your next insight starts here."}</h3><p>{busy ? `Investigating “${runQuestion || question}”. Your sourced report will appear here as the agents finish their analysis.` : "Ask your first question to turn papers and code into a clear, cited research report."}</p><div className="research-report-features"><span><Icon name="check" size={12} /> Grounded findings</span><span><Icon name="check" size={12} /> Source citations</span><span><Icon name="check" size={12} /> Markdown export</span></div></div>}
            {verification && <div className="research-verification" role="status"><Icon name="spark" size={13} /><span>{verification}</span></div>}
            {sources.length > 0 && <div className="research-read-sources"><div><span className="research-eyebrow">SOURCES EXAMINED</span><span>{sources.length} excerpts</span></div>{sources.map((source) => <button key={source.id} onClick={() => void openSource(source.id)}><span className="research-source-id" title={source.id}>{source.id.startsWith("P") ? source.id.slice(0, 8) : source.id}</span><span>{source.title}<small>{[source.section || source.path || "Read by the research agents", source.coverage].filter(Boolean).join(" · ")}</small></span><Icon name="arrow" size={14} /></button>)}</div>}
            <div className="research-report-footer"><span className="research-shield">◇</span> Citations point to the excerpts actually analyzed. Excerpts may not cover the full paper.</div>
          </article>
        </section>
      </div>
      <footer className="research-footer"><div className={`research-connection ${health?.configured ? "is-connected" : ""}`}><i /><span>{connectionLabel}</span><button onClick={() => void refreshHealth()} disabled={checkingHealth}>Recheck</button></div><span>Jev orchestration <b>·</b> Exa paper search <b>·</b> Built for curiosity</span></footer>
      {!checkingHealth && (!health?.configured || healthProblem) && <div className="research-config-notice"><strong>{healthProblem ? "Start the research backend to run an investigation." : "Connect your providers to start live research."}</strong><span>{healthProblem || (health?.missing?.length ? `Missing configuration: ${health.missing.join(", ")}` : health?.configError || "Check your server configuration.")}</span><span>Your question and source selections stay here while you set up.</span></div>}
    </main>
    {sourceDrawer && <SourceDrawer source={sourceDrawer} onClose={() => setSourceDrawer(null)} />}
  </div>;
}
