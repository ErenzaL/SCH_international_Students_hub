#!/usr/bin/env python3
"""Charts for the RAG v2 reports, drawn as plain SVG from the committed result files (no plotting dependency).

    backend/.venv/bin/python scripts/rag_v2/charts.py      # writes docs/research/rag-v2/figures/*.svg

Palette: the validated default categorical slots 1-2 (blue #2a78d6 / #3987e5 dark, orange #eb6834 / #d95926 dark;
validate_palette.js: all checks pass in both modes). Every mark has a <title> (hover tooltip); the numbers are also in
the report tables. Dark mode uses its own steps via prefers-color-scheme.
"""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "scripts" / "benchmarks" / "results" / "rag_v2"
OUT = ROOT / "docs" / "research" / "rag-v2" / "figures"
STYLE = """<style>
 .bg{fill:#fcfcfb} .t1{fill:#0b0b0b} .t2{fill:#52514e} .grid{stroke:#e4e3df} .axis{stroke:#9a9993}
 .s1{fill:#2a78d6} .s2{fill:#eb6834} .ci{stroke:#0b0b0b} .dot{fill:#52514e} .zero{stroke:#52514e}
 text{font-family:system-ui,-apple-system,'Segoe UI','Noto Sans','Noto Sans CJK KR',sans-serif}
 @media (prefers-color-scheme: dark){ .bg{fill:#1a1a19} .t1{fill:#f0efec} .t2{fill:#c3c2b7} .grid{stroke:#383835}
  .axis{stroke:#6b6a64} .s1{fill:#3987e5} .s2{fill:#d95926} .ci{stroke:#f0efec} .dot{fill:#c3c2b7} .zero{stroke:#c3c2b7} }
</style>"""


def load(name: str) -> dict:
    return json.loads((R / name).read_text(encoding="utf-8"))


def svg(w: int, h: int, body: list[str], title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{escape(title)}">{STYLE}<rect class="bg" width="{w}" height="{h}" rx="6"/>' + "".join(body) + "</svg>")


def bar(x0: float, y: float, w: float, h: float, cls: str, tip: str) -> str:
    """Bar anchored at x0 with a 4px rounded data end."""
    r = min(4.0, w / 2, h / 2)
    d = (f"M{x0:.1f},{y:.1f} H{x0 + w - r:.1f} Q{x0 + w:.1f},{y:.1f} {x0 + w:.1f},{y + r:.1f} V{y + h - r:.1f} "
         f"Q{x0 + w:.1f},{y + h:.1f} {x0 + w - r:.1f},{y + h:.1f} H{x0:.1f} Z")
    return f'<path class="{cls}" d="{d}"><title>{escape(tip)}</title></path>'


def chart_test_context() -> None:
    res = load("T1_test_memory.json")["results"]
    rows = [("RC baseline (no rewrite)", "baseline"), ("hub scaling 0.1", "hub0.1"),
            ("RC + rewrite (local proxy)", "llm_rewrite"), ("hub scaling 0.1 + rewrite", "hub0.1_llm_rewrite")]
    W, left, right, top = 720, 230, 60, 64
    plot = W - left - right
    body = ['<text class="t1" x="20" y="28" font-size="16" font-weight="600">TEST: a gold quote reaches the answer model</text>',
            '<text class="t2" x="20" y="48" font-size="12">share of 190 answerable questions (42 needs × 5 languages); whiskers = 95 % interval over needs</text>']
    for i in range(5):
        x = left + plot * i / 4
        body.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{top + 4 * 40}" stroke-width="1"/>')
        body.append(f'<text class="t2" x="{x:.1f}" y="{top + 4 * 40 + 16}" font-size="11" text-anchor="middle">{i * 25} %</text>')
    for j, (label, cfg) in enumerate(rows):
        o = res[cfg]["overall"]
        v, (lo, hi) = o["ctx_hit"], o["ctx_hit_ci95"]
        y = top + j * 40
        body.append(f'<text class="t1" x="{left - 10}" y="{y + 17}" font-size="13" text-anchor="end">{escape(label)}</text>')
        body.append(bar(left, y + 4, plot * v, 18, "s1", f"{label}: {v:.1%} (95 % {lo:.1%}–{hi:.1%})"))
        body.append(f'<line class="ci" x1="{left + plot * lo:.1f}" x2="{left + plot * hi:.1f}" y1="{y + 13}" y2="{y + 13}" stroke-width="1.5"/>')
        body.append(f'<text class="t1" x="{left + plot * hi + 6:.1f}" y="{y + 17}" font-size="12">{v:.0%}</text>')
    body.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top - 6}" y2="{top + 4 * 40}" stroke-width="1"/>')
    (OUT / "test_context_hit.svg").write_text(svg(W, top + 4 * 40 + 34, body, "TEST: gold quote reaches the answer model"))


def chart_replication() -> None:
    def diff(file: str, b: str, m: str) -> tuple[float, float, float]:
        for c in load(file)["paired_vs_baseline"]:
            if c["b"] == b and c["metric"] == m:
                return c["diff"], c["ci95"][0], c["ci95"][1]
        raise KeyError((file, b, m))

    panels = [("Hub scaling 0.1 − baseline: MRR (selected on DEV/VAL, rejected on TEST)", "hub0.1", "mrr"),
              ("Rewrite proxy − baseline: primary document reaches the answer model", "llm_rewrite", "ctx_doc_hit")]
    splits = [("DEV", "E7_dev_memory.json"), ("VALIDATION", "E7_val_memory.json"), ("TEST", "T1_test_memory.json")]
    W, left, right = 720, 120, 40
    lo_x, hi_x = -0.15, 0.30
    plot = W - left - right

    def X(v: float) -> float:
        return left + plot * (v - lo_x) / (hi_x - lo_x)

    body = ['<text class="t1" x="20" y="28" font-size="16" font-weight="600">Do the effects replicate on the frozen TEST set?</text>',
            '<text class="t2" x="20" y="48" font-size="12">paired difference, 95 % interval over information needs; dashed line = no effect</text>']
    y = 76
    for title, cfg, metric in panels:
        body.append(f'<text class="t1" x="20" y="{y}" font-size="13" font-weight="600">{escape(title)}</text>')
        y0 = y + 12
        for k, (name, f) in enumerate(splits):
            d, lo, hi = diff(f, cfg, metric)
            yy = y0 + k * 26 + 10
            body.append(f'<text class="t1" x="{left - 10}" y="{yy + 4}" font-size="12" text-anchor="end">{name}</text>')
            body.append(f'<line class="ci" x1="{X(lo):.1f}" x2="{X(hi):.1f}" y1="{yy}" y2="{yy}" stroke-width="2"/>')
            body.append(f'<circle class="dot" cx="{X(d):.1f}" cy="{yy}" r="5"><title>{name}: {d:+.3f} [{lo:+.3f}, {hi:+.3f}]</title></circle>')
            body.append(f'<text class="t2" x="{X(hi) + 8:.1f}" y="{yy + 4}" font-size="11">{d:+.3f} [{lo:+.3f}, {hi:+.3f}]</text>')
        body.append(f'<line class="zero" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{y0}" y2="{y0 + 3 * 26 + 4}" stroke-width="1" stroke-dasharray="3 3"/>')
        y = y0 + 3 * 26 + 30
    for v in (-0.1, 0.0, 0.1, 0.2, 0.3):
        body.append(f'<text class="t2" x="{X(v):.1f}" y="{y - 8}" font-size="11" text-anchor="middle">{v:+.1f}</text>')
    (OUT / "replication.svg").write_text(svg(W, y + 4, body, "Replication of effects on TEST"))


def chart_crosslingual() -> None:
    res = load("T1_test_memory.json")["results"]
    groups = [("same language", False), ("cross-language", True)]
    W, left, right, top = 720, 150, 160, 92
    plot = W - left - right
    body = ['<text class="t1" x="20" y="28" font-size="16" font-weight="600">TEST: the rewrite closes most of the cross-language gap</text>',
            '<text class="t2" x="20" y="48" font-size="12">share of answerable questions whose gold quote reaches the answer model</text>',
            f'<rect class="s1" x="20" y="60" width="12" height="12" rx="2"/><text class="t1" x="38" y="70" font-size="12">RC baseline (no rewrite)</text>',
            f'<rect class="s2" x="220" y="60" width="12" height="12" rx="2"/><text class="t1" x="238" y="70" font-size="12">with rewrite (local proxy)</text>']
    for i in range(5):
        x = left + plot * i / 4
        body.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{top + 2 * 64}" stroke-width="1"/>')
        body.append(f'<text class="t2" x="{x:.1f}" y="{top + 2 * 64 + 16}" font-size="11" text-anchor="middle">{i * 25} %</text>')
    for j, (label, flag) in enumerate(groups):
        y = top + j * 64
        body.append(f'<text class="t1" x="{left - 10}" y="{y + 28}" font-size="13" text-anchor="end">{label}</text>')
        for k, (cfg, cls, name) in enumerate((("baseline", "s1", "RC baseline"), ("llm_rewrite", "s2", "with rewrite"))):
            rows = [r for r in res[cfg]["rows"] if r["answerability"] in ("answerable", "conflicting") and r["cross_lingual"] == flag]
            v = sum(r["ctx_hit"] for r in rows) / len(rows)
            yy = y + 6 + k * 24       # 2px surface gap between the two bars (22px bars on a 24px pitch)
            body.append(bar(left, yy, plot * v, 22, cls, f"{label}, {name}: {v:.1%} of {len(rows)} questions"))
            body.append(f'<text class="t1" x="{left + plot * v + 6:.1f}" y="{yy + 15}" font-size="12">{v:.0%} ({name})</text>')
    body.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top - 6}" y2="{top + 2 * 64}" stroke-width="1"/>')
    (OUT / "test_crosslingual.svg").write_text(svg(W, top + 2 * 64 + 34, body, "Cross-language gap on TEST"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chart_test_context()
    chart_replication()
    chart_crosslingual()
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
