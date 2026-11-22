"""Version-controlled assistant prompts.

* ``system_vN.txt``  - the behavioral specification (owner-provided, canonical; used verbatim as the system
  instruction for every model, primary and fallback alike);
* ``response_contract_vN.txt`` - the application contract appended after it: the citation-marker format, the hidden
  assessment block the backend parses, and the statement that tagged runtime data is data. It adds no behavior.

Runtime context (response language, today's date, conversation, retrieved sources) is never part of the system
instruction; the engine sends it in the request as tagged data. Select a prompt with ASSISTANT_PROMPT_VERSION; the
version and a content hash are recorded with every answer and every evaluation run, so prompt versions can be
compared without touching retrieval.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT_VERSION = "system_v2"
CONTRACT_VERSION = "response_contract_v1"   # contract of system_v1 (each prompt uses the contract of its version)
META_MARKER = "<<<META>>>"


@dataclass(frozen=True)
class SystemPrompt:
    version: str
    contract_version: str
    text: str            # what the model receives: specification + contract
    sha256: str          # first 12 hex chars of the hash of `text`


@lru_cache(maxsize=8)
def load_system_prompt(version: str = DEFAULT_PROMPT_VERSION) -> SystemPrompt:
    if not re.fullmatch(r"system_v\d{1,3}", version or ""):
        raise ValueError(f"invalid assistant prompt version {version!r} (expected system_vN)")
    spec_path = PROMPTS_DIR / f"{version}.txt"
    if not spec_path.is_file():
        raise ValueError(f"assistant prompt {version!r} not found at {spec_path}")
    spec = spec_path.read_text(encoding="utf-8").strip()
    contract_version = _contract_for(int(version.removeprefix("system_v")))
    contract = (PROMPTS_DIR / f"{contract_version}.txt").read_text(encoding="utf-8").strip()
    text = f"{spec}\n\n{contract.replace('{META}', META_MARKER)}\n"
    return SystemPrompt(version=version, contract_version=contract_version, text=text,
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])


def _contract_for(n: int) -> str:
    """The contract with the same number as the prompt, else the newest older one."""
    for k in range(n, 0, -1):
        if (PROMPTS_DIR / f"response_contract_v{k}.txt").is_file():
            return f"response_contract_v{k}"
    raise ValueError("no response contract found")
