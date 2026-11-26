"""Every environment variable named in the staging guide is one that something really reads: the API settings (generated
ENVIRONMENT.md), the web app (process.env.*), the staging scripts (os.environ / secret(...)), or Render / glibc (listed with a source)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: read by the platform, not by our code, each with where it is documented
PLATFORM = {"PYTHON_VERSION": "Render: Python version of a native Python service",
            "MALLOC_ARENA_MAX": "glibc malloc tunable, read at process start (RENDER-MEMORY.md)",
            "PORT": "Render: the port the service must listen on"}
WORD = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")


def known() -> set[str]:
    api = set(re.findall(r"^\| `([A-Z0-9_]+)` \|", (ROOT / "docs/owner/ENVIRONMENT.md").read_text(), re.M))
    web = set()
    for f in (ROOT / "apps/web/src").rglob("*.ts*"):
        web |= set(re.findall(r"process\.env\.([A-Z0-9_]+)", f.read_text(errors="ignore")))
    scripts = set()
    for name in ("staging_bootstrap.py", "staging_memory_check.py"):
        scripts |= set(re.findall(r"""(?:environ(?:\.get)?\(|environ\[|secret\()["']([A-Z0-9_]+)["']""", (ROOT / "scripts" / name).read_text()))
    return api | web | scripts | set(PLATFORM)


def test_staging_guide_names_only_real_variables():
    text = (ROOT / "docs/owner/STAGING.md").read_text()
    blocks = re.findall(r"```.*?```", text, re.S)
    named = set()
    for block in blocks:                                   # code blocks first, then the inline code spans of the rest
        named |= set(WORD.findall(block))
    for span in re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S)):
        named |= set(WORD.findall(span))
    named -= {"SAMPLE", "TEST", "DATA", "FETCH_HEAD"}      # label words and a git name, not variables
    unknown = sorted(n for n in named if n not in known() and not n.startswith(("STAGING_REF", "PRODUCTION_REF")))
    assert not unknown, f"STAGING.md names variables nothing reads: {unknown}"


def test_the_guide_covers_every_required_api_variable():
    env = (ROOT / "docs/owner/ENVIRONMENT.md").read_text()
    required = re.findall(r"^\| `([A-Z0-9_]+)` \| [A-Z]+ \| \*\*required\*\*", env, re.M)
    text = (ROOT / "docs/owner/STAGING.md").read_text()
    assert required and all(f"`{r}`" in text for r in required), required
