"""Task 1 diagnostics for the guidebook PDF -> data/experiments/chunking/investigation.json (read by notebook 13).

Separates the possible causes of fragmentation: PDF text extraction (heading tagging, line-level paragraphs), Korean
sentence boundaries, tables / multi-column layout, headers & footers, OCR / encoding, chunking logic and empty
paragraphs. Uses the original PDF (verified SHA-256, git-ignored) and the production extracted text from corpus_v2.

    backend/.venv/bin/python research/scripts/pdf_investigation.py
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research/scripts"))
from pdf_chunk_variants import CORPUS, DOC_ID, OUT, PDF, PDF_SHA256, SENT_END, body_size_all_pages  # noqa: E402

PRODUCTION_META = {   # document_versions.extraction_meta of the guidebook (read-only query, 2026-11-23)
    "extractor": "pymupdf", "pages": 94, "pages_with_text": 91, "empty_pages": [4, 5, 91], "scanned_pages": [4],
    "vector_text_pages": [5], "table_mode": "off", "tables": 0, "hangul_ratio": 0.425, "chars": 84467,
}


def main() -> None:
    import hashlib

    import pymupdf
    from app.services.chunking import ChunkerConfig, chunk_text, parse_segments
    from app.services.ingestion.extractors_files import _body_font_size

    data = PDF.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PDF_SHA256
    doc = pymupdf.open(stream=data, filetype="pdf")
    W = doc[0].rect.width
    est_first20, est_all = _body_font_size(doc), body_size_all_pages(doc)
    first20: collections.Counter[float] = collections.Counter()
    allp: collections.Counter[float] = collections.Counter()
    lines_per_block, twocol_pages, ctrl = [], 0, collections.Counter()
    for i, page in enumerate(doc):
        blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        left = sum(1 for b in blocks if b["bbox"][2] < W * 0.55)
        right = sum(1 for b in blocks if b["bbox"][0] > W * 0.45)
        twocol_pages += left >= 3 and right >= 3
        for b in blocks:
            lines_per_block.append(len(b["lines"]))
            for ln in b["lines"]:
                for s in ln["spans"]:
                    if s["text"].strip():
                        sz = round(float(s["size"]), 1)
                        allp[sz] += len(s["text"])
                        if i < 20:
                            first20[sz] += len(s["text"])
                    for ch in s["text"]:
                        if ord(ch) < 32 or 0x200B <= ord(ch) <= 0x200D or ch == "﻿":
                            ctrl[f"U+{ord(ch):04X}"] += 1
    total = sum(allp.values())
    tagged = sum(v for k, v in allp.items() if k >= 1.2 * est_first20)

    text = next(d for d in json.loads(CORPUS.read_text()) if d["id"] == DOC_ID)["content"]
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    body = [p for p in paras if not p.startswith("[Page")]
    heads = [p for p in body if p.startswith("#")]
    plain = [re.sub(r"^#+\s*", "", p) for p in body]
    rep = collections.Counter(plain)
    segs = parse_segments(text)
    chunks = chunk_text(text, ChunkerConfig(320, 420, 48))
    # chunks whose section heading differs from the previous chunk's -> split forced by a (false) heading
    forced = sum(1 for a, b in zip(chunks, chunks[1:]) if a.heading != b.heading)

    def page_excerpt(p: int, n: int = 700) -> str:
        m = re.search(rf"\[Page {p}\]\n(.*?)(?=\n\[Page \d+\]|\Z)", text, re.S)
        return (m.group(1) if m else "")[:n]

    variants = {}
    for name in ("C3_heading",):
        t = (OUT / name / "guidebook.md").read_text()
        variants[name] = {p: (re.search(rf"\[Page {p}\]\n(.*?)(?=\n\n\[Page \d+\]|\Z)", t, re.S) or [None, ""])[1][:700]
                          for p in (7, 37, 74)}
    out = dict(
        production_extraction_meta=PRODUCTION_META,
        font=dict(body_estimate_production_first20=est_first20, body_estimate_all_pages=est_all,
                  first20_top=[(k, v) for k, v in first20.most_common(6)], all_pages_top=[(k, v) for k, v in allp.most_common(8)],
                  share_chars_tagged_heading=round(tagged / total, 3),
                  heading_threshold_pt=round(1.2 * est_first20, 2)),
        layout=dict(pages=len(doc), two_column_like_pages=twocol_pages, median_lines_per_block=statistics.median(lines_per_block),
                    control_or_zero_width_chars=dict(ctrl), image_only_pages=PRODUCTION_META["empty_pages"]),
        extracted_text=dict(
            chars=len(text), paragraphs=len(body), heading_marked=len(heads),
            heading_marked_over_40_chars=sum(1 for h in heads if len(h) > 40),
            paragraphs_ending_sentence=sum(1 for p in plain if SENT_END.search(p)),
            median_paragraph_chars=statistics.median(len(p) for p in plain),
            paragraphs_under_20_chars=sum(1 for p in plain if len(p) < 20),
            page_number_only=sum(1 for p in plain if re.fullmatch(r"\d{1,3}", p)),
            running_header=rep.get("외국인 유학생 가이드북", 0),
            chapter_tabs=sum(v for k, v in rep.items() if k.startswith("┃")),
            bel_chars=text.count("\x07"), replacement_chars=text.count("�")),
        chunker=dict(segments=len(segs), segments_with_heading=sum(1 for s in segs if s.heading), chunks=len(chunks),
                     chunk_boundaries_at_heading_change=forced,
                     share_boundaries_forced_by_heading=round(forced / max(1, len(chunks) - 1), 3),
                     median_chunk_chars=statistics.median(len(c.content) for c in chunks)),
        examples=dict(production={p: page_excerpt(p) for p in (7, 37, 74)}, **variants),
    )
    (OUT / "investigation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "examples"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
