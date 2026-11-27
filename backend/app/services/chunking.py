"""Heading/paragraph-aware chunker with token budgets and overlap.

Input is the stored ``extracted_text`` (markdown-ish). Recognised structure:
  * ``#``..``######`` headings -> section boundaries (heading kept on every chunk)
  * ``[Page N]`` marker lines (PDFs) -> page references on chunks
  * blank-line separated paragraphs; consecutive list/numbered lines stay together
Tokens are *estimated* (no tokenizer dependency): Latin words ~1.3 tokens, CJK
characters ~1 token each. The budgets leave headroom under E5's 512-token limit.
Chunks never span documents (the caller chunks one document version at a time).

Versions (``ChunkerConfig.version``):
  v1   a heading line is only ever a section title. A heading line directly followed by another heading line was
       therefore lost: the next one replaced it before any text was attached. Text extracted from PDFs with `## `
       at every line start lost most of its content this way (57.7 % of the Korean guidebook; RAG v2 audit).
  v2   no text is dropped: a heading line that gets no body before the next heading line is kept as body text of
       the enclosing section. Documents without consecutive headings chunk exactly as in v1.
  v2b  v2, and when most non-empty lines of a document are heading lines (`#` marks left by PDF extraction, not
       structure), the marks are ignored and the lines are read as ordinary text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.domain import Chunk, Segment

CHUNKER_VERSION = "v1"          # default; see chunker_version()
CHUNKER_VERSIONS = ("v1", "v2", "v2b")
PSEUDO_HEADING_SHARE = 0.5      # v2b: share of non-empty lines that are heading lines

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_PAGE = re.compile(r"^\[Page (\d+)\]\s*$")
_LIST_LINE = re.compile(r"^\s*(?:[-*•·▪○●]|\d{1,3}[.)]|\(\d{1,3}\)|[①-⑳]|[가-힣][.)])\s+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# sentence boundary: terminator + space, NOT after a digit-dot date/number like "2025.3." or "1."
_SENT = re.compile(r"(?<=[.!?。！？])(?<!\d\.)(?<!\b[A-Za-z]\.)\s+(?=[A-Z가-힣\"'“(\[])|(?<=[다요음함됨임]\.)\s+")


def estimate_tokens(text: str) -> int:
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(_CJK.sub(" ", text)))
    return int(words * 1.3 + cjk + 0.5) or (1 if text.strip() else 0)


def _pseudo_headings(text: str) -> bool:
    lines = [ln for ln in text.split("\n") if ln.strip() and not _PAGE.match(ln)]
    return bool(lines) and sum(1 for ln in lines if _HEADING.match(ln)) / len(lines) > PSEUDO_HEADING_SHARE


def parse_segments(text: str, version: str = "v1") -> list[Segment]:
    """Split stored text into paragraph-level segments carrying heading/page context."""
    segments: list[Segment] = []
    heading: str | None = None
    page: int | None = None
    buf: list[str] = []
    keep = version in ("v2", "v2b")
    as_text = version == "v2b" and _pseudo_headings(text)
    pending: str | None = None        # a heading line that has no body text yet (v2)
    outer: str | None = None          # the heading that was current before `pending`

    def flush() -> None:
        if buf:
            block = "\n".join(buf).strip()
            if block:
                segments.append(Segment(text=block, heading=heading, page=page))
            buf.clear()

    for line in text.split("\n"):
        m_h, m_p = _HEADING.match(line), _PAGE.match(line)
        if m_h and as_text:
            buf.append(m_h.group(2).strip())
        elif m_h:
            flush()
            if keep and pending is not None:
                heading = outer               # the empty heading line becomes text of its enclosing section
                buf.append(pending)
                flush()
            outer = heading
            heading = m_h.group(2).strip()
            pending = heading
        elif m_p:
            flush()
            page = int(m_p.group(1))
        elif not line.strip():
            flush()
        else:
            pending = None
            buf.append(line)
    flush()
    if keep and pending is not None:          # a final heading line without body
        heading = outer
        buf.append(pending)
        flush()
    return segments


def _split_oversized(seg: Segment, max_tokens: int) -> list[Segment]:
    """Split a long paragraph on sentence (or, for lists, item) boundaries; hard-split as a last resort."""
    if estimate_tokens(seg.text) <= max_tokens:
        return [seg]
    lines = seg.text.split("\n")
    units: list[str] = []
    if len(lines) > 1:
        # keep a list item (plus its wrapped continuation lines) together
        cur: list[str] = []
        for ln in lines:
            if _LIST_LINE.match(ln) and cur:
                units.append("\n".join(cur))
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            units.append("\n".join(cur))
    else:
        units = [seg.text]
    flat: list[str] = []
    for u in units:
        flat.extend(_SENT.split(u) if estimate_tokens(u) > max_tokens else [u])
    out: list[Segment] = []
    cur_txt: list[str] = []
    cur_tok = 0
    for piece in flat:
        for sub in _hard_split(piece, max_tokens):
            t = estimate_tokens(sub)
            if cur_txt and cur_tok + t > max_tokens:
                out.append(Segment("\n".join(cur_txt), seg.heading, seg.page))
                cur_txt, cur_tok = [], 0
            cur_txt.append(sub)
            cur_tok += t
    if cur_txt:
        out.append(Segment("\n".join(cur_txt), seg.heading, seg.page))
    return out


def _hard_split(piece: str, max_tokens: int) -> list[str]:
    if estimate_tokens(piece) <= max_tokens:
        return [piece]
    # last resort: split on whitespace without cutting inside a word
    words = piece.split(" ")
    if len(words) == 1:  # one huge unbroken string (e.g. CJK without spaces): cut by characters
        step = max(max_tokens, 1)
        return [piece[i : i + step] for i in range(0, len(piece), step)]
    out, cur = [], []
    for w in words:
        cur.append(w)
        if estimate_tokens(" ".join(cur)) >= max_tokens:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


@dataclass
class ChunkerConfig:
    target_tokens: int = 320
    max_tokens: int = 420
    overlap_tokens: int = 48
    version: str = CHUNKER_VERSION


def chunker_version(config: ChunkerConfig | None) -> str:
    """The value stored in ``document_chunks.chunk_strategy``."""
    v = (config or ChunkerConfig()).version
    if v not in CHUNKER_VERSIONS:
        raise ValueError(f"unknown chunker version {v!r}")
    return v


def _make_chunk(index: int, segs: list[Segment]) -> Chunk:
    body = "\n\n".join(s.text for s in segs)
    pages = [s.page for s in segs if s.page is not None]
    return Chunk(
        index=index, heading=segs[0].heading, content=body, token_count=estimate_tokens(body),
        page_start=min(pages) if pages else None, page_end=max(pages) if pages else None,
    )


def _overlap_tail(segs: list[Segment], budget: int) -> list[Segment]:
    """Trailing whole paragraphs (same section) totalling <= budget tokens."""
    tail: list[Segment] = []
    used = 0
    for s in reversed(segs):
        t = estimate_tokens(s.text)
        if s.heading != segs[-1].heading or used + t > budget:
            break
        tail.insert(0, s)
        used += t
    return tail


def chunk_text(text: str, config: ChunkerConfig | None = None) -> list[Chunk]:
    """Chunk one document's text. Sections never share a chunk; overlap stays inside a section."""
    cfg = config or ChunkerConfig()
    segments: list[Segment] = []
    for seg in parse_segments(text, chunker_version(cfg)):
        segments.extend(_split_oversized(seg, cfg.max_tokens))

    chunks: list[Chunk] = []
    cur: list[Segment] = []
    carried = 0  # leading segments of `cur` that are overlap from the previous chunk
    cur_tok = 0

    for seg in segments:
        t = estimate_tokens(seg.text)
        if cur:
            section_change = seg.heading != cur[-1].heading
            full = cur_tok + t > cfg.max_tokens or cur_tok >= cfg.target_tokens
            if section_change or full:
                if len(cur) > carried:
                    chunks.append(_make_chunk(len(chunks), cur))
                    tail = [] if section_change else _overlap_tail(cur, cfg.overlap_tokens)
                else:
                    tail = []  # only overlap present and the next paragraph still does not fit
                if tail and sum(estimate_tokens(s.text) for s in tail) + t > cfg.max_tokens:
                    tail = []
                cur, carried = list(tail), len(tail)
                cur_tok = sum(estimate_tokens(s.text) for s in cur)
        cur.append(seg)
        cur_tok += t
    if len(cur) > carried:
        chunks.append(_make_chunk(len(chunks), cur))
    return chunks
