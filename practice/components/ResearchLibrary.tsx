"use client";

import { useEffect, useState } from "react";

type Repository = { status?: string; url?: string; commit?: string; evidenceUrl?: string };
type Capabilities = {
  measuredAt?: string; architecture?: string; cpuCount?: number; ramAvailableBytes?: number;
  diskFreeBytes?: number; cudaAvailable?: boolean; isolatedExecutor?: boolean;
  gpu?: { name?: string; vramFreeBytes?: number }[];
};
type PaperJob = { jobId?: string; state?: string; reason?: string; executed?: boolean; repository?: Repository; capabilities?: Capabilities };
type Paper = { paperId: string; title: string; url?: string; coverage?: string; status?: string; jobs?: PaperJob[]; reports?: { runId: string; status?: string }[] };
type SavedRun = { runId: string; question: string; status: string };
type SavedSession = { sessionId: string; title: string; paperCount?: number; latestRunId?: string; updatedAt?: string };
type Session = { sessionId: string; papers: Paper[]; runs: SavedRun[] };
type Props = {
  sessionId: string;
  busy: boolean;
  selectedPaperIds: string[];
  onSelect: (ids: string[]) => void;
  onResume: (sessionId: string, runId?: string) => void;
  onOpenRun: (runId: string) => void;
  refreshToken?: number;
};

const LABELS: Record<string, string> = {
  queued: "Waiting to inspect code", running: "Inspecting code", ready: "Evidence saved",
  "metadata-only": "Waiting for evidence", completed: "Completed", cancelled: "Cancelled",
  interrupted: "Interrupted", failed: "Failed", clarification: "Clarification",
  blocked_compute: "Compute limit", blocked_environment: "Execution unavailable",
  requirements_unknown: "Requirements unknown", unsupported_operation: "No supported experiment",
  eligible: "Ready for a supported operation", "not-found": "No repository found",
  "author-linked": "Author-linked code", "third-party": "Third-party implementation", uncertain: "Unconfirmed code link",
};
const label = (value?: string) => value ? LABELS[value] || value.replaceAll("_", " ") : "Saved";

function safeUrl(value?: string) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}

function bytes(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value / 1024 ** 3).toFixed(1)} GB` : "Not measured";
}

function JobDetails({ job }: { job: PaperJob }) {
  const repository = job.repository;
  const capabilities = job.capabilities;
  const url = safeUrl(repository?.url);
  return <details className="library-job">
    <summary>{label(job.state)}{repository?.status ? ` · ${label(repository.status)}` : ""}</summary>
    <div className="library-job-content">
      {url && <p><a href={url} target="_blank" rel="noopener noreferrer">{url.replace("https://github.com/", "")} ↗</a>
        {repository?.commit && <span> · commit <code title={repository.commit}>{repository.commit.slice(0, 10)}</code></span>}</p>}
      {job.reason && <p>{job.reason}</p>}
      {capabilities && <dl className="library-compute">
        <div><dt>Available RAM</dt><dd>{bytes(capabilities.ramAvailableBytes)}</dd></div>
        <div><dt>Free disk</dt><dd>{bytes(capabilities.diskFreeBytes)}</dd></div>
        <div><dt>GPU</dt><dd>{capabilities.gpu?.map(gpu => gpu.name).filter(Boolean).join(", ") || "None measured"}</dd></div>
        <div><dt>CUDA</dt><dd>{capabilities.cudaAvailable ? "Available" : "Unavailable"}</dd></div>
      </dl>}
      <p className="library-execution-note">{job.executed ? "Execution recorded. See the saved job findings for verification status." : "Experiments have not run. Paper reading remains available."}</p>
    </div>
  </details>;
}

export default function ResearchLibrary({ sessionId, busy, selectedPaperIds, onSelect, onResume, onOpenRun, refreshToken = 0 }: Props) {
  const [session, setSession] = useState<Session | null>(null);
  const [problem, setProblem] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SavedSession[]>([]);
  const [historyProblem, setHistoryProblem] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    let disposed = false;
    let request: AbortController | null = null;
    setSession(current => current?.sessionId === sessionId ? current : null);
    setProblem("");
    const load = async () => {
      request?.abort();
      request = new AbortController();
      try {
        const response = await fetch(`/api/research/sessions/${encodeURIComponent(sessionId)}`, { cache: "no-store", signal: request.signal });
        if (!response.ok) throw new Error("Workspace unavailable");
        const data: Session = await response.json();
        if (!disposed && data.sessionId === sessionId && Array.isArray(data.papers) && Array.isArray(data.runs)) {
          setSession(data);
          setProblem("");
        }
      } catch (error) {
        if (!disposed && !(error instanceof DOMException && error.name === "AbortError")) setProblem("Saved papers are temporarily unavailable. Live research can continue.");
      }
    };
    void load();
    const timer = busy ? setInterval(() => void load(), 3000) : null;
    return () => { disposed = true; request?.abort(); if (timer) clearInterval(timer); };
  }, [sessionId, busy, refreshToken]);

  useEffect(() => {
    if (!historyOpen) return;
    const controller = new AbortController();
    setHistoryProblem("");
    void fetch("/api/research/sessions", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("History unavailable");
        const data = await response.json();
        if (Array.isArray(data.sessions)) setHistory(data.sessions);
      }).catch(error => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setHistoryProblem("Conversation history is temporarily unavailable.");
      });
    return () => controller.abort();
  }, [historyOpen, sessionId, refreshToken]);

  const papers = session?.sessionId === sessionId ? session.papers : [];
  const runs = session?.sessionId === sessionId ? session.runs : [];
  const saved = [...runs].reverse().filter(run => run.status !== "running").slice(0, 6);
  const conversations = history.filter(item => item.sessionId !== sessionId && item.latestRunId);
  const select = (paperId: string) => onSelect(selectedPaperIds.includes(paperId)
    ? selectedPaperIds.filter(id => id !== paperId)
    : [...selectedPaperIds, paperId].slice(0, 2));

  return <section className="research-library" aria-label="Conversation workspace">
    <header className="library-heading">
      <div><span className="research-eyebrow">CONVERSATION WORKSPACE</span><h2>Your paper agents</h2></div>
      <span className="library-count">{papers.length} {papers.length === 1 ? "paper" : "papers"}</span>
    </header>
    <p className="library-hint">{papers.length
      ? "Select a paper to ask a follow-up, or select two and ask to compare them."
      : "Ask a research question to discover papers. Their evidence and reports stay in this conversation."}</p>
    {problem && <p className="library-problem" role="status">{problem}</p>}
    {papers.length > 0 && <div className="library-papers">
      {papers.map(paper => {
        const selected = selectedPaperIds.includes(paper.paperId);
        const latestJob = paper.jobs?.[paper.jobs.length - 1];
        const original = safeUrl(paper.url);
        return <article className={`library-paper${selected ? " library-paper-selected" : ""}`} key={paper.paperId}>
          <label className="library-paper-title">
            <input type="checkbox" checked={selected} disabled={busy || (!selected && selectedPaperIds.length >= 2)} onChange={() => select(paper.paperId)} />
            <span>{paper.title}</span>
          </label>
          <div className="library-paper-meta"><span>{label(paper.status)}</span>{original && <a href={original} target="_blank" rel="noopener noreferrer">Original paper ↗</a>}</div>
          {paper.coverage && <p className="library-coverage">{paper.coverage}</p>}
          {latestJob && <JobDetails job={latestJob} />}
          {!!paper.reports?.length && <button className="library-text-button" disabled={busy} onClick={() => onOpenRun(paper.reports![paper.reports!.length - 1].runId)}>Open latest saved report ↗</button>}
        </article>;
      })}
    </div>}
    {selectedPaperIds.length > 0 && <div className="library-selection"><span>{selectedPaperIds.length} selected for your next question</span><button className="library-text-button" disabled={busy} onClick={() => onSelect([])}>Clear selection</button></div>}
    {!!saved.length && <details className="library-history">
      <summary>Saved reports in this conversation <span>{saved.length}</span></summary>
      <ul>{saved.map(run => <li key={run.runId}><button disabled={busy} onClick={() => onOpenRun(run.runId)}><span>{run.question}</span><small>{label(run.status)}</small></button></li>)}</ul>
    </details>}
    <details className="library-history" onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>Resume a saved conversation</summary>
      {historyOpen && <div>
        {historyProblem && <p className="library-problem" role="status">{historyProblem}</p>}
        {!conversations.length && !historyProblem && <p className="library-hint">No other saved conversations yet.</p>}
        <ul>{conversations.map(item => <li key={item.sessionId}><button disabled={busy} onClick={() => onResume(item.sessionId, item.latestRunId)}><span>{item.title}</span><small>{item.paperCount || 0} papers</small></button></li>)}</ul>
      </div>}
    </details>
    <style jsx>{`
      .research-library { margin: 24px 0; border: 1px solid var(--r-border, #242937); border-radius: 16px; padding: 20px; background: #11151edd; min-width: 0; }
      .library-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
      .library-heading h2 { font-size: 17px; font-weight: 500; margin-top: 5px; }
      .library-count { color: var(--r-muted, #8a91a5); font-size: 12px; white-space: nowrap; }
      .library-hint { color: var(--r-muted, #8a91a5); font-size: 12px; margin: 10px 0 14px; }
      .library-problem { color: #e6b388; font-size: 12px; margin: 12px 0; }
      .library-papers { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 290px), 1fr)); gap: 12px; margin-top: 16px; }
      .library-paper { border: 1px solid #2b3141; border-radius: 12px; padding: 15px; min-width: 0; background: #141925; }
      .library-paper-selected { border-color: #9b8ddd; background: #211d34; }
      .library-paper-title { display: flex; align-items: flex-start; gap: 9px; font-size: 13px; cursor: pointer; line-height: 1.5; overflow-wrap: anywhere; }
      .library-paper-title input { margin: 4px 0 0; accent-color: #b8a8ff; flex-shrink: 0; }
      .library-paper-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px 12px; margin-top: 10px; font-size: 11px; color: #a4afbc; }
      .library-paper-meta a, .library-text-button { color: #beb1ff; }
      .library-coverage { font-size: 11px; color: #9099ad; margin-top: 9px; overflow-wrap: anywhere; }
      .library-text-button { border: 0; background: transparent; padding: 8px 0 0; font-size: 11px; text-align: left; cursor: pointer; }
      .library-selection { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; font-size: 12px; color: #b7acdb; }
      .library-selection button { padding: 0; }
      .library-history { border-top: 1px solid #282d3d; margin-top: 16px; padding-top: 12px; font-size: 12px; }
      .library-history summary { color: #adb3c4; cursor: pointer; }
      .library-history summary span { color: #777f92; margin-left: 8px; }
      .library-history ul { list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 5px; }
      .library-history li button { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; min-width: 0; background: #181d29; color: #c9cddd; padding: 10px 12px; border: 1px solid #282e3e; border-radius: 7px; text-align: left; cursor: pointer; font-size: 12px; }
      .library-history li button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
      .library-history small { color: #929aad; flex-shrink: 0; font-size: 10px; }
      .research-library :global(.library-job) { font-size: 11px; margin-top: 11px; border-top: 1px solid #303346; padding-top: 10px; }
      .research-library :global(.library-job summary) { color: #beb9d5; cursor: pointer; }
      .research-library :global(.library-job-content) { display: grid; gap: 9px; padding-top: 9px; color: #a4aabe; overflow-wrap: anywhere; }
      .research-library :global(.library-job a) { color: #c2b6ff; }
      .research-library :global(.library-compute) { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px; margin: 0; }
      .research-library :global(.library-compute dt) { color: #828ba1; }
      .research-library :global(.library-compute dd) { margin: 0; color: #c5cad9; }
      .research-library :global(.library-execution-note) { color: #9189a7; }
      @media (max-width: 500px) { .research-library { padding: 15px; } .library-selection { align-items: flex-start; } }
    `}</style>
  </section>;
}
