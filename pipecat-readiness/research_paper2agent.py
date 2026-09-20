"""Run Paper2Agent's real Paper2Skill converter for one bounded arXiv PDF.

The converter produces an explicitly unreviewed draft. Mechanical verification
is required, but neither these checks nor extraction substitute for page review
or Paper2MCP scientific execution. A completed cache pointer is published only
after every conversion stage succeeds; subprocesses are killed and reaped when
their request is cancelled.
"""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import importlib.util
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urljoin, urlsplit

import httpx


MAX_PDF_BYTES = 20_000_000
MAX_PAGES = 60
MAX_EVIDENCE_CHARS = 16_000
MAX_PACKAGE_CHARS = 8_000
STAGE_TIMEOUT = 45.0
TOTAL_TIMEOUT = 120.0
DOWNLOAD_TIMEOUT = 25.0
PACKAGE_NAME = "research-paper"
ADAPTER_VERSION = "paper2skill-draft-v2"
_SCRIPT_NAMES = ("paper_bundle.py", "pdf_to_skill.py", "reading_package.py")
_STOP_WORDS = frozenset("a an and are as at be by can compare do explain find for from how i in is it me of on or paper papers research show study that the their this to using what which with would".split())


class PreparationError(RuntimeError):
    """Only fixed, safe messages may leave the worker."""


def arxiv_pdf_url(value):
    """Canonicalize supported arXiv IDs; no supplied host is ever fetched."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"arxiv.org", "export.arxiv.org", "ar5iv.labs.arxiv.org", "ar5iv.org", "doi.org", "dx.doi.org"}
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}):
            return None
    except ValueError:
        return None
    path = parsed.path
    if parsed.hostname in {"doi.org", "dx.doi.org"}:
        # Exa's publication index can return the registered arXiv DOI rather
        # than an abs/PDF URL. Only this exact DOI namespace maps to arXiv.
        path = re.sub(r"^/10\.48550/arxiv\.", "/abs/", path, flags=re.I)
        if path == parsed.path:
            return None
    match = re.fullmatch(r"/(?:abs|pdf|html)/((?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})(?:v[1-9]\d*)?)(?:\.pdf)?/?", path)
    return f"https://arxiv.org/pdf/{match[1]}" if match else None


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rank_passages(text, question, budget):
    """Retrieve body evidence without letting URLs or bibliography dominate it."""
    query = re.sub(r"https?://\S+", " ", question.lower())
    def tokens(value):
        return {word[:-1] if len(word) > 4 and word.endswith("s") else word
                for word in re.findall(r"[a-z][a-z0-9-]{2,}", value.lower())} - _STOP_WORDS

    words = tokens(query)
    wants_method = bool(re.search(r"\b(method\w*|approach|architecture|mechanism|how)\b", query))
    wants_limits = bool(re.search(r"\b(limit\w*|weakness\w*|critique|drawback\w*|failure\w*|cost\w*)\b", query))
    method_terms = set("architecture method model attention algorithm mechanism procedure training encoder decoder stack".split())
    limit_terms = set("limitation limit complexity cost scalability failure memory computational constraint bottleneck challenge expensive longer restricted".split())
    lines = text.splitlines()
    blocks, pending, start, heading, excluded_section = [], [], 1, "", False

    def finish(end):
        if not pending or excluded_section:
            return
        content = "\n".join(pending).strip()
        # These are useful document metadata, but not evidence about the method.
        if (not content or re.search(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", content, re.I)
                or re.search(r"(?i)equal contribution|grants? permission|work performed while at|all rights reserved|listing order is random", content)
                or re.match(r"^\s*\[\d+\]\s", content)
                or re.fullmatch(r"\[[^\]]+\]\([^)]*\)", content)
                or (len(content) < 80 and not content.startswith("|"))):
            return
        body_tokens, heading_tokens = tokens(content), tokens(heading)
        method_score = len(method_terms & body_tokens) + 2 * len(method_terms & heading_tokens)
        limit_score = len(limit_terms & body_tokens) + 3 * len(limit_terms & heading_tokens)
        score = 1 + 4 * len(words & body_tokens) + 3 * len(words & heading_tokens)
        score += (method_score if wants_method else 0) + (2 * limit_score if wants_limits else 0)
        if re.search(r"(?i)abstract|conclusion|results?", heading):
            score += 2
        blocks.append({"startLine": start, "endLine": end, "section": heading,
                       "text": content, "score": score, "methodScore": method_score,
                       "limitScore": limit_score})

    for ordinal, line in enumerate(lines, 1):
        heading_match = re.match(r"^\s*#{1,6}\s+(.+)", line)
        plain = re.sub(r"[*_#]", "", line).strip()
        exclusion = bool(re.match(r"(?i)^(?:\d+[. ]+)?(?:references|bibliography|acknowledg(?:e?ments))\b", plain))
        if heading_match:
            finish(ordinal - 1)
            pending, start = [], ordinal + 1
            heading = re.sub(r"[*_]", "", heading_match[1]).strip()
            excluded_section = exclusion
        elif exclusion:
            finish(ordinal - 1)
            pending, start, excluded_section = [], ordinal + 1, True
        elif not line.strip():
            finish(ordinal - 1)
            pending, start = [], ordinal + 1
        else:
            if not pending:
                start = ordinal
            pending.append(line)
    finish(len(lines))

    # Reserve context for distinct requested aspects before filling by relevance.
    # The remaining greedy selection penalizes repeated sections, keeping one
    # long section from using the entire evidence budget.
    priorities = []
    if budget >= 1800:
        abstract = next((block for block in blocks if re.search(r"(?i)\babstract\b", block["section"])), None)
        if abstract:
            priorities.append(abstract)
    for wanted, metric in ((wants_method, "methodScore"), (wants_limits, "limitScore")):
        if wanted and blocks:
            candidate = max(blocks, key=lambda block: (block[metric], block["score"], -block["startLine"]))
            if candidate[metric] > 0 and candidate not in priorities:
                priorities.append(candidate)
    selected, remaining, section_counts = [], max(0, budget), {}
    candidates = list(blocks)
    while candidates:
        if priorities:
            block = priorities.pop(0)
        else:
            block = max(candidates, key=lambda item: (item["score"] / (1 + section_counts.get(item["section"], 0)), -item["startLine"]))
        candidates.remove(block)
        separator = 7 if selected else 0  # '\n\n[…]\n\n'
        if remaining <= separator + 40:
            break
        cap = 1400 if re.search(r"(?i)\babstract\b", block["section"]) else 2400
        content = block["text"][:min(cap, remaining - separator)]
        if not content:
            continue
        selected.append({key: value for key, value in block.items() if key not in {"score", "methodScore", "limitScore"}} |
                        {"text": content, "endLine": block["startLine"] + len(content.splitlines()) - 1})
        remaining -= len(content) + separator
        section_counts[block["section"]] = section_counts.get(block["section"], 0) + 1
    selected.sort(key=lambda block: block["startLine"])
    return "\n\n[…]\n\n".join(block["text"] for block in selected), selected


class Paper2AgentWorker:
    def __init__(self, root: Path, cache_root: Path, python: Path):
        self.root = Path(root).resolve()
        self.cache_root = Path(cache_root).resolve()
        self.python = Path(python).absolute()
        self.scripts = self.root / "skills/paper2agent/paper2skill/scripts"
        self._lock = asyncio.Lock()

    def available(self):
        if not self.python.is_file() or not all((self.scripts / name).is_file() for name in _SCRIPT_NAMES):
            return False
        if self.python.resolve() == Path(sys.executable).resolve():
            return all(importlib.util.find_spec(name) is not None for name in ("pymupdf", "pymupdf4llm", "pypdf", "PIL"))
        return True  # A separately provisioned interpreter is validated by the first stage.

    def _converter_hash(self):
        digest = sha256()
        digest.update(json.dumps({"adapter": ADAPTER_VERSION, "package": PACKAGE_NAME,
            "ocr": "never", "previewDpi": 72, "buildDpi": 90, "maxImageSide": 1400,
            "maxPages": MAX_PAGES}, sort_keys=True).encode())
        for name in _SCRIPT_NAMES:
            digest.update(name.encode())
            digest.update((self.scripts / name).read_bytes())
        digest.update((self.scripts.parent / "SKILL.md").read_bytes())
        return digest.hexdigest()

    async def _download(self, url):
        async with httpx.AsyncClient(follow_redirects=False, timeout=DOWNLOAD_TIMEOUT,
                                     headers={"User-Agent": "ResearchOrb-Paper2Agent/1.0"}) as client:
            for _ in range(4):
                async with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = urljoin(url, response.headers.get("location", ""))
                        canonical = arxiv_pdf_url(target)
                        if not canonical or urlsplit(target).scheme != "https" or not urlsplit(target).path.startswith("/pdf/"):
                            raise PreparationError("The PDF download redirected outside the supported arXiv PDF path.")
                        url = canonical
                        continue
                    if response.status_code != 200:
                        raise PreparationError("arXiv could not provide this PDF. Continuing with the Exa excerpts.")
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > MAX_PDF_BYTES:
                        raise PreparationError("This PDF exceeds the 20 MB preparation limit.")
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > MAX_PDF_BYTES:
                            raise PreparationError("This PDF exceeds the 20 MB preparation limit.")
                        parts.append(part)
                    content = b"".join(parts)
                    if not content.startswith(b"%PDF-"):
                        raise PreparationError("arXiv returned content that is not a PDF. Continuing with the Exa excerpts.")
                    return content
        raise PreparationError("The PDF download redirected too many times.")

    async def _command(self, arguments, work):
        # File-backed output avoids unbounded PIPE buffers from parser warnings.
        # Only the final bounded JSON is read; provider/parser output never enters SSE.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = await asyncio.create_subprocess_exec(str(self.python), *map(str, arguments),
                cwd=str(work), stdout=stdout, stderr=stderr)
            try:
                async with asyncio.timeout(STAGE_TIMEOUT):
                    await process.wait()
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await asyncio.shield(process.wait())
                raise
            if process.returncode != 0:
                raise PreparationError("Paper2Agent could not complete this preparation stage. Continuing with the Exa excerpts.")
            if stdout.tell() > 1_000_000:
                raise PreparationError("Paper2Agent produced an oversized preparation result.")
            stdout.seek(0)
            raw = stdout.read().decode("utf-8", errors="replace").strip()
            # Some PDF dependencies emit plain-text notices before the JSON result.
            for position in [0, *(match.start() for match in re.finditer(r"(?m)^\{", raw))]:
                try:
                    result = json.loads(raw[position:])
                    if isinstance(result, dict):
                        return result
                except ValueError:
                    pass
            raise PreparationError("Paper2Agent returned an unreadable preparation result.")

    def _cached(self, artifact_id, source_hash, converter_hash):
        pointer = self.cache_root / f"{artifact_id}.json"
        if not pointer.is_file():
            return None
        try:
            record = _json(pointer)
            if not isinstance(record, dict) or not isinstance(record.get("object"), str):
                return None
            object_root = (self.cache_root / record["object"]).resolve()
            if not object_root.is_relative_to((self.cache_root / "objects").resolve()):
                return None
            manifest = _json(object_root / "manifest.json")
            if not isinstance(manifest, dict):
                return None
            verification, files = manifest.get("verification"), manifest.get("files")
            if (not isinstance(verification, dict) or not isinstance(files, dict) or not files
                    or not isinstance(manifest.get("sourceUrl"), str)
                    or not isinstance(manifest.get("pdfUrl"), str)
                    or not arxiv_pdf_url(manifest["sourceUrl"])
                    or arxiv_pdf_url(manifest["pdfUrl"]) != manifest["pdfUrl"]
                    or not isinstance(manifest.get("pages"), int) or isinstance(manifest["pages"], bool)
                    or not 1 <= manifest["pages"] <= MAX_PAGES):
                return None
            if (manifest["sourceSha256"] != source_hash or manifest["converterSha256"] != converter_hash
                    or verification.get("mechanical_ok") is not True
                    or verification.get("all_sources_agent_reviewed") is not False
                    or verification.get("status") != "unreviewed"
                    or manifest["status"] != "unreviewed" or manifest.get("package") != PACKAGE_NAME
                    or f"{PACKAGE_NAME}/references/paper.md" not in files):
                return None
            actual_files = {str(path.relative_to(object_root)) for path in (object_root / PACKAGE_NAME).rglob("*") if path.is_file()}
            if set(files) != actual_files:
                return None
            for relative, digest in files.items():
                if not isinstance(relative, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    return None
                path = (object_root / relative).resolve()
                if not path.is_relative_to(object_root) or not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
                    return None
            return object_root, manifest
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def _convert(self, content, source, pdf_url, artifact_id, converter_hash, emit):
        objects = self.cache_root / "objects"
        objects.mkdir(parents=True, exist_ok=True)
        object_root = Path(tempfile.mkdtemp(prefix=f"{artifact_id}-", dir=objects))
        complete = False
        try:
            pdf_path = object_root / "source.pdf"
            pdf_path.write_bytes(content)
            emit("paper2agent.progress", sourceId=source["id"], status="validating", message="Checking PDF size and page count.")
            validation = await self._command(["-c", "import json,sys,pymupdf; d=pymupdf.open(sys.argv[1]); print(json.dumps({'pages':len(d),'encrypted':d.needs_pass})); d.close()", pdf_path], object_root)
            pages = validation.get("pages")
            if validation.get("encrypted") or not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES:
                raise PreparationError("Paper preparation supports unencrypted PDFs of up to 60 pages.")
            review = object_root / "review"
            package = object_root / PACKAGE_NAME
            script = self.scripts / "paper_bundle.py"
            stages = [
                ("snapshot", "Snapshotting the original paper with Paper2Agent.", ["prepare", pdf_path, "--work", review, "--name", PACKAGE_NAME, "--title", str(source.get("title") or "Research paper")[:300], "--main", pdf_path]),
                ("extract", "Extracting paper pages and figures with Paper2Agent.", ["extract", "--work", review, "--ocr", "never", "--preview-dpi", "72"]),
                ("review_queue", "Recording pages that still need visual review.", ["review-aid", "--work", review, "--cell-width", "350", "--cell-height", "475"]),
                ("build", "Building an explicitly unreviewed Paper2Agent reading package.", ["build", "--work", review, "--output", package, "--draft", "--dpi", "90", "--max-image-side", "1400"]),
                ("verify", "Checking package files and source integrity; visual review remains pending.", ["verify", "--work", review]),
            ]
            report = None
            for stage, message, arguments in stages:
                emit("paper2agent.progress", sourceId=source["id"], status=stage, message=message)
                report = await self._command([script, *arguments], object_root)
            if not isinstance(report, dict) or report.get("mechanical_ok") is not True:
                raise PreparationError("The draft failed Paper2Agent's mechanical integrity checks. Continuing with the Exa excerpts.")
            if report.get("status") != "unreviewed" or report.get("all_sources_agent_reviewed") is not False:
                raise PreparationError("Paper2Agent returned an unexpected review status; this paper was not visually reviewed.")
            paper_path = package / "references/paper.md"
            paper = paper_path.read_text(encoding="utf-8")
            if len(paper.strip()) < 120:
                raise PreparationError("The PDF did not produce enough searchable text. Continuing with the Exa excerpts.")
            manifest = {"schemaVersion": 1, "artifactId": artifact_id, "sourceUrl": source["url"],
                        "pdfUrl": pdf_url, "sourceSha256": sha256(content).hexdigest(),
                        "converterSha256": converter_hash, "adapterVersion": ADAPTER_VERSION,
                        "status": report["status"], "pages": pages,
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "package": PACKAGE_NAME, "review": "review", "verification": report,
                        "limitations": ["Draft; no source page has been visually reviewed.",
                                        "OCR is disabled; image-only content is not searchable.",
                                        "No scientific code or Paper2MCP tools were executed."],
                        "files": {str(path.relative_to(object_root)): sha256(path.read_bytes()).hexdigest()
                                  for path in package.rglob("*") if path.is_file()}}
            _write_json(object_root / "manifest.json", manifest)
            # Preserve converter-recorded absolute paths. Publishing only this pointer
            # makes the entire immutable object visible atomically after verification.
            pointer = self.cache_root / f"{artifact_id}.json"
            pending = object_root / "cache-pointer.json"
            _write_json(pending, {"object": str(object_root.relative_to(self.cache_root))})
            os.replace(pending, pointer)
            complete = True
            return object_root, manifest
        finally:
            if not complete:
                shutil.rmtree(object_root, ignore_errors=True)

    def _retrieve(self, source, question, object_root, manifest, budget, retrieval_dir):
        paper = (object_root / manifest["package"] / "references/paper.md").read_text(encoding="utf-8")
        excerpt, passages = _rank_passages(paper, question, budget)
        if len(excerpt) < 120:
            raise PreparationError("No usable paper passages fit the evidence budget. Continuing with the Exa excerpts.")
        artifact_id = manifest["artifactId"]
        for passage in passages:
            passage["chunkId"] = sha256(f"{artifact_id}:{passage['startLine']}:{passage['endLine']}:{passage['text']}".encode()).hexdigest()[:20]
        retrieval = {"question": question[:4000], "sourceId": source["id"],
                     "artifactId": artifact_id, "passages": passages,
                     "excerptSha256": sha256(excerpt.encode()).hexdigest()}
        if retrieval_dir is not None:
            # Conversation questions and selected passages belong to that
            # session's workspace, never the globally shared PDF object cache.
            directory = Path(retrieval_dir)
            directory.mkdir(parents=True, exist_ok=True)
            retrieval_key = sha256(json.dumps(retrieval, sort_keys=True).encode()).hexdigest()
            path = directory / f"retrieval-{retrieval_key}.json"
            temporary = directory / f".{retrieval_key}-{os.getpid()}.tmp"
            _write_json(temporary, retrieval)
            os.replace(temporary, path)
        return dict(source, packId="paper2agent-draft", section="Paper2Agent draft passages",
            text=excerpt, path=None, startLine=None, endLine=None, sha256=sha256(excerpt.encode()).hexdigest(),
            sourceSha256=manifest["sourceSha256"], artifactId=artifact_id, preparationStatus="unreviewed", pageCount=manifest["pages"],
            passages=passages,
            coverage=f"Question-ranked excerpts from a {manifest['pages']}-page PDF converted by Paper2Agent. Draft; visual review incomplete; no scientific code executed.")

    async def retrieve(self, source, question, retrieval_dir=None):
        """Re-rank an integrity-checked cached paper without downloading it again."""
        artifact_id, source_hash = source.get("artifactId"), source.get("sourceSha256")
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in (artifact_id, source_hash)):
            return source
        try:
            async with self._lock:
                cached = self._cached(artifact_id, source_hash, self._converter_hash())
                if cached is None:
                    return source
                return self._retrieve(source, question, *cached, MAX_PACKAGE_CHARS, retrieval_dir)
        except (OSError, ValueError, KeyError, TypeError, PreparationError):
            return source

    async def prepare(self, sources: list, question: str, emit, *, retrieval_dir=None):
        chosen = next(((index, source, arxiv_pdf_url(source.get("url"))) for index, source in enumerate(sources)
                       if arxiv_pdf_url(source.get("url"))), None)
        if not chosen:
            emit("paper2agent.failed", status="unsupported", sourceId=None,
                 message="No arXiv PDF was resolved for this source. Its Exa excerpt can be analyzed, but Paper2Agent has not prepared a PDF for it.")
            return sources
        index, source, pdf_url = chosen
        if not self.available():
            emit("paper2agent.failed", status="unavailable", sourceId=source.get("id"),
                 message="Paper2Agent's local PDF runtime is not installed. Continuing with the Exa excerpts.")
            return sources
        emit("paper2agent.started", sourceId=source["id"], status="downloading",
             message="Preparing one arXiv paper with Paper2Agent; the package will remain an unreviewed draft.")
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                async with self._lock:
                    content = await self._download(pdf_url)
                    source_hash = sha256(content).hexdigest()
                    converter_hash = self._converter_hash()
                    artifact_id = sha256(f"{source_hash}:{converter_hash}".encode()).hexdigest()
                    cached = self._cached(artifact_id, source_hash, converter_hash)
                    cache_hit = cached is not None
                    object_root, manifest = cached or await self._convert(content, source, pdf_url, artifact_id, converter_hash, emit)
                    other_chars = sum(len(item.get("text", "")) for number, item in enumerate(sources) if number != index)
                    budget = min(MAX_PACKAGE_CHARS, max(0, MAX_EVIDENCE_CHARS - other_chars))
                    replacement = self._retrieve(source, question, object_root, manifest, budget, retrieval_dir)
                    result = list(sources)
                    result[index] = replacement
                    emit("paper2agent.completed", sourceId=source["id"], status="unreviewed", artifactId=artifact_id,
                         cacheHit=cache_hit, pages=manifest["pages"], characters=len(replacement["text"]),
                         message="Paper2Agent draft ready. Mechanical integrity checks passed; visual review remains pending.")
                    return result
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            message = "Paper2Agent preparation timed out. Continuing with the Exa excerpts."
        except PreparationError as exc:
            message = str(exc)
        except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
            message = "Paper2Agent preparation was unavailable. Continuing with the Exa excerpts."
        emit("paper2agent.failed", sourceId=source.get("id"), status="failed", message=message)
        return sources
