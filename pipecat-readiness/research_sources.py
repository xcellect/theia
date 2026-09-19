"""Bounded, registered Paper2Agent excerpts; no caller-supplied paths or fetching."""

from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2] / "Paper2Agent"
SKILL = "skills/paper2agent/paper2agent-paper"
REPOSITORY = "https://github.com/jmiao24/Paper2Agent"
PAPER_URL = "https://doi.org/10.1038/s41586-026-11044-y"
SOURCE_REGISTRY = [
    {"id": "paper2agent-paper", "title": "Paper2Agent manuscript", "kind": "paper",
     "description": "Prepared final manuscript and supplement, navigated using the Paper2Agent reading skill."},
    {"id": "paper2agent-code", "title": "Paper2Agent implementation", "kind": "code",
     "description": "Local workflow, verification scripts, and runtime acceptance documentation. Static reading only."},
]
FILES = {
    "paper2agent-paper": [f"{SKILL}/references/paper.md", f"{SKILL}/references/supplement.md"],
    "paper2agent-code": ["README.md", "skills/paper2agent/paper2mcp/SKILL.md",
        "skills/paper2agent/paper2mcp/references/runtime-verification.md",
        "skills/paper2agent/paper2mcp/references/workflow-state.md",
        "skills/paper2agent/paper2mcp/scripts/verify_workflow.py",
        "skills/paper2agent/paper2mcp/scripts/verify_mcp_server.py"],
}
STOP_WORDS = set("a an and are as at be by can do does for from how i in is it its me of on or that the their this to using what which with would you paper2agent agent agents paper papers research code".split())


def prepared_available(root=ROOT):
    return root.is_dir() and (root / SKILL / "references/paper.md").is_file()


def reading_instructions(root=ROOT):
    """Consume the prepared reading package and its navigation index explicitly."""
    return (root / SKILL / "SKILL.md").read_text()[:5000] + "\nNavigation:\n" + (
        root / SKILL / "references/index.md").read_text()[:6000]


def unknown_reference(question):
    for match in re.findall(r"https?://[^\s<>]+", question):
        parsed = urlsplit(match.rstrip(".,);"))
        repository_path = parsed.path.lower().rstrip("/")
        registered = (
            (parsed.hostname == "github.com" and (repository_path == "/jmiao24/paper2agent" or repository_path.startswith("/jmiao24/paper2agent/")))
            or (parsed.hostname in ("doi.org", "www.nature.com") and "s41586-026-11044-y" in parsed.path)
        )
        if not registered:
            return True
    return False


def _passages(text, path):
    """Keep headings and adjacent lines, ignoring headings inside quoted code."""
    lines = text.splitlines()
    section, start, buffer, size, fence = Path(path).name, 1, [], 0, False
    for number, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            fence = not fence
        heading = not fence and re.match(r"^#{1,5}\s+(.+)", line)
        if buffer and ((heading and size > 250) or size + len(line) > 2100):
            yield section, start, number - 1, "\n".join(buffer)[:2300]
            buffer, size, start = [], 0, number
        if heading:
            section = heading.group(1)
        if len(line) > 2300:
            # Extremely long extracted paragraphs are marked as bounded excerpts.
            line = line[:2300] + " […]"
        buffer.append(line)
        size += len(line) + 1
    if buffer:
        yield section, start, len(lines), "\n".join(buffer)[:2300]


def retrieve(question, source_ids, *, pasted_text="", pasted_kind="paper", code_profile=False, root=ROOT):
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{2,}", question.lower())) - STOP_WORDS
    if {"verify", "verifies", "verification", "validated", "validate"} & tokens:
        tokens.update(("test", "tests", "verification", "validate", "reproducibility"))
    candidates = []
    for source_id in source_ids:
        for path in FILES[source_id]:
            for section, start, end, text in _passages((root / path).read_text(), path):
                lower = text.lower()
                score = sum(min(lower.count(token), 5) for token in tokens)
                score += sum(5 for token in tokens if token in section.lower())
                if "overview of paper2agent" in section.lower():
                    score += 5
                if source_id == "paper2agent-code" and code_profile:
                    score += 4
                if section.lower() in ("references", "methods references"):
                    score -= 30
                candidates.append((score, source_id, path, section, start, end, text))
    candidates.sort(key=lambda entry: -entry[0])
    picked = []
    # Include evidence from each selected pack before filling the remaining budget.
    for source_id in source_ids:
        first = next((entry for entry in candidates if entry[1] == source_id), None)
        if first:
            picked.append(first)
    if code_profile and "paper2agent-code" in source_ids:
        # A code-focused analysis must inspect implementation, not only README prose.
        for entry in [item for item in candidates if item[1] == "paper2agent-code" and item[2].endswith(".py")][:2]:
            if entry not in picked:
                picked.append(entry)
    if pasted_text:
        for section, start, end, text in list(_passages(pasted_text, "User supplied excerpt"))[:4]:
            picked.append((100, "pasted", "", f"Pasted {pasted_kind} excerpt", start, end, text))
    for entry in candidates:
        if len(picked) >= 8:
            break
        if entry not in picked:
            picked.append(entry)
    sources, remaining = [], 16000
    for _, pack, path, section, start, end, text in picked[:8]:
        content = text[:remaining]
        if not content.strip():
            break
        remaining -= len(content)
        title = "User supplied excerpt" if pack == "pasted" else next(s["title"] for s in SOURCE_REGISTRY if s["id"] == pack)
        url = None if pack == "pasted" else f"{REPOSITORY}/blob/main/{path}#L{start}-L{end}"
        sources.append({"id": f"S{len(sources) + 1}", "packId": pack, "title": title,
                        "section": section, "text": content, "url": url,
                        "path": f"Paper2Agent/{path}" if path else None,
                        "startLine": start, "endLine": end, "coverage": "Bounded excerpt; no code was executed.",
                        "sha256": sha256(content.encode()).hexdigest()})
    return sources
