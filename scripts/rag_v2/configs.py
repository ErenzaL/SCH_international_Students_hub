"""Retrieval configurations of the RAG v2 experiments (one place, so every result file names exactly what ran).

`settings` are overrides of app.core.config.Settings applied on top of the production values of render.yaml
(RETRIEVAL_MIN_SIMILARITY=0.80; everything else at its code default). `mode` is RetrievalService.search's mode.
`hooks` name optional post-processing steps implemented in retrieval_eval.py (none in the baseline).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

PRODUCTION = dict(retrieval_min_similarity=0.80)   # render.yaml; the other retrieval settings are code defaults

CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": dict(mode="hybrid", settings={}, desc="production retrieval: weighted hybrid (vector 1.0, keyword 0.35, "
                     "glossary bridge 0.75), min similarity 0.80, candidate pool 30, at most 3 passages per document"),
    "vector": dict(mode="vector", settings={}, desc="dense only (multilingual-e5-small int8), min similarity 0.80"),
    "keyword": dict(mode="keyword", settings={}, desc="full-text leg only (to_tsvector('simple') + ILIKE + exact terms)"),
    "hybrid_legacy": dict(mode="hybrid_legacy", settings={}, desc="RRF fusion inside the SQL function (before Release A)"),
    "no_bridge": dict(mode="hybrid", settings={"retrieval_bridge_weight": 0.0}, desc="baseline without the glossary bridge"),
    # long documents scaled by (median chunks per document / their chunks) ** beta (RetrievalService, exists, off)
    **{f"hub{b}": dict(mode="hybrid", settings={"retrieval_hub_beta": float(b)},
                       desc=f"baseline + hub scaling beta {b}") for b in ("0.05", "0.1", "0.15", "0.2", "0.25", "0.5", "1.0")},
    # query variants in the assistant stage (production adds en / ko variants through the Gemini rewrite)
    "oracle_en": dict(mode="hybrid", settings={}, variants="oracle_en",
                      desc="upper bound: + the English version of the same need as a second query; bridge off"),
    "oracle_en_ko": dict(mode="hybrid", settings={}, variants="oracle_en_ko",
                         desc="upper bound: + English and Korean versions of the same need; bridge off"),
    "llm_rewrite": dict(mode="hybrid", settings={}, variants="llm_rewrite",
                        desc="the engine's rewrite step with a local model (Qwen 2.5 7B, temperature 0) as a proxy for "
                             "the Gemini Flash-Lite rewrite; bridge off when rewritten"),
    # combinations with the P1 selection (hub scaling 0.1)
    **{f"hub0.1_{v}": dict(mode="hybrid", settings={"retrieval_hub_beta": 0.1}, variants=v,
                           desc=f"hub scaling 0.1 + {v}") for v in ("oracle_en", "oracle_en_ko", "llm_rewrite")},
}


def resolve(name: str) -> dict[str, Any]:
    if name not in CONFIGS:
        raise SystemExit(f"unknown configuration {name!r}; known: {', '.join(CONFIGS)}")
    cfg = dict(CONFIGS[name], name=name)
    cfg.setdefault("hooks", [])
    cfg.setdefault("variants", None)
    cfg["settings"] = dict(PRODUCTION, **cfg["settings"])
    keys = ("mode", "settings", "hooks") + (("variants",) if cfg["variants"] else ())   # older hashes stay valid
    blob = json.dumps({k: cfg[k] for k in keys}, sort_keys=True)
    cfg["hash"] = hashlib.sha256(blob.encode()).hexdigest()[:12]
    return cfg
