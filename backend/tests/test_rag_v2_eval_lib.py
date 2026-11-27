"""The RAG v2 evaluation code is itself tested: metrics, need-level intervals, the test-set freeze."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "rag_v2"))

lib = pytest.importorskip("lib")


def test_strict_and_lenient_document_metrics() -> None:
    rel = {"A": 2, "B": 1}
    m = lib.doc_metrics(["B", "X", "A"], rel)
    assert (m["hit@1"], m["hit@1_len"], m["hit@3"]) == (0.0, 1.0, 1.0)
    assert m["mrr"] == pytest.approx(1 / 3) and m["mrr_len"] == 1.0
    assert m["recall@5"] == 1.0 and m["p@5"] == pytest.approx(2 / 5)
    perfect = lib.doc_metrics(["A", "B"], rel)
    assert perfect["ndcg@10"] == pytest.approx(1.0)


def test_passage_metrics_count_quotes_in_the_retrieved_and_the_context_passages() -> None:
    quotes = [{"document_id": "A", "quote": "fee is KRW 35,000"}, {"document_id": "A", "quote": "within 15 days"}]
    m = lib.passage_metrics(["nothing here", "## The fee is KRW 35,000 for issuance"], ["Report within 15 days."], quotes)
    assert (m["phit@1"], m["phit@3"], m["qrecall@10"]) == (0.0, 1.0, 0.5)
    assert (m["ctx_hit"], m["ctx_qrecall"]) == (1.0, 0.5)


def test_quote_normalisation_ignores_markdown_marks_and_whitespace() -> None:
    assert lib.norm("## 외국인 학생의 경우,\n## 15일 이내") == "외국인 학생의 경우, 15일 이내"


def test_need_level_interval_is_wider_when_language_versions_agree() -> None:
    # 10 needs x 5 identical language versions: resampling questions would pretend 50 independent observations
    rows = [dict(need=f"n{i}", v=float(i % 2)) for i in range(10) for _ in range(5)]
    lo, hi = lib.cluster_ci(rows, "v")
    import random
    import statistics
    rnd = random.Random(7)
    vals = [r["v"] for r in rows]
    means = sorted(statistics.fmean(rnd.choices(vals, k=len(vals))) for _ in range(2000))
    assert hi - lo > (means[1949] - means[50]) * 1.5


def test_paired_difference_of_identical_runs_is_zero() -> None:
    rows = [dict(id=str(i), need=f"n{i // 5}", m=float(i % 3 == 0)) for i in range(40)]
    p = lib.paired(rows, rows, "m")
    assert p["diff"] == 0 and p["ci95"] == [0.0, 0.0] and p["needs_better"] == p["needs_worse"] == 0


def test_the_test_set_is_still_frozen() -> None:
    if not (ROOT / "backend" / ".eval-cache" / "public_corpus.json").exists():
        pytest.skip("corpus snapshot not present (it is not in git)")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "rag_v2" / "build_testset.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_dev_negatives_are_disjoint_from_the_test_set() -> None:
    neg = json.loads((ROOT / "scripts/benchmarks/rag_v2/dev_negatives_v0.1.json").read_text(encoding="utf-8"))["questions"]
    test = json.loads((ROOT / "scripts/benchmarks/rag_v2/testset_v0.3.json").read_text(encoding="utf-8"))["questions"]
    assert not {q["question"] for q in neg} & {q["question"] for q in test}
    assert not {q["need_id"] for q in neg} & {q["need_id"] for q in test}
    assert all(q["answerability"] == "unanswerable" and not q["relevant"] for q in neg)
