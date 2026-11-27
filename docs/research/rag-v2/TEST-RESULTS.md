# Test results — RAG v2 branch

All runs on the school server, 2026-11-27, branch `research/rag-reliability-v2`. "Passed" means the command was run and
its output read. Nothing was run against hosted staging or production.

## 1. Automated suites

| Suite | Command | Result |
|---|---|---|
| backend unit + component tests | `cd backend && .venv/bin/python -m pytest -q tests/` | **1,073 passed**, 0 failed, 53 skipped (the 53 are integration tests that need a scratch stack: 47 + the 6 new visibility tests); RC: 1,024 passed |
| PostgreSQL integration (real PostgREST + migrations) | `scripts/scratch_db.sh start …` then `pytest tests/integration` | **100 passed**, 0 failed, 9 skipped (RC: 94; + 6 visibility tests of `test_rag_v2_visibility.py`) |
| SQL behaviour suites (run by `scratch_db.sh start`) | `scripts/run_sql_tests.sh` | **15 / 15 passed** |
| web (Next.js) | not re-run: no frontend file changed on this branch | RC: 261 passed |

New test files of this mission:

| File | Tests | Covers |
|---|---|---|
| `tests/test_chunker_v2.py` | 11 | no text lost (v2 / v2b), v1 unchanged for structured markdown, stored strategy |
| `tests/test_evidence_gate.py` | 11 | decisions, path-dependent thresholds, `off` / `log` / `enforce` in the chat flow |
| `tests/test_citation_check.py` | 6 | supported, re-attributed, ambiguous, uncited, Korean dates, lists |
| `tests/test_injection_screen.py` | 14 | orders in five languages removed, ordinary guidance kept, prompt requests, translated disclosure, metadata |
| `tests/test_rag_v2_eval_lib.py` | 7 | metrics, need-level intervals, the TEST freeze, negatives disjoint from TEST |
| `tests/integration/test_rag_v2_visibility.py` | 6 | real PostgreSQL: draft, pending, superseded, cancelled, archived, expired, not-yet-valid, inactive-source content never searched, selected or counted; positive control found; hidden chunks exist |
| `tests/test_system_prompt.py` (changed) | 1 | an injected order now never reaches the prompt (stricter than before) |

## 2. Evaluation scripts as tests

| Check | Result |
|---|---|
| `scripts/rag_v2/build_testset.py --check` | OK, question hash `52f216ed7e5d7d1f` unchanged since the freeze |
| `scripts/rag_v2/regression.py` (reference `hub0.1` on DEV + VAL) | exit 0, every metric equal to the reference |
| same with keyword leg and bridge switched off (negative control) | exit 1, 6 metrics flagged |
| prompt-injection suite (`injection_eval.py`, local proxy) | 7 / 11 before the screens (J1), 11 / 11 after (J2) |
| monitoring SQL (PRODUCTION-READINESS §4) | executed on a migrated scratch database; empty table and sample rows both correct |

## 3. Not run

Hosted staging, production, Gemini (no key), browser end-to-end journeys (no UI change on this branch; RC 168 / 168).
