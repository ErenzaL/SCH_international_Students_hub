#!/usr/bin/env bash
# One Render-equivalent memory run: scratch database, the API under scripts/render_like.py, the workload of scripts/render_memory_test.py.
# Results: scripts/benchmarks/results/render_like_TAG.{coldstart.txt,phases.json,server.json}. See docs/development/RENDER-MEMORY.md.
#
#   PG_BIN=... POSTGREST=... PY=backend/.venv/bin/python WORK=/private/dir \
#     scripts/render_memory_run.sh MEMORY_MB CPU TAG CORE SLOT [VAR=value ...]
#
#   MEMORY_MB 512 = killed like Render; 4096 = record the true peak.  CPU 0.1 = Render free.  CORE: the one CPU the API may use.
#   SLOT 1..9: own database directory, ports and info file, so two runs can go side by side.  VAR=value: extra environment for the API,
#   e.g. MALLOC_ARENA_MAX=2.  Loopback only, synthetic and public data only; needs backend/.eval-cache/public_corpus.json
#   (scripts/eval_retrieval_benchmark.py --fetch-corpus: public GET requests only).
set -uo pipefail
MB=${1:?MEMORY_MB}; CPU=${2:?CPU}; TAG=${3:?TAG}; CORE=${4:?CORE}; SLOT=${5:?SLOT}; shift 5
W="$(cd "$(dirname "$0")/.." && pwd)"; PY=${PY:?python of the backend venv}; WORK=${WORK:?private work directory}
API=$((8150 + SLOT * 10)); AUTH=$((API + 1)); DB=$WORK/sdb$SLOT; INFO=$WORK/mem$SLOT.json
OUT=$W/scripts/benchmarks/results/render_like_$TAG
RL=""
stop() { p=$(ss -ltnp "sport = :$API" | grep -oP 'pid=\K\d+' | head -1); [ -n "$p" ] && kill -CONT "$p" 2>/dev/null; [ -n "$RL" ] && kill "$RL" 2>/dev/null; sleep 3; }
[ -d "$DB" ] && "$W/scripts/scratch_db.sh" stop "$DB" >/dev/null 2>&1
PYTHON=$PY "$W/scripts/scratch_db.sh" start "$DB" >/dev/null || exit 1
# shellcheck disable=SC1091
source "$DB/env"
T0=$(date +%s.%N)
(cd "$W/backend" && exec env "$@" python3 "$W/scripts/render_like.py" --memory-mb "$MB" --cpu "$CPU" --report "$OUT.server.json" -- \
   taskset -c "$CORE" "$PY" ../scripts/dev_stack.py --api $API --auth $AUTH --web 3999 --info "$INFO" --embedding e5_onnx --llm none --offline \
   > "$WORK/mem_api$SLOT.log" 2>&1) & RL=$!
for _ in $(seq 600); do curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:$API/health" && break; sleep 1; done
echo "cold start: $(python3 -c "print(round($(date +%s.%N)-$T0,1))") s" | tee "$OUT.coldstart.txt"
(cd "$W/backend" && "$PY" -u ../scripts/render_memory_test.py "$INFO" --report "$OUT.phases.json" --corpus .eval-cache/public_corpus.json \
   --pdf-dir "$WORK" --pdf-mb "${PDFS:-3,9}" 2>&1 | cut -c1-260)
stop; wait "$RL" 2>/dev/null
python3 -c "import json;d=json.load(open('$OUT.server.json'));print('server: peak',d['peak_pss_mb'],'MB PSS /',d['peak_rss_mb'],'RSS; killed:',d['out_of_memory'],'; seconds',d['seconds'])"
"$W/scripts/scratch_db.sh" stop "$DB" >/dev/null; rm -f "$INFO"
