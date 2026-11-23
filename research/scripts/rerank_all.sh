#!/usr/bin/env bash
# Runs every (snapshot, model) reranking job to completion. The runner is resumable (one flushed line per question);
# on this Apple-silicon machine the torch process occasionally dies natively (SIGBUS, no Python traceback), so each
# job is restarted (fixed in reranking.py by copying the weights out of the memory map; the restart loop stays as a guard) until both datasets have all 100 questions (max 15 attempts). Restarts are logged to
# data/results/<snapshot>/rerank_restarts.log (corpus_v1: data/results/rerank_restarts.log).
set -u
cd "$(dirname "$0")/../.."
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
for snap in ${SNAPSHOTS:-corpus_v1 corpus_v2}; do
  res=research/data/results; [ "$snap" = corpus_v1 ] || res=$res/$snap
  for m in ${MODELS:-mminilm bge-m3}; do
    for attempt in $(seq 1 15); do
      n1=$(cat "$res/reranked_${m}_pilot_v0.1.jsonl" 2>/dev/null | wc -l | tr -d ' ')
      n2=$(cat "$res/reranked_${m}_heldout_v0.2.jsonl" 2>/dev/null | wc -l | tr -d ' ')
      if [ "$n1" -ge 100 ] && [ "$n2" -ge 100 ] && [ -f "$res/reranked_${m}.manifest.json" ]; then break; fi
      echo "=== $snap $m attempt $attempt pilot=$n1 heldout=$n2 $(date -u +%H:%M:%S)"
      RERANK_ATTEMPT=$attempt RAG_SNAPSHOT=$snap research/.venv-rerank/bin/python research/scripts/run_reranking.py --models "$m" \
        > "/tmp/rerank_${snap}_${m}.out" 2>&1
      code=$?
      echo "exit $code $(date -u +%H:%M:%S)"
      [ $code -eq 0 ] || echo "$(date -u +%FT%TZ) $m attempt=$attempt exit=$code pilot=$n1 heldout=$n2" >> "$res/rerank_restarts.log"
    done
  done
done
echo "ALL DONE $(date -u +%H:%M:%S)"
