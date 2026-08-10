"""Fail CI when repository or generated evidence contains credential literals."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
PATTERNS = {
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Odds API literal": re.compile(r"ODDS_API_KEY\s*=\s*[^\s#][^\r\n]{7,}"),
    "API-Football literal": re.compile(r"API_FOOTBALL_KEY\s*=\s*[^\s#][^\r\n]{7,}"),
    "Neon API key": re.compile(r"\bnapi_[A-Za-z0-9_-]{24,}\b"),
    "Neon production DSN": re.compile(
        r"postgresql(?:\+psycopg)?://[^:\s/]+:(?!secret@)[^@\s]+@"
        r"ep-[a-z0-9-]+\.[a-z0-9-]+\.aws\.neon\.tech/[^\s]+"
    ),
    "Chronos generation nonce literal": re.compile(
        r"CHRONOS_CONTROL_PLANE_GENERATION_NONCE\s*=\s*['\"]?[0-9a-fA-F]{64}"
    ),
    "Chronos scoped password literal": re.compile(
        r"CHRONOS_BOOTSTRAP_(?:AUTHORITY|RUNTIME|READER)_PASSWORD\s*=\s*"
        r"(?!\$\{\{)[^\s#][^\r\n]{15,}"
    ),
    "Chronos bootstrap owner DSN literal": re.compile(
        r"NEON_BOOTSTRAP_DATABASE_URL\s*=\s*"
        r"(?!\$\{\{)[^\s#][^\r\n]{15,}"
    ),
}


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    files = {
        ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    }
    for generated_root in (ROOT / ".chronos", ROOT / ".ci", ROOT / "artifacts"):
        if generated_root.is_dir():
            files.update(path for path in generated_root.rglob("*") if path.is_file())
    files.update(path for path in ROOT.glob("*.log") if path.is_file())
    return sorted(files)


def find_secret_literals(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: {label}")
    return findings


def main() -> None:
    findings = find_secret_literals(repository_files())
    if findings:
        raise SystemExit("Secrets potentiels détectés:\n" + "\n".join(findings))
    print("Aucun secret littéral détecté dans le dépôt et ses preuves générées.")


if __name__ == "__main__":
    main()
