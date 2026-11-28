# Technical debt

| # | Debt | Where | Effect | Proposed fix | Priority |
|---|---|---|---|---|---|
| D1 | The live services do not follow `render.yaml` (values set by hand) | Render environment | blueprint and production drift (e.g. `EMBEDDING_PROVIDER` `e5` live, `e5_onnx` in the file) | list live values once; make the blueprint the source of truth or document it as reference only | P2 |
| D2 | No revision endpoint | `/health` | the live commit cannot be verified from outside | add the build commit to `/health` | P2 |
| D3 | Migrations applied by hand in the SQL editor | Supabase | drift between files and production is invisible | the read-only `doctor` before and after each deploy (exists); record applied versions | P2 |
| D4 | Two chunker versions | `chunking.py` (`v1`, `v2`, `v2b`) | three code paths until the re-index | after the re-index, make v2 the default and keep v1 only for reading old chunks | P2 |
| D5 | DEV / VALIDATION labels not exhaustive | `scripts/benchmarks/` | misleading results for ranking experiments | regrade or retire (B1) | P2 |
| D6 | Evaluation data outside git | `backend/.eval-cache/` (corpus snapshot, validation set) | reproduction needs the files from the workstation | keep a private copy with the owner; document the hashes (done in DATASET-CARD) | P3 |
| D7 | Many local branches | workstation | confusion about what is current | after the merge, archive old branches with tags and delete them locally (owner decision) | P3 |
| D8 | Evidence gate thresholds tuned on development questions | `gate.py`, settings | cannot be enforced | refit on human-labelled real traffic or remove the similarity signal | P3 |
| D9 | AI budgets in memory until 0018 | `rate_limit.py` | budgets reset on restart | apply 0018 | P1 |
| D10 | No automated backups | Supabase free | data-loss risk | scheduled `pg_dump` | P1 |
| D11 | Translation scope encoded in settings and tests | `auto_translate_languages`, scope tests | widening the scope needs code and test changes together | keep; it prevents accidental expansion | — |
