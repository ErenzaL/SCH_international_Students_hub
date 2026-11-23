"""Corpus snapshot -> input corpus file and result directory for the experiment scripts (RAG_SNAPSHOT env var)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = os.environ.get("RAG_SNAPSHOT", "corpus_v1")
CORPUS = {"corpus_v1": ROOT / "backend/.eval-cache/public_corpus.json",
          "corpus_v2": ROOT / "backend/.eval-cache/public_corpus_v2.json",
          # experimental (notebook 13): corpus_v2 with the guidebook re-extracted by the production extractor with the
          # body-size fix (P1). Not a production snapshot; used only to test whether reranking conclusions hold.
          "corpus_v2_p1": ROOT / "research/data/experiments/chunking/P1_prod_fixed_body/corpus.json"}[SNAPSHOT]
RESULTS = ROOT / "research/data/results" if SNAPSHOT == "corpus_v1" else ROOT / "research/data/results" / SNAPSHOT
RESULTS.mkdir(parents=True, exist_ok=True)
