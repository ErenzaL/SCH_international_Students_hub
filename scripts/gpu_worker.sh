#!/usr/bin/env bash
# Run the GPU worker with ONLY its own settings (a clean environment: nothing from your shell, such as other keys,
# reaches it).   scripts/gpu_worker.sh --check | --once | --drain | (no option: continuous, stop with Ctrl+C)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
envfile="${GPU_WORKER_ENV_FILE:-$HOME/.config/sch-gpu-worker/env}"
py="${GPU_WORKER_PYTHON:-$HOME/sch-gpu/venv/bin/python}"
[ -f "$envfile" ] || { echo "Missing $envfile: copy backend/gpu-worker.env.example there (chmod 600)." >&2; exit 78; }
[ "$(stat -c %a "$envfile")" = 600 ] || { echo "$envfile must be chmod 600." >&2; exit 78; }
[ -x "$py" ] || { echo "Missing $py: uv venv --python 3.11 ~/sch-gpu/venv && uv pip install --python ~/sch-gpu/venv/bin/python -r backend/requirements-gpu-worker.txt" >&2; exit 78; }
cd "$root/backend"
exec env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" LANG=C.UTF-8 \
  bash -c 'set -a; . "$0"; set +a; exec "$1" -m app.gpu_worker "${@:2}"' "$envfile" "$py" "$@"
