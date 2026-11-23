"""Validate the PDF body-size fix (extractors_files._body_font_size over all pages) on the real production PDFs.

For every PDF original in research/data/raw_private/pdfs/ (downloaded read-only from private storage; versions.json
lists them) and the guidebook, the PRODUCTION extractor is run twice on the same bytes:
  old  = body size estimated from the first 20 pages, control characters kept (the code before the fix)
  new  = body size estimated from all pages, C0 control characters (InDesign \x07 marks) removed (the fix)
and both outputs go through the production chunker. Ground truth is each page's raw PDF text layer
(page.get_text("text")): the extractor reads the same layer, so every word in it should reach the chunks.

Metrics (per document, old vs new):
  * extraction recall  - share of text-layer words present in the extracted text (multiset)
  * chunk recall       - share of text-layer words present in chunk CONTENT (what is embedded and shown)
  * line accuracy      - share of chunk content lines found verbatim (whitespace-insensitive) in the text layer of
                         the chunk's own pages: recovered text is real PDF text, on the cited page
  * heading share      - share of characters on '#'/'##' lines; distinct headings kept on chunks
  * page references    - pages with text that are cited by at least one chunk
  * chunk statistics   - count, median / p10 characters, share < 100 characters, max tokens
  * table cells        - words inside tables detected by PyMuPDF that reach chunk content
No production data is read or written; the files are local copies.

    cd backend && .venv/bin/python ../research/scripts/validate_pdf_fix.py
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
PRIV = ROOT / "research/data/raw_private"
OUT = ROOT / "research/data/experiments/pdf_fix_validation"
GUIDEBOOK_VERSION = "612108fb-e5fa-4d52-be8c-0d6cf440f426"
TOK = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")
WS = re.compile(r"\s+")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def toks(text: str) -> Counter[str]:
    return Counter(t.lower() for t in TOK.findall(text))


def recall(gt: Counter[str], got: Counter[str]) -> float:
    n = sum(gt.values())
    return sum(min(c, got[w]) for w, c in gt.items()) / n if n else 1.0


def missing(gt: Counter[str], got: Counter[str]) -> Counter[str]:
    return Counter({w: c - got[w] for w, c in gt.items() if c > got[w]})


def run_extract(data: bytes, name: str, first_pages_only: bool):
    from app.services.ingestion import extractors_files as ef

    original, strip = ef._body_font_size, ef._strip_controls
    if first_pages_only:   # pre-fix behaviour
        ef._body_font_size = lambda doc, max_pages=None: original(doc, max_pages=20)
        ef._strip_controls = lambda text: text
    try:
        t0 = time.perf_counter()
        ex = ef.extract_pdf(data, name, table_mode="off")
        ms = (time.perf_counter() - t0) * 1000
        doc = ef.open_pdf(data)
        with doc:
            body = ef._body_font_size(doc)
    finally:
        ef._body_font_size, ef._strip_controls = original, strip
    return ex, ms, body


def analyse(ex, pages_gt: dict[int, str], tables_gt: dict[int, list[str]]) -> dict:
    from app.services.chunking import ChunkerConfig, chunk_text
    from app.core.config import Settings

    s = Settings()
    chunks = chunk_text(ex.text, ChunkerConfig(s.chunk_target_tokens, s.chunk_max_tokens, s.chunk_overlap_tokens))
    body_lines = [ln for ln in ex.text.split("\n") if ln.strip() and not re.match(r"^\[Page \d+\]$", ln.strip())]
    head_chars = sum(len(ln) for ln in body_lines if re.match(r"^#{1,6}\s", ln))
    gt_all = Counter()
    for t in pages_gt.values():
        gt_all += toks(t)
    content = "\n".join(c.content for c in chunks)
    with_heading = "\n".join(f"{c.heading or ''}\n{c.content}" for c in chunks)
    # line accuracy: chunk lines must occur verbatim in the text layer of the pages the chunk cites
    nows = {p: WS.sub("", CONTROL.sub("", t)) for p, t in pages_gt.items()}   # \x07 marks are not content
    ok = total = 0
    bad: list[dict] = []
    for c in chunks:
        lo, hi = c.page_start or 1, c.page_end or c.page_start or max(pages_gt)
        layer = "".join(nows.get(p, "") for p in range(lo, hi + 1))
        for ln in c.content.split("\n"):
            ln_n = WS.sub("", CONTROL.sub("", ln))
            if len(ln_n) < 4:
                continue
            total += 1
            if ln_n in layer:
                ok += 1
            elif len(bad) < 8:
                bad.append(dict(page=lo, line=ln[:120]))
    cited = set()
    for c in chunks:
        if c.page_start:
            cited |= set(range(c.page_start, (c.page_end or c.page_start) + 1))
    text_pages = {p for p, t in pages_gt.items() if len(t.strip()) >= 20}
    lens = sorted(len(c.content) for c in chunks)
    cell_gt = Counter()
    for cells in tables_gt.values():
        for cell in cells:
            cell_gt += toks(cell)
    return dict(
        chars=len(ex.text), heading_char_share=round(head_chars / max(1, sum(len(x) for x in body_lines)), 3),
        heading_lines=sum(1 for ln in body_lines if re.match(r"^#{1,6}\s", ln)),
        distinct_chunk_headings=len({c.heading for c in chunks if c.heading}),
        extraction_recall=round(recall(gt_all, toks(ex.text)), 4),
        chunk_recall=round(recall(gt_all, toks(content)), 4),
        chunk_recall_incl_headings=round(recall(gt_all, toks(with_heading)), 4),
        hangul_words_text_layer=sum(c for w, c in gt_all.items() if re.match("[가-힣]", w)),
        hangul_words_in_chunks=sum(min(c, toks(content)[w]) for w, c in gt_all.items() if re.match("[가-힣]", w)),
        line_accuracy=round(ok / total, 4) if total else None, lines_checked=total, unverified_lines=bad,
        table_cell_recall=round(recall(cell_gt, toks(content)), 4) if cell_gt else None,
        pages_with_text=len(text_pages), pages_cited=len(cited & text_pages),
        pages_not_cited=sorted(text_pages - cited),
        chunks=len(chunks), median_chars=statistics.median(lens) if lens else 0,
        p10_chars=lens[len(lens) // 10] if lens else 0, share_under_100=round(sum(n < 100 for n in lens) / len(lens), 3) if lens else 0,
        max_tokens=max((c.token_count for c in chunks), default=0),
        control_chars=sum(len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", c.content)) for c in chunks),
        _chunks=chunks, _gt=gt_all, _content=toks(content),
    )


def ground_truth(data: bytes) -> tuple[dict[int, str], dict[int, list[str]], dict]:
    import pymupdf

    from app.services.ingestion.normalize import normalize_text

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages, tables = {}, {}
    for i, page in enumerate(doc, start=1):
        pages[i] = normalize_text(page.get_text("text"))
        try:
            cells = [str(c) for t in page.find_tables().tables for row in t.extract() for c in row if c]
        except Exception:  # noqa: BLE001
            cells = []
        if cells:
            tables[i] = cells
    return pages, tables, dict(doc.metadata or {}, page_count=doc.page_count)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((PRIV / "pdfs/versions.json").read_text())
    report = dict(fix="extractors_files._body_font_size: character-weighted modal span size over all pages "
                      "(was: first 20 pages)", documents=[])
    examples: list[dict] = []
    for r in rows:
        f = PRIV / "pdfs" / f"{r['version_id']}.pdf"
        if r["version_id"] == GUIDEBOOK_VERSION and not f.exists():
            f = PRIV / "guideBook_ko.pdf"
        data = f.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        assert sha[:16] == r["sha"], f"{f.name}: file differs from the production original"
        pages_gt, tables_gt, meta = ground_truth(data)
        res = {}
        for label, first in (("old", True), ("new", False)):
            ex, ms, body = run_extract(data, r["fname"], first)
            a = analyse(ex, pages_gt, tables_gt)
            a.update(body_size=body, extract_ms=round(ms), text_sha16=hashlib.sha256(ex.text.encode()).hexdigest()[:16])
            a["_text"] = ex.text
            res[label] = a
        old, new = res["old"], res["new"]
        identical = old["text_sha16"] == new["text_sha16"]
        only_controls = hashlib.sha256(CONTROL.sub("", old["_text"]).encode()).hexdigest()[:16] == new["text_sha16"]
        doc_row = dict(version_id=r["version_id"], title=r["title"], file=r["fname"], sha256_16=sha[:16],
                       pages=meta["page_count"], creation_date=meta.get("creationDate"), identical_output=identical,
                       identical_except_control_chars=only_controls,
                       production_chars=r["chars"],
                       old={k: v for k, v in old.items() if not k.startswith("_")},
                       new={k: v for k, v in new.items() if not k.startswith("_")})
        miss = missing(new["_gt"], new["_content"])
        doc_row["new"]["missing_words_top"] = miss.most_common(25)
        doc_row["new"]["missing_words_total"] = sum(miss.values())
        report["documents"].append(doc_row)
        print(f"{r['title'][:28]:30s} pages={meta['page_count']:3d} identical={identical!s:5s} only_ctrl_diff={only_controls!s:5s} "
              f"body {old['body_size']}->{new['body_size']}  chunk_recall {old['chunk_recall']:.3f}->{new['chunk_recall']:.3f} "
              f"line_acc {old['line_accuracy']}->{new['line_accuracy']}  chunks {old['chunks']}->{new['chunks']} "
              f"median {old['median_chars']}->{new['median_chars']}", flush=True)
        if r["version_id"] == GUIDEBOOK_VERSION:
            # recovered passages: new chunk paragraphs whose words were absent from every old chunk
            old_words = old["_content"]
            for c in new["_chunks"]:
                for para in c.content.split("\n\n"):
                    w = toks(para)
                    hangul = [x for x in w if re.match("[가-힣]", x)]
                    if len(hangul) < 12:
                        continue
                    gained = sum(1 for x in hangul if old_words[x] == 0)
                    if gained / len(hangul) >= 0.3:
                        examples.append(dict(page=c.page_start, heading=c.heading, gained_share=round(gained / len(hangul), 2),
                                             text=para[:400]))
            # how the heading tags changed on the guidebook: lines that were '##' before and are body text now
            ex_old, _, _ = run_extract(data, r["fname"], True)
            ex_new, _, _ = run_extract(data, r["fname"], False)
            o_lines = Counter(re.sub(r"^#+\s*", "", ln).strip() for ln in ex_old.text.split("\n") if ln.startswith("#"))
            n_lines = Counter(re.sub(r"^#+\s*", "", ln).strip() for ln in ex_new.text.split("\n") if ln.startswith("#"))
            doc_row["headings_kept_examples"] = [h for h, _ in n_lines.most_common(30)][:30]
            doc_row["lines_untagged_by_fix"] = sum((o_lines - n_lines).values())
            (OUT / "guidebook_old.md").write_text(ex_old.text, encoding="utf-8")
            (OUT / "guidebook_new.md").write_text(ex_new.text, encoding="utf-8")
            doc_row["published_from_pdf_metadata"] = str(ex_new.source_published_at)
    examples.sort(key=lambda e: (-e["gained_share"], e["page"] or 0))
    report["recovered_examples"] = examples[:40]
    report["recovered_paragraphs_total"] = len(examples)
    (OUT / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("recovered paragraphs:", len(examples), "->", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
