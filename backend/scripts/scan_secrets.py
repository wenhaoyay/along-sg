"""Fail when source artifacts appear to contain committed credential values."""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {
    ".git", ".venv", "node_modules", ".next", "out", "test-results",
    "playwright-report", "__pycache__", "work", "outputs", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".yaml", ".css", ".html",
    ".yml", ".toml", ".txt", ".example", ".dockerignore", "",
}
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "JWT access token": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
FRONTEND_SECRET_NAMES = re.compile(
    r"ONEMAP_(?:EMAIL|PASSWORD)|OPENAI_API_KEY|BETA_ADMIN_TOKEN|TOMTOM_API_KEY|GEOAPIFY_API_KEY|TAVILY_API_KEY"
)


def main() -> None:
    findings: list[str] = []
    configured = dotenv_values(ROOT / ".env") if (ROOT / ".env").is_file() else {}
    secret_values = [
        str(configured.get(name))
        for name in ("ONEMAP_EMAIL", "ONEMAP_PASSWORD", "OPENAI_API_KEY", "BETA_ADMIN_TOKEN", "TOMTOM_API_KEY", "GEOAPIFY_API_KEY", "TAVILY_API_KEY")
        if configured.get(name) and len(str(configured.get(name))) >= 6
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name == ".env" or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(ROOT)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: {label}")
        if any(value in text for value in secret_values):
            findings.append(f"{relative}: configured server secret value")
        if relative.parts[0] == "frontend" and FRONTEND_SECRET_NAMES.search(text):
            findings.append(f"{relative}: backend secret environment name in frontend")

    bundle = ROOT / "frontend" / "out"
    if bundle.is_dir():
        for path in bundle.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            relative = path.relative_to(ROOT)
            if FRONTEND_SECRET_NAMES.search(text):
                findings.append(f"{relative}: backend secret environment name in bundle")
            if any(value in text for value in secret_values):
                findings.append(f"{relative}: configured server secret value in bundle")
    if findings:
        raise SystemExit("Credential scan failed:\n" + "\n".join(findings))
    print("Credential scan passed: no credential values or backend secret names in frontend.")


if __name__ == "__main__":
    main()
