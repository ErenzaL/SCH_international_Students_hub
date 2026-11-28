"""Per-citation support check for generated answers (RAG v2, Phase 7). Deterministic; no model is asked.

`_validate_answer` (engine.py) already removes sentences whose figures appear in NONE of the selected passages. This
step checks the sentences that remain against the sources THEY cite:

  supported      every figure of the sentence (amounts, dates, durations, counts with >= 2 digits) is stated by a
                 cited source
  reattributed   the figures are not in the cited source but all of them are in exactly one other selected source:
                 the marker is replaced by that source's marker (the sentence is kept; the citation now points to the
                 passage that states the number)
  ambiguous      the figures are spread over several other sources or no single source holds all of them: left as
                 written and reported
  uncited        a sentence with figures but without a marker, in an answer that has markers elsewhere: reported only
A sentence without figures is not checked (wording cannot be verified this way). The report is returned with the
answer and logged; it never invents a citation for text that no source supports.
"""
from __future__ import annotations

import re
from typing import Any

_MARK = re.compile(r"\[(\d{1,2})\]")
_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
_LIST = re.compile(r"\s*([-*•]|\d+[.)])\s")


def _numbers(text: str) -> set[str]:
    from app.services.assistant.engine import _NUMBER, _norm_number   # one definition of a figure

    body = re.sub(r"^\s*\d+[.)]\s", "", _MARK.sub("", text))
    return {x for x in (_norm_number(n) for n in _NUMBER.findall(body)) if len(x.replace(".", "")) >= 2}


def _source_numbers(src: dict[str, Any]) -> set[str]:
    from app.services.assistant.engine import _NUMBER, _norm_number

    return {_norm_number(x) for p in src["passages"] for x in _NUMBER.findall(
        f"{p.get('document_title') or ''} {p.get('heading') or ''} {p.get('passage') or ''}")}


def check_citations(answer: str, sources: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Returns (answer with re-attributed markers, report)."""
    have = [_source_numbers(s) for s in sources]
    report: dict[str, Any] = dict(checked=0, supported=0, reattributed=0, ambiguous=0, uncited=0, details=[])
    if not sources or not answer:
        return answer, report
    any_marker = bool(_MARK.search(answer))
    out_lines = []
    for line in answer.split("\n"):
        pieces = [line] if _LIST.match(line) else _SPLIT.split(line)
        fixed = []
        for piece in pieces:
            figs = _numbers(piece)
            cited = [int(m) for m in _MARK.findall(piece) if 1 <= int(m) <= len(sources)]
            if not figs:
                fixed.append(piece)
                continue
            if not cited:
                if any_marker:
                    report["uncited"] += 1
                fixed.append(piece)
                continue
            report["checked"] += 1
            if figs <= set().union(*(have[c - 1] for c in cited)):
                report["supported"] += 1
                fixed.append(piece)
                continue
            holders = [i + 1 for i, h in enumerate(have) if figs <= h]
            if len(holders) == 1:
                new = holders[0]
                piece2 = _MARK.sub("", piece).rstrip()
                piece2 = re.sub(r"\s+([.!?。！？])$", r"\1", piece2)
                end = re.search(r"[.!?。！？]$", piece2)
                piece2 = f"{piece2[:-1]} [{new}]{piece2[-1]}" if end else f"{piece2} [{new}]"
                report["reattributed"] += 1
                report["details"].append(dict(kind="reattributed", from_=cited, to=new, figures=sorted(figs)))
                fixed.append(piece2)
            else:
                report["ambiguous"] += 1
                report["details"].append(dict(kind="ambiguous", cited=cited, figures=sorted(figs), holders=holders))
                fixed.append(piece)
        out_lines.append(" ".join(fixed))
    return "\n".join(out_lines), report
