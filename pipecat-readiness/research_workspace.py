"""Small, durable conversation workspaces; SQLite is the source of truth.

No model-generated summary is treated as evidence. Exact source excerpts stay in
run snapshots and paper records, while bounded memory is only conversation context.
The runner batches calls to save_run rather than writing for each streamed token.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
TERMINAL_EVENTS = {"run.completed", "run.cancelled", "run.failed"}
TERMINAL_STATES = {"completed", "failed", "cancelled", "interrupted", "clarification"}
SOURCE_KEYS = {"id", "title", "url", "text", "kind", "packId", "coverage", "author", "authors",
               "publishedDate", "sha256", "sourceSha256", "artifactId", "pageCount", "preparationStatus",
               "candidateId", "candidateIds", "originResultId", "arxivId", "links", "lineStart", "lineEnd",
               "startLine", "endLine", "path", "version", "paperId", "sourceId", "textStatus",
               "section", "passages", "description"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid workspace identifier.")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(source):
    """Group arXiv revisions as a paper; distinguish their excerpt citations."""
    url = str(source.get("url") or "")
    parsed = urlsplit(url)
    version = str(source.get("version") or "")
    if parsed.hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|pdf|html)/((?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7}))(v\d+)?(?:\.pdf)?/?", parsed.path)
        if match:
            return "arxiv:" + match[1], match[2] or version
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        canonical = urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))
        return canonical, version
    return "text:" + sha256(str(source.get("text", "")).encode()).hexdigest(), version


class WorkspaceStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "state.sqlite", timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=15000")
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', summarized_through INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL, status TEXT NOT NULL, snapshot TEXT NOT NULL,
                    UNIQUE(session_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), role TEXT NOT NULL, content TEXT NOT NULL,
                    status TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(run_id, role)
                );
                CREATE TABLE IF NOT EXISTS papers (
                    session_id TEXT NOT NULL REFERENCES sessions(id), paper_id TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL, metadata TEXT NOT NULL, source TEXT NOT NULL,
                    PRIMARY KEY(session_id, paper_id)
                );
                CREATE TABLE IF NOT EXISTS paper_answers (
                    session_id TEXT NOT NULL, paper_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    content TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, findings TEXT NOT NULL,
                    PRIMARY KEY(session_id, paper_id, run_id),
                    FOREIGN KEY(session_id, paper_id) REFERENCES papers(session_id, paper_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    session_id TEXT NOT NULL, paper_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    body TEXT NOT NULL, updated TEXT NOT NULL, PRIMARY KEY(session_id, job_id),
                    FOREIGN KEY(session_id, paper_id) REFERENCES papers(session_id, paper_id)
                );
                CREATE INDEX IF NOT EXISTS message_session ON messages(session_id, id);
                CREATE INDEX IF NOT EXISTS run_session ON runs(session_id, created);
            """)
        self._recover()

    def close(self):
        with self.lock:
            self.db.close()

    def _path(self, *parts):
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Workspace path leaves the storage root.")
        return path

    def session_path(self, session_id):
        """Validated directory for registered worker artifacts, never a browser path."""
        self.ensure_session(session_id)
        return self._path("sessions", _id(session_id))

    def job_path(self, session_id, paper_id, job_id):
        self._paper(session_id, paper_id)
        path = self._path("sessions", _id(session_id), "papers", _id(paper_id), "jobs", _id(job_id))
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _atomic(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Check after directory creation as well; existing symlinks cannot escape.
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Workspace path leaves the storage root.")
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def ensure_session(self, session_id):
        session_id = _id(session_id)
        with self.lock, self.db:
            now = _now()
            self.db.execute("INSERT OR IGNORE INTO sessions(id,created,updated) VALUES(?,?,?)", (session_id, now, now))
            path = self._path("sessions", session_id)
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return {"sessionId": session_id, "createdAt": row["created"], "updatedAt": row["updated"],
                    "summary": row["summary"], "summarizedThroughMessageId": row["summarized_through"]}

    def begin_run(self, run_id, session_id, question, request_id, fingerprint):
        run_id, session_id = _id(run_id), _id(session_id)
        if not isinstance(question, str) or not 1 <= len(question) <= 4000:
            raise ValueError("A bounded question is required.")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 160:
            raise ValueError("A request ID is required.")
        with self.lock:
            self.ensure_session(session_id)
            existing = self.find_request(session_id, request_id)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("This request ID belongs to a different question.")
                return existing
            now = _now()
            snapshot = {"id": run_id, "runId": run_id, "sessionId": session_id, "question": question,
                        "requestId": request_id, "fingerprint": fingerprint, "createdAt": now,
                        "updatedAt": now, "status": "running", "done": False, "cancelled": False,
                        "markdown": "", "sources": {}, "sourceIds": [], "events": [], "seq": 0}
            with self.db:
                self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", (run_id, session_id, request_id,
                    fingerprint, now, now, "running", _json({k: v for k, v in snapshot.items() if k != "events"})))
                self.db.execute("INSERT INTO messages(session_id,run_id,role,content,status,created) VALUES(?,?,?,?,?,?)",
                                (session_id, run_id, "user", question, "committed", now))
                self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now, session_id))
            return snapshot

    def find_request(self, session_id, request_id):
        with self.lock:
            row = self.db.execute("SELECT id FROM runs WHERE session_id=? AND request_id=?", (_id(session_id), request_id)).fetchone()
            return self.get_run(row["id"]) if row else None

    def get_run(self, run_id):
        with self.lock:
            row = self.db.execute("SELECT snapshot FROM runs WHERE id=?", (_id(run_id),)).fetchone()
            if row is None:
                return None
            result = json.loads(row["snapshot"])
            result["events"] = [json.loads(item["body"]) for item in self.db.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
            return result

    def save_run(self, snapshot, events=None):
        """Merge a snapshot and event batch; terminal history is immutable."""
        run_id = _id(snapshot.get("runId") or snapshot.get("id"))
        with self.lock:
            existing = self.get_run(run_id)
            if not existing:
                raise ValueError("Begin the run before saving it.")
            if snapshot.get("sessionId", existing["sessionId"]) != existing["sessionId"]:
                raise ValueError("A run cannot move between sessions.")
            # A late callback must never resurrect an interrupted or completed run.
            if existing.get("done"):
                return existing
            incoming_events = list(events if events is not None else snapshot.get("events", []))
            incoming = {key: value for key, value in snapshot.items() if key != "events"}
            result = dict(existing, **incoming)
            for key in ("id", "runId", "sessionId", "requestId", "fingerprint", "createdAt", "question"):
                result[key] = existing[key]
            result.pop("events", None)
            now, session_id = _now(), existing["sessionId"]
            with self.db:
                for event in incoming_events:
                    seq = event.get("seq")
                    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
                        raise ValueError("A persisted event needs a positive sequence number.")
                    if event.get("runId", run_id) != run_id or event.get("sessionId", session_id) != session_id:
                        raise ValueError("Event does not belong to this run.")
                    event = dict(event, runId=run_id, sessionId=session_id)
                    self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?)", (run_id, seq, _json(event)))
                last = self.db.execute("SELECT body,seq FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
                if last:
                    result["seq"] = last["seq"]
                    event = json.loads(last["body"])
                    if event.get("type") in TERMINAL_EVENTS:
                        result["done"] = True
                        result["cancelled"] = event["type"] == "run.cancelled"
                        result["status"] = event.get("payload", {}).get("status") or event["type"].split(".")[1]
                if result.get("done") and result.get("status") == "running":
                    result["status"] = "cancelled" if result.get("cancelled") else "completed"
                result["updatedAt"] = now
                self.db.execute("UPDATE runs SET snapshot=?,status=?,updated=? WHERE id=?", (_json(result), result["status"], now, run_id))
                self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now, session_id))
                if result.get("done"):
                    answer = result.get("markdown", "")
                    if not answer:
                        terminal = json.loads(last["body"]) if last else {}
                        answer = str(terminal.get("payload", {}).get("message") or "Research ended: " + result["status"] + ".")
                    self.db.execute("INSERT OR IGNORE INTO messages(session_id,run_id,role,content,status,created) VALUES(?,?,?,?,?,?)",
                                    (session_id, run_id, "assistant", answer, result["status"], now))
            if result.get("markdown"):
                name = "report.md" if result.get("done") and result["status"] == "completed" else "partial.md"
                self._atomic(self._path("sessions", session_id, "runs", run_id, name), result["markdown"])
            sources = result.get("sources") or {}
            for source in sources.values() if isinstance(sources, dict) else sources:
                paper_id = source.get("paperId")
                if paper_id and self._paper(session_id, paper_id, required=False):
                    self._atomic(self._path("sessions", session_id, "papers", _id(paper_id), "retrieval", run_id + ".json"),
                                 _json({"runId": run_id, "question": result["question"], "source": source}))
            self._compact(session_id)
            return self.get_run(run_id)

    def save_paper(self, session_id, source):
        self.ensure_session(session_id)
        if not isinstance(source, dict) or not isinstance(source.get("text", ""), str):
            raise ValueError("A paper source must contain text.")
        clean = {key: value for key, value in source.items() if key in SOURCE_KEYS}
        identity, version = _identity(clean)
        paper_id = "paper-" + sha256(identity.encode()).hexdigest()[:20]
        excerpt_hash = sha256(clean.get("text", "").encode()).hexdigest()
        source_id = "P" + sha256((identity + "\0" + version + "\0" + excerpt_hash).encode()).hexdigest()[:24]
        clean.update(id=source_id, sourceId=source_id, paperId=paper_id)
        now = _now()
        paper = {"paperId": paper_id, "sourceId": source_id, "sessionId": session_id, "identity": identity,
                 "version": version, "title": str(clean.get("title") or "Untitled paper")[:500],
                 "url": clean.get("url"), "coverage": clean.get("coverage", "Extracted passages"),
                 "artifactId": clean.get("artifactId"), "preparationStatus": clean.get("preparationStatus"),
                 "candidateIds": clean.get("candidateIds") or ([clean["candidateId"]] if clean.get("candidateId") else []),
                 "status": "ready" if clean.get("text", "").strip() else "metadata-only", "updatedAt": now}
        with self.lock, self.db:
            existing = self._paper(session_id, paper_id, required=False)
            # A rediscovered URL with no text must not erase a previously read
            # paper if its new PDF preparation subsequently fails.
            if existing and existing["source"].get("text", "").strip() and not clean.get("text", "").strip():
                return existing
            paper["createdAt"] = existing["createdAt"] if existing else now
            self.db.execute("INSERT INTO papers VALUES(?,?,?,?,?,?) ON CONFLICT(session_id,paper_id) DO UPDATE SET updated=excluded.updated,metadata=excluded.metadata,source=excluded.source",
                            (session_id, paper_id, paper["createdAt"], now, _json(paper), _json(clean)))
            self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now, session_id))
            self._atomic(self._path("sessions", session_id, "papers", paper_id, "paper.json"), _json(dict(paper, source=clean)))
        return dict(paper, source=clean)

    def _paper(self, session_id, paper_id, required=True):
        with self.lock:
            row = self.db.execute("SELECT metadata,source FROM papers WHERE session_id=? AND paper_id=?",
                                  (_id(session_id), _id(paper_id))).fetchone()
            if not row:
                if required:
                    raise ValueError("Paper does not belong to this session.")
                return None
            return dict(json.loads(row["metadata"]), source=json.loads(row["source"]))

    def paper_sources(self, session_id, paper_ids=None):
        with self.lock:
            if paper_ids is not None:
                if not isinstance(paper_ids, (list, tuple)) or len(paper_ids) > 20:
                    raise ValueError("Select at most twenty paper IDs.")
                return [self._paper(session_id, paper_id)["source"] for paper_id in dict.fromkeys(paper_ids)]
            rows = self.db.execute("SELECT source FROM papers WHERE session_id=? ORDER BY created,paper_id", (_id(session_id),))
            return [json.loads(row["source"]) for row in rows]

    def save_paper_answer(self, session_id, paper_id, run_id, text, status="completed"):
        with self.lock:
            paper = self._paper(session_id, paper_id)
            run = self.get_run(run_id)
            if not run or run["sessionId"] != session_id:
                raise ValueError("Answer run does not belong to this session.")
            citations = sorted(set(re.findall(r"\[(P[a-f0-9]{24}|S\d+)\]", text)))
            findings = {"runId": run_id, "paperId": paper_id, "sourceId": paper["sourceId"],
                        "citationIds": citations, "coverage": paper["coverage"], "status": status,
                        "sourceVersion": paper.get("version", ""),
                        "chunkIds": [passage["chunkId"] for passage in paper["source"].get("passages", [])
                                     if isinstance(passage, dict) and isinstance(passage.get("chunkId"), str)],
                        "verificationStatus": "unverified", "note": text[:2000]}
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO paper_answers VALUES(?,?,?,?,?,?,?)",
                                (session_id, paper_id, _id(run_id), text, status, _now(), _json(findings)))
            saved = self.db.execute("SELECT content,findings FROM paper_answers WHERE session_id=? AND paper_id=? AND run_id=?",
                                    (session_id, paper_id, run_id)).fetchone()
            self._atomic(self._path("sessions", session_id, "papers", paper_id, "reports", run_id + ".md"), saved["content"])
            return json.loads(saved["findings"])

    def save_job(self, session_id, paper_id, job):
        with self.lock:
            self._paper(session_id, paper_id)
            job_id = _id(job.get("jobId") or job.get("id"))
            if job.get("sessionId", session_id) != session_id or job.get("paperId", paper_id) != paper_id:
                raise ValueError("Job does not belong to this paper/session.")
            existing = self.db.execute("SELECT paper_id FROM jobs WHERE session_id=? AND job_id=?", (session_id, job_id)).fetchone()
            if existing and existing["paper_id"] != paper_id:
                raise ValueError("A job cannot move between papers.")
            body = dict(job, jobId=job_id, sessionId=session_id, paperId=paper_id, updatedAt=_now())
            with self.db:
                self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?) ON CONFLICT(session_id,job_id) DO UPDATE SET body=excluded.body,updated=excluded.updated",
                                (session_id, paper_id, job_id, _json(body), body["updatedAt"]))
            self._atomic(self.job_path(session_id, paper_id, job_id) / "job.json", _json(body))
            return body

    def _compact(self, session_id):
        """Incremental extractive memory, preserving all raw turns in SQLite."""
        with self.lock:
            row = self.db.execute("SELECT summary,summarized_through FROM sessions WHERE id=?", (session_id,)).fetchone()
            recent = self.db.execute("SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 6", (session_id,)).fetchall()
            if len(recent) < 6:
                return
            cutoff = recent[-1]["id"]
            older = self.db.execute("SELECT * FROM messages WHERE session_id=? AND id>? AND id<? ORDER BY id",
                                    (session_id, row["summarized_through"], cutoff)).fetchall()
            if not older:
                return
            additions = [f"{item['role']} ({item['status']}): " + " ".join(item["content"].split())[:360] for item in older]
            summary = (row["summary"] + "\n" + "\n".join(additions)).strip()[-3000:]
            with self.db:
                self.db.execute("UPDATE sessions SET summary=?,summarized_through=? WHERE id=?", (summary, older[-1]["id"], session_id))
            self._atomic(self._path("sessions", session_id, "summary.md"), summary)

    def memory(self, session_id, paper_ids=None):
        with self.lock:
            row = self.db.execute("SELECT summary FROM sessions WHERE id=?", (_id(session_id),)).fetchone()
            if row is None:
                return ""
            selected = set(paper_ids) if paper_ids is not None else None
            if selected is not None:
                for paper_id in selected:
                    self._paper(session_id, paper_id)
            messages = self.db.execute("SELECT role,content,status FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 6", (session_id,)).fetchall()
            recent, remaining = [], 6000
            for item in messages:
                line = f"{item['role']} ({item['status']}): {item['content']}"
                text = line[:remaining]
                if text:
                    recent.append(text)
                remaining -= len(text)
                if remaining <= 0:
                    break
            notes, remaining = [], 2000
            answers = self.db.execute("SELECT paper_id,findings FROM paper_answers WHERE session_id=? ORDER BY created DESC LIMIT 30", (session_id,)).fetchall()
            for answer in answers:
                if selected is not None and answer["paper_id"] not in selected:
                    continue
                note = _json(json.loads(answer["findings"]))[:remaining]
                if note:
                    notes.append(note)
                remaining -= len(note)
                if remaining <= 0:
                    break
            return ("Conversation memory only. Prior answers and notes are unverified context, not source evidence.\n"
                    "Earlier turns (extractive summary):\n" + row["summary"][:3000] +
                    "\nRecent turns:\n" + "\n".join(reversed(recent)) +
                    "\nPaper finding notes (retain their status):\n" + "\n".join(notes))

    def session_exists(self, session_id):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM sessions WHERE id=?", (_id(session_id),)).fetchone())

    def delete_session(self, session_id):
        """Remove one inactive workspace and its dependent rows, never shared caches."""
        session_id = _id(session_id)
        with self.lock:
            if not self.db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                return False
            if any(not json.loads(row["snapshot"]).get("done") for row in self.db.execute(
                    "SELECT snapshot FROM runs WHERE session_id=?", (session_id,))):
                raise RuntimeError("Conversation research is still running.")
            if any(json.loads(row["body"]).get("state") in {"queued", "running", "preparing", "cloning", "started"}
                   for row in self.db.execute("SELECT body FROM jobs WHERE session_id=?", (session_id,))):
                raise RuntimeError("Conversation jobs are still running.")
            directory = self._path("sessions", session_id)
            if directory.is_symlink() or directory.parent.is_symlink():
                raise ValueError("Conversation directory cannot be a symbolic link.")
            staged = self._path(".deleted-" + uuid4().hex)
            moved = directory.exists()
            if moved:
                directory.rename(staged)
            try:
                with self.db:
                    for table in ("jobs", "paper_answers", "papers", "messages"):
                        self.db.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
                    self.db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE session_id=?)", (session_id,))
                    self.db.execute("DELETE FROM runs WHERE session_id=?", (session_id,))
                    self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            except Exception:
                if moved:
                    staged.rename(directory)
                raise
            if moved:
                shutil.rmtree(staged)
            return True

    def session(self, session_id, *, before=None, limit=None, create=True):
        with self.lock:
            session_id = _id(session_id)
            if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100):
                raise ValueError("Invalid conversation page size.")
            if before is not None:
                before = _id(before)
                cursor = self.db.execute("SELECT created,id FROM runs WHERE session_id=? AND id=?", (session_id, before)).fetchone()
                if cursor is None:
                    raise ValueError("Invalid conversation history cursor.")
            else:
                cursor = None
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row and not create:
                return {"sessionId": session_id, "summary": "", "papers": [], "runs": [], "messages": [],
                        "totalRuns": 0, "hasMore": False, "nextBefore": None}
            result = self.ensure_session(session_id) if not row else {
                "sessionId": session_id, "createdAt": row["created"], "updatedAt": row["updated"],
                "summary": row["summary"], "summarizedThroughMessageId": row["summarized_through"]}
            papers = []
            for row in self.db.execute("SELECT metadata FROM papers WHERE session_id=? ORDER BY created,paper_id", (session_id,)):
                paper = json.loads(row["metadata"])
                paper["reports"] = [{"runId": item["run_id"], "status": item["status"], "createdAt": item["created"]}
                    for item in self.db.execute("SELECT run_id,status,created FROM paper_answers WHERE session_id=? AND paper_id=? ORDER BY created", (session_id, paper["paperId"]))]
                paper["jobs"] = [json.loads(item["body"]) for item in self.db.execute("SELECT body FROM jobs WHERE session_id=? AND paper_id=? ORDER BY updated", (session_id, paper["paperId"]))]
                papers.append(paper)
            query, parameters = "SELECT snapshot FROM runs WHERE session_id=?", [session_id]
            if cursor:
                query += " AND (created,id) < (?,?)"
                parameters.extend((cursor["created"], cursor["id"]))
            query += " ORDER BY created DESC,id DESC"
            if limit is not None:
                query += " LIMIT ?"
                parameters.append(limit + 1)
            rows = self.db.execute(query, parameters).fetchall()
            has_more = limit is not None and len(rows) > limit
            rows = rows[:limit] if limit is not None else rows
            runs = []
            for row in reversed(rows):
                snapshot = json.loads(row["snapshot"])
                run = {key: snapshot.get(key) for key in ("runId", "sessionId", "question", "status", "createdAt", "updatedAt", "done", "markdown")}
                # Old snapshots did not save this flag, but the terminal event
                # does. Preserve uncertainty when reopening those reports.
                last = self.db.execute("SELECT body FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run["runId"],)).fetchone()
                terminal = json.loads(last["body"]) if last else {}
                run["partial"] = snapshot.get("partial") is True or terminal.get("payload", {}).get("partial") is True
                runs.append(run)
            run_ids = [run["runId"] for run in runs]
            messages = [{"messageId": row["id"], "runId": row["run_id"], "role": row["role"], "content": row["content"],
                         "status": row["status"], "createdAt": row["created"]} for row in self.db.execute(
                "SELECT * FROM messages WHERE session_id=?" +
                (" AND run_id IN (" + ",".join("?" for _ in run_ids) + ")" if limit is not None else "") +
                " ORDER BY id", [session_id, *run_ids] if limit is not None else [session_id])] if run_ids else []
            total = self.db.execute("SELECT COUNT(*) FROM runs WHERE session_id=?", (session_id,)).fetchone()[0]
            return dict(result, papers=papers, runs=runs, messages=messages, totalRuns=total,
                        hasMore=has_more, nextBefore=runs[0]["runId"] if has_more else None)

    def sessions(self):
        with self.lock:
            result = []
            for row in self.db.execute("SELECT * FROM sessions ORDER BY updated DESC LIMIT 50"):
                first = self.db.execute("SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1", (row["id"],)).fetchone()
                latest = self.db.execute("SELECT id,status FROM runs WHERE session_id=? ORDER BY created DESC LIMIT 1", (row["id"],)).fetchone()
                count = self.db.execute("SELECT COUNT(*) FROM papers WHERE session_id=?", (row["id"],)).fetchone()[0]
                result.append({"sessionId": row["id"], "createdAt": row["created"], "updatedAt": row["updated"],
                               "title": first["content"][:160] if first else "New conversation", "paperCount": count,
                               "latestRunId": latest["id"] if latest else None, "status": latest["status"] if latest else "empty"})
            return result

    def _recover(self):
        with self.lock:
            unfinished = self.db.execute("SELECT id FROM runs WHERE status NOT IN ('completed','failed','cancelled','interrupted','clarification')").fetchall()
            for row in unfinished:
                snapshot = self.get_run(row["id"])
                if snapshot.get("done"):
                    continue
                event = {"runId": row["id"], "sessionId": snapshot["sessionId"], "seq": snapshot.get("seq", 0) + 1,
                         "at": _now(), "type": "run.failed", "payload": {"status": "interrupted", "code": "SERVER_RESTARTED",
                         "message": "The server restarted during this research. Saved work is retained; submit a new turn to continue."}}
                snapshot.update(done=True, status="interrupted")
                self.save_run(snapshot, [event])
            rows = self.db.execute("SELECT session_id,paper_id,body FROM jobs").fetchall()
            for row in rows:
                body = json.loads(row["body"])
                if body.get("state") in {"queued", "running", "preparing", "cloning", "started"}:
                    body.update(state="interrupted", reason="The server restarted; this job was not automatically resumed.")
                    self.save_job(row["session_id"], row["paper_id"], body)
