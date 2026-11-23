# RAG pipeline diagram - static specification for PowerPoint

One 16:9 slide, two horizontal swim-lanes, left-to-right flow. Build with PowerPoint shapes (no screenshots of the
app). Values in boxes come from `configs/experiments.json` and `data/dataset_statistics.json`; do not add numbers
that are not in those files.

## Canvas and style

- Slide 13.33 × 7.5 in. Margins 0.5 in. Background white (#FFFFFF); lane bands #F5F5F3, no borders.
- Boxes: rounded rectangles, 1.6 × 0.9 in, 1 pt outline #52514E, fill white; title 12 pt semibold #0B0B0B, detail
  9 pt #52514E. Arrows: 1.5 pt #52514E, filled triangle heads. Dashed arrow (4-2) = optional / conditional path.
- Accent fills (light tint, 15% opacity) by role - use each consistently:
  - data and indexing: blue #2A78D6
  - retrieval: aqua #1BAF7A
  - generation and checks: orange #EB6834
  - human review: yellow #EDA100 (pair the fill with a small person icon; never colour alone)

## Lane 1 (top) - "Indexing (offline, after human approval)"

1. **Sources** - "University notices, guides; Korean government pages · web / PDF / DOCX / pasted notices"
2. **Extraction** - "HTML / PyMuPDF / DOCX · page markers · text normalisation"
3. **Human review** *(yellow, person icon)* - "Reviewer approves a version · only approved, current versions are indexed"
4. **Chunking** - "Heading/paragraph-aware v1 · target 320 / max 420 / overlap 48 est. tokens"
5. **Embedding** - "multilingual-e5-small · ONNX int8 · 384 dimensions · 'passage:' prefix"
6. **Vector store** - "Supabase PostgreSQL + pgvector · HNSW (cosine) · GIN full-text + trigram"

Arrows 1→2→3→4→5→6. Under box 6 a small caption: "searchable_chunks view: approved · current · not canceled /
archived · active source · within validity window".

## Lane 2 (bottom) - "Answering (per student question)"

7. **Question** - "Korean · English · Indonesian · Vietnamese · Chinese · selected site language"
8. **Query understanding** - "Visa-code normalisation (D2 = D-2) · multilingual glossary · optional LLM rewrite → standalone + English + Korean queries" (dashed outline for the LLM part)
9. **Hybrid retrieval (E2)** - "Vector leg + keyword leg · weighted fusion (semantic ≥ keyword) · rarity-weighted, script-aware coverage · code-mismatch demotion · de-duplication"
10. **Evidence selection** - "≤ 4 source documents · ≤ 3 passages each · quantity questions prefer passages with figures"
11. **Generation** - "Gemini primary → fallback (bounded retries, circuit breaker) · versioned system prompt"
12. **Answer checks** - "Citation validity · unsupported-figure removal · link allow-list · prompt-leak guard · one clean ending"
13. **Answer + sources** - "Student's language · one compact Sources list · supporter offer only by backend policy (explicit consent to send)"

Arrows 7→8→9→10→11→12→13. A vertical arrow from box 6 (lane 1) down into box 9 labelled "approved chunks only".
A dashed arrow from box 13 to a small box **Global Supporter** *(yellow, person icon)* labelled "only when the student
confirms".

## Footer (8 pt, #52514E)

"Evaluation: B0 vector-only · E1 equal-weight hybrid (SQL RRF) · E2 improved hybrid · E2S + evidence selection.
Reranking not implemented. Datasets: pilot v0.1 (development), held-out v0.2 (test); labels not yet human-reviewed."

## Accessibility

- Every role colour also has a text label (lane titles, icons); the slide must read correctly in greyscale.
- Alt text: "Two-lane diagram of the SCH assistant: approved documents are extracted, reviewed, chunked, embedded and
  stored in pgvector; a student's question is normalised, searched with hybrid retrieval, reduced to evidence,
  answered by Gemini, checked, and returned with sources."
