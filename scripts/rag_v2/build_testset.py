#!/usr/bin/env python3
"""Build, validate and freeze the RAG v2 test set from its hand-written source.

Input : scripts/benchmarks/rag_v2/testset_v0.3.src.json  (information needs, 5 languages each)
Corpus: backend/.eval-cache/public_corpus.json            (frozen public snapshot)
Output: scripts/benchmarks/rag_v2/testset_v0.3.json        (one record per question)
        scripts/benchmarks/rag_v2/testset_v0.3.sha256      (hash of the question records)
        scripts/benchmarks/rag_v2/testset_v0.3_review.csv  (sheet for native / domain reviewers)
        scripts/benchmarks/rag_v2/testset_v0.3_termhits.json (other documents containing the key terms)

Validation (any failure exits non-zero, nothing is written):
  * every document prefix resolves to exactly one corpus document;
  * every evidence quote occurs verbatim (after whitespace normalisation) in its document;
  * every evidence document is graded 2 or 1; answerable needs have at least one grade-2 document;
  * unanswerable needs have no relevant document and no evidence;
  * all five languages are present, non-empty, and written in the expected script.

The key-term search is exhaustive over the corpus text (not retriever output), so graders can see
every document that mentions a need's terms and decide whether it deserves a grade.

`--check` re-validates and verifies that the committed JSON still matches the frozen hash.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts/benchmarks/rag_v2/testset_v0.3.src.json"
CORPUS = ROOT / "backend/.eval-cache/public_corpus.json"
OUT_DIR = ROOT / "scripts/benchmarks/rag_v2"
LANGS = ("ko", "en", "id", "vi", "zh-CN")
ANSWERABILITY = {"answerable", "conflicting", "not_in_sources", "unanswerable"}
OVERLAP_LEVELS = ("none", "related", "same_family")

_HANGUL = re.compile(r"[가-힣]")
_HAN = re.compile(r"[一-鿿]")
_VI = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


_MD_MARK = re.compile(r"(?:(?<=\s)|^)#{1,6}(?=\s)")


def norm(text: str) -> str:
    """NFC text with stand-alone markdown heading marks removed and whitespace collapsed.

    The extracted guidebook text carries `## ` marks at PDF line starts, often in the middle of
    a sentence; removing them lets a quote match the sentence. The same function is used to
    decide whether a retrieved passage contains a gold quote (passage-level relevance).
    """
    text = _MD_MARK.sub(" ", unicodedata.normalize("NFC", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def script_ok(lang: str, text: str) -> bool:
    if lang == "ko":
        return bool(_HANGUL.search(text))
    if lang == "zh-CN":
        return bool(_HAN.search(text)) and not _HANGUL.search(text)
    if lang == "vi":
        return bool(_VI.search(text))
    # en / id: Latin script, no Hangul or Han
    return not _HANGUL.search(text) and not _HAN.search(text)


def build(src: dict, corpus: list[dict]) -> tuple[list[dict], dict, list[str]]:
    errors: list[str] = []
    docs = {d["id"]: d for d in corpus}
    texts = {d["id"]: norm(f"{d.get('title', '')}\n{d.get('content', '')}") for d in corpus}

    def resolve(prefix: str, where: str) -> str | None:
        hits = [i for i in docs if i.startswith(prefix)]
        if len(hits) != 1:
            errors.append(f"{where}: prefix {prefix!r} matches {len(hits)} documents")
            return None
        return hits[0]

    records: list[dict] = []
    termhits: dict[str, dict] = {}
    seen = set()
    for need in src["needs"]:
        nid = need["id"]
        if nid in seen:
            errors.append(f"{nid}: duplicate id")
        seen.add(nid)
        ans = need["answerability"]
        if ans not in ANSWERABILITY:
            errors.append(f"{nid}: bad answerability {ans!r}")

        relevant: dict[str, int] = {}
        for prefix, grade in need["relevant"].items():
            full = resolve(prefix, nid)
            if full:
                if grade not in (1, 2):
                    errors.append(f"{nid}: grade {grade} for {prefix} (only 1 or 2 are listed)")
                relevant[full] = grade

        evidence = []
        for ev in need["evidence"]:
            full = resolve(ev["doc"], nid)
            if not full:
                continue
            q = norm(ev["quote"])
            if q not in texts[full]:
                errors.append(f"{nid}: quote not found in {ev['doc']}: {ev['quote'][:70]!r}")
            if full not in relevant:
                errors.append(f"{nid}: evidence document {ev['doc']} has no grade")
            evidence.append({"document_id": full, "quote": q})

        ov = need.get("overlap") or {}
        if ov.get("level") not in OVERLAP_LEVELS or (ov.get("level") != "none") != bool(ov.get("with")):
            errors.append(f"{nid}: overlap must be one of {OVERLAP_LEVELS} and name the dev/validation scenarios")
        if ans in ("answerable", "conflicting") and 2 not in relevant.values():
            errors.append(f"{nid}: {ans} need without a grade-2 document")
        if ans == "unanswerable" and (relevant or evidence):
            errors.append(f"{nid}: unanswerable need lists relevant documents or evidence")
        if ans == "conflicting" and sum(1 for g in relevant.values() if g == 2) < 2:
            errors.append(f"{nid}: conflicting need needs two grade-2 documents")

        # exhaustive key-term search over the whole corpus
        hits: dict[str, list[str]] = {}
        for term in need["key_terms"]:
            t = norm(term).casefold()
            hits[term] = sorted(i[:8] for i, txt in texts.items() if t in txt.casefold())
        unlisted = sorted({h for v in hits.values() for h in v} - {i[:8] for i in relevant})
        termhits[nid] = {"terms": hits, "mentioning_but_ungraded": unlisted}

        for lang in LANGS:
            text = (need["q"].get(lang) or "").strip()
            if not text:
                errors.append(f"{nid}: missing {lang} question")
                continue
            if not script_ok(lang, text):
                errors.append(f"{nid}: {lang} question is not in the expected script: {text!r}")
            records.append({
                "id": f"{nid}-{lang}",
                "need_id": nid,
                "language": lang,
                "question": text,
                "topic": need["topic"],
                "difficulty": need["difficulty"],
                "types": need["types"],
                "answerability": ans,
                "source_language": need["source_language"],
                "relevant": relevant,
                "primary_documents": sorted(i for i, g in relevant.items() if g == 2),
                "evidence": evidence,
                "reference_answer": need["reference_answer"],
                "grading_notes": need.get("grading_notes", ""),
                "overlap_with_dev_validation": need["overlap"],
                "split": "test",
                "label_origin": "ai_drafted_from_corpus",
                "review_status": "draft_unreviewed",
            })
    return records, termhits, errors


def records_hash(records: list[dict]) -> str:
    blob = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="validate and compare with the frozen hash; write nothing")
    args = ap.parse_args()

    src = json.loads(SRC.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus_sha = file_sha256(CORPUS)
    if not corpus_sha.startswith(src["corpus_sha256_16"]):
        print(f"corpus hash {corpus_sha[:16]} != source {src['corpus_sha256_16']}", file=sys.stderr)
        return 2

    records, termhits, errors = build(src, corpus)
    if errors:
        print("VALIDATION FAILED:", *errors, sep="\n  ", file=sys.stderr)
        return 1
    digest = records_hash(records)
    version = src["dataset_version"]
    out_json = OUT_DIR / "testset_v0.3.json"
    out_hash = OUT_DIR / "testset_v0.3.sha256"

    if args.check:
        frozen = out_hash.read_text().split()[0]
        on_disk = records_hash(json.loads(out_json.read_text(encoding="utf-8"))["questions"])
        ok = frozen == digest == on_disk
        print(f"{'OK' if ok else 'MISMATCH'} frozen={frozen[:16]} rebuilt={digest[:16]} on_disk={on_disk[:16]}")
        return 0 if ok else 3

    payload = {
        "dataset_version": version,
        "split": "test",
        "frozen": True,
        "frozen_before": "any rag-v2 retrieval or answer tuning",
        "created": src["created"],
        "corpus_file": str(CORPUS.relative_to(ROOT)),
        "corpus_sha256": corpus_sha,
        "provenance": src["provenance"],
        "grades": src["grades"],
        "overlap_policy": src["overlap_policy"],
        "questions_sha256": digest,
        "counts": {
            "needs": len(src["needs"]),
            "questions": len(records),
            "by_language": dict(Counter(r["language"] for r in records)),
            "by_answerability": dict(Counter(r["answerability"] for r in records)),
            "by_topic": dict(Counter(r["topic"] for r in records)),
            "by_difficulty": dict(Counter(r["difficulty"] for r in records)),
            "by_type": dict(Counter(t for r in records for t in r["types"])),
            "by_overlap": dict(Counter(r["overlap_with_dev_validation"]["level"] for r in records)),
            "documents_with_grade2": len({d for r in records for d in r["primary_documents"]}),
        },
        "questions": records,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out_hash.write_text(f"{digest}  questions of {out_json.name} ({version})\n")
    (OUT_DIR / "testset_v0.3_termhits.json").write_text(
        json.dumps(termhits, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    titles = {d["id"]: d.get("title", "") for d in corpus}
    with (OUT_DIR / "testset_v0.3_review.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["question_id", "need_id", "language", "question", "answerability", "overlap", "graded_documents",
                    "gold_quotes", "reference_answer", "other_documents_mentioning_terms",
                    "R1_question_natural(y/n)", "R2_same_meaning_as_other_languages(y/n)",
                    "R3_quotes_support_reference(y/n)", "R4_grades_correct(y/n)",
                    "R5_missing_relevant_documents", "R6_answerability_correct(y/n)",
                    "reviewer", "review_date", "notes"])
        for r in records:
            graded = "; ".join(f"{d[:8]}={g} {titles[d][:40]}" for d, g in sorted(r["relevant"].items()))
            quotes = " | ".join(f"[{e['document_id'][:8]}] {e['quote']}" for e in r["evidence"])
            others = ", ".join(termhits[r["need_id"]]["mentioning_but_ungraded"])
            ov = r["overlap_with_dev_validation"]
            w.writerow([r["id"], r["need_id"], r["language"], r["question"], r["answerability"],
                        f"{ov['level']} {' '.join(ov['with'])}".strip(), graded,
                        quotes, r["reference_answer"], others, "", "", "", "", "", "", "", "", ""])
    print(f"wrote {len(records)} questions ({len(src['needs'])} needs), sha256 {digest[:16]}")
    print(json.dumps(payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
