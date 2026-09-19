"""Archive only reproducible practice source, never secrets or runtime data."""
from hashlib import sha256
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parent.parent
excluded = {"node_modules", ".next", ".venv", ".cache", "__pycache__", ".git"}
files = [root / ".gitignore", root / "README.md", root / "voice-ai-hackathon-agent-checklist.md", Path(__file__).resolve()]
for directory in ["practice", "pipecat-readiness"]:
    for file in (root / directory).rglob("*"):
        relative = file.relative_to(root)
        if file.is_symlink() or not file.is_file() or excluded.intersection(relative.parts):
            continue
        if file.name.startswith(".env") and file.name != ".env.example":
            continue
        if file.name.endswith((".tsbuildinfo", ".log")):
            continue
        files.append(file)
# Runbooks are useful in a restore; readiness is excluded to avoid a hash cycle.
files.extend(file for file in (root / "docs").glob("*") if file.is_file() and file.name != "readiness.md" and not file.is_symlink())
files = sorted(files, key=lambda file: str(file.relative_to(root)))
manifest = "".join(f"{sha256(file.read_bytes()).hexdigest()}  {file.relative_to(root)}\n" for file in files)
artifacts = root / "artifacts"
(artifacts / "local").mkdir(parents=True, exist_ok=True)
(artifacts / "source-manifest.sha256").write_text(manifest)
archive = artifacts / "local" / "practice-baseline.tar.gz"
with tarfile.open(archive, "w:gz") as output:
    for file in files:
        output.add(file, arcname=str(file.relative_to(root)), recursive=False)
    output.add(artifacts / "source-manifest.sha256", arcname="artifacts/source-manifest.sha256")
print(f"PASS recorded {len(files)} source files; no secret/runtime directories included.")
print(f"Source manifest SHA-256: {sha256(manifest.encode()).hexdigest()}")
print("Archive: artifacts/local/practice-baseline.tar.gz")
