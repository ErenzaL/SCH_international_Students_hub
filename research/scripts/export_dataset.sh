#!/usr/bin/env bash
# Read-only data export for the research notebooks. Run from the repository root.
#  1. database statistics (read-only transaction, linked Supabase project) -> research/data/dataset_statistics.json
#  2. public corpus snapshot (public API, approved content only)            -> backend/.eval-cache/public_corpus.json
#  3. corpus manifest (ids, titles, languages, sizes, content hashes; no full text) -> research/data/corpus_manifest.json
# No production writes; no student conversations are exported.
set -euo pipefail
supabase db query --remote --read-only -f research/sql/dataset_statistics.sql --output-format json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin)["rows"][0]["stats"], open("research/data/dataset_statistics.json","w"), ensure_ascii=False, indent=1)'
(cd backend && .venv/bin/python ../scripts/eval_retrieval_benchmark.py --fetch-corpus https://sch-hub-api.onrender.com)
python3 research/scripts/corpus_manifest.py
echo "export complete"
