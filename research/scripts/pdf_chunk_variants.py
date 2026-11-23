"""Experimental extraction / preprocessing variants of the Korean guidebook PDF (research only; production untouched).

The production text of "한국 유학생 생활 가이드북" (corpus_v2) is fragmented. Investigation (notebook 13) shows the cause is
the PDF extractor, not the chunker: the body font size is estimated from the first 20 pages only (6.2 pt, front
matter and tables), so the real 9.4 pt body text is >= 1.2x that size and 82 % of all characters are tagged as `##`
headings - one heading per visual line - and the heading-aware chunker then starts a new section at every line.

Each variant below produces the guidebook text from the SAME source (the production extracted text, or the same PDF
file verified by SHA-256); every other corpus_v2 document is unchanged. The production chunker (same settings) and
embedding model are then applied by the experiment runner, in a separate local in-memory index.

  C0_existing        production extracted text, unchanged (= corpus_v2)
  C1_merge_short     text-only repair of the production text: remove page furniture (page numbers, running header)
                     and control characters, drop false `##` markers, merge consecutive short fragments within a page
                     until ~400 characters (no access to the PDF needed)
  C2_paragraph       re-extraction from the PDF: wrapped lines of a block re-flowed into one paragraph, page furniture
                     removed by position, no heading markup
  C3_heading         C2 + headings from the corrected body size (char-weighted mode over ALL pages = 9.4 pt):
                     >= 1.4x -> `#`, >= 1.15x (short, single line) -> `##`
  C4_table           C3 + tables (PyMuPDF find_tables) rendered as `| a | b |` rows instead of loose cell lines
  P1_prod_fixed_body the PRODUCTION extractor (extract_pdf) with one change: body size estimated over all pages
                     (candidate minimal production fix; tables off as in production)

    backend/.venv/bin/python research/scripts/pdf_chunk_variants.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
PDF = ROOT / "research/data/raw_private/guideBook_ko.pdf"          # git-ignored; downloaded read-only from Storage
PDF_SHA256 = "8f892bb8dcb08f13fbf32d17315a9fb54e0a1c1f52380b7f53c9dd13b5aaaf79"   # = document_versions.original_file.sha256
CORPUS = ROOT / "backend/.eval-cache/public_corpus_v2.json"
DOC_ID = "d60bc363-0aae-44e5-b0c3-df8c61ad6f66"
OUT = ROOT / "research/data/experiments/chunking"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‍﻿]")
PAGE = re.compile(r"^\[Page (\d+)\]$")
SENT_END = re.compile(r"(다|요|음|함|임|됨|것|[.!?:;)\]>》」』])\s*$")
TITLE = "한국 유학생 생활 가이드북"
TABLE_LOG: list[dict] = []


def clean(t: str) -> str:
    return re.sub(r"[ \t]+", " ", CONTROL.sub("", t)).strip()


# ----------------------------------------------------------------------------------------------- C1 (text only)
def merge_short(text: str, target: int = 400) -> str:
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(" ".join(buf))
            buf.clear()

    seen_header = collections.Counter(re.sub(r"^#+\s*", "", p.strip()) for p in re.split(r"\n\s*\n", text))
    for para in re.split(r"\n\s*\n", text):
        for line in para.split("\n"):
            s = clean(line)
            if not s:
                continue
            if PAGE.match(s):
                flush(); out.append(s); continue
            body = re.sub(r"^#+\s*", "", s)
            if re.fullmatch(r"\d{1,3}", body) or (seen_header[body] >= 8 and len(body) <= 40 and (
                    body.startswith("┃") or body == "외국인 유학생 가이드북")):
                continue                                           # page numbers, running header, chapter tabs
            if s.startswith("# ") and not s.startswith("## ") and len(body) <= 40:
                flush(); out.append(s); continue                    # keep level-1 titles as section headings
            buf.append(body)
            if sum(len(b) for b in buf) >= target and SENT_END.search(body):
                flush()
        # paragraph breaks inside a page are not trusted (they are line breaks in this PDF): keep merging
    flush()
    return "\n\n".join(out)


# ----------------------------------------------------------------------------------------------- PDF variants
def body_size_all_pages(doc) -> float:  # type: ignore[no-untyped-def]
    sizes: collections.Counter[float] = collections.Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip():
                        sizes[round(float(s["size"]), 1)] += len(s["text"])
    return sizes.most_common(1)[0][0]


def furniture(line: dict, page_w: float) -> bool:
    """Page numbers, running header and chapter tabs: printed in the outer margins (x < 6 % or > 90 % of width)."""
    x0 = line["bbox"][0] / page_w
    return x0 < 0.06 or x0 > 0.90


def extract_variant(doc, *, headings: bool, tables: bool) -> str:  # type: ignore[no-untyped-def]
    body = body_size_all_pages(doc)
    parts = [f"# {TITLE}"]
    for pno, page in enumerate(doc, start=1):
        w = page.rect.width
        table_items: list[tuple[tuple[float, ...], str]] = []
        if tables:
            try:
                for t in page.find_tables().tables:
                    rows = [[clean(str(c or "")).replace("|", "/").replace("\n", " ") for c in r] for r in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) < 2:
                        continue
                    md = "\n".join("| " + " | ".join(r) + " |" for r in rows)
                    # validation: PyMuPDF also "finds" tables in framed text boxes and can drop cell text; keep the
                    # table rendering only if it retains >= 95 % of the Hangul printed inside its area
                    inside = "".join("".join(s["text"] for l in b.get("lines", []) for s in l["spans"])
                                     for b in page.get_text("dict")["blocks"] if b["type"] == 0
                                     and b["bbox"][0] >= t.bbox[0] - 1 and b["bbox"][1] >= t.bbox[1] - 1
                                     and b["bbox"][2] <= t.bbox[2] + 1 and b["bbox"][3] <= t.bbox[3] + 1)
                    if hangul(md) >= 0.95 * hangul(inside):
                        table_items.append((tuple(t.bbox), md))
                    else:
                        TABLE_LOG.append(dict(page=pno, kept=False, hangul_table=hangul(md), hangul_area=hangul(inside)))
                        continue
                    TABLE_LOG.append(dict(page=pno, kept=True, rows=len(rows), hangul_table=hangul(md),
                                          hangul_area=hangul(inside)))
            except Exception:  # noqa: BLE001
                table_items = []

        def in_table(bb) -> bool:  # type: ignore[no-untyped-def]
            return any(bb[0] >= a[0] - 1 and bb[1] >= a[1] - 1 and bb[2] <= a[2] + 1 and bb[3] <= a[3] + 1
                       for a, _ in table_items)

        items: list[tuple[float, float, str]] = [(bb[1], bb[0], md) for bb, md in table_items]
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0 or in_table(b["bbox"]):
                continue
            lines = [l for l in b["lines"] if "".join(s["text"] for s in l["spans"]).strip() and not furniture(l, w)]
            if not lines:
                continue
            texts = [clean("".join(s["text"] for s in l["spans"])) for l in lines]
            sizes = [max(s["size"] for s in l["spans"] if s["text"].strip()) for l in lines]
            joined = clean(" ".join(texts))
            if headings and len(lines) <= 2 and len(joined) <= 60 and min(sizes) >= body * 1.15 \
                    and not SENT_END.search(joined.rstrip(".")):
                level = "#" if min(sizes) >= body * 1.4 else "##"
                items.append((b["bbox"][1], b["bbox"][0], f"{level} {joined}"))
            else:
                items.append((b["bbox"][1], b["bbox"][0], joined))
        items.sort(key=lambda x: (round(x[0]), x[1]))
        if items:
            parts.append(f"[Page {pno}]\n" + "\n\n".join(t for _, _, t in items))
    return "\n\n".join(parts)


def production_fixed_body(data: bytes) -> str:
    from app.services.ingestion import extractors_files as ef

    original = ef._body_font_size
    ef._body_font_size = lambda doc, max_pages=10_000: original(doc, max_pages=max_pages)  # all pages
    try:
        return ef.extract_pdf(data, "guideBook_ko.pdf").text
    finally:
        ef._body_font_size = original


# ----------------------------------------------------------------------------------------------- main
def hangul(t: str) -> int:
    return len(re.findall(r"[가-힣]", t))


def main() -> None:
    import pymupdf

    data = PDF.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PDF_SHA256, "PDF differs from the production original"
    corpus = json.loads(CORPUS.read_text())
    existing = next(d for d in corpus if d["id"] == DOC_ID)["content"]
    doc = pymupdf.open(stream=data, filetype="pdf")
    variants = {
        "C0_existing": existing,
        "C1_merge_short": merge_short(existing),
        "C2_paragraph": extract_variant(doc, headings=False, tables=False),
        "C3_heading": extract_variant(doc, headings=True, tables=False),
        "C4_table": extract_variant(doc, headings=True, tables=True),
        "P1_prod_fixed_body": production_fixed_body(data),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    base_h = hangul(existing)
    manifest = dict(document_id=DOC_ID, pdf_sha256=PDF_SHA256, base_corpus=CORPUS.name,
                    base_corpus_sha256_16=hashlib.sha256(CORPUS.read_bytes()).hexdigest()[:16],
                    body_size_production_first20=6.2, body_size_all_pages=body_size_all_pages(doc), variants={})
    for name, text in variants.items():
        d = OUT / name
        d.mkdir(exist_ok=True)
        (d / "guidebook.md").write_text(text, encoding="utf-8")
        cor = [dict(x, content=text) if x["id"] == DOC_ID else x for x in corpus]
        (d / "corpus.json").write_text(json.dumps(cor, ensure_ascii=False), encoding="utf-8")
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        manifest["variants"][name] = dict(
            chars=len(text), hangul_chars=hangul(text), hangul_retained_vs_existing=round(hangul(text) / base_h, 4),
            paragraphs=len(paras), heading_paragraphs=sum(p.lstrip().startswith("#") for p in paras),
            pages_marked=len(re.findall(r"^\[Page \d+\]", text, re.M)), control_chars=len(CONTROL.findall(text)),
            sha256_16=hashlib.sha256(text.encode()).hexdigest()[:16])
        print(name, manifest["variants"][name])
    manifest["c4_tables"] = dict(kept=sum(t["kept"] for t in TABLE_LOG), rejected=sum(not t["kept"] for t in TABLE_LOG),
                                 detail=TABLE_LOG)
    (OUT / "variants.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
