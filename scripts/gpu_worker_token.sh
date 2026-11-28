#!/usr/bin/env bash
# Store the GPU worker token WITHOUT showing it: paste it when asked. Nothing is echoed, nothing reaches the shell
# history, the file is written owner-only (600) in an owner-only directory (700).
#   scripts/gpu_worker_token.sh            # -> ~/.config/sch-gpu-worker/token
set -euo pipefail
dir="${GPU_WORKER_CONFIG_DIR:-$HOME/.config/sch-gpu-worker}"
umask 077
mkdir -p "$dir"
chmod 700 "$dir"
printf 'Paste the worker token (hidden), then press Enter: ' >&2
IFS= read -rs token
printf '\n' >&2
if [[ ! "$token" =~ ^schgw_[0-9a-f]{32}_[A-Za-z0-9_-]{43}$ ]]; then
  unset token
  echo "That is not a worker token (schgw_...). Nothing was written." >&2
  exit 1
fi
tmp="$(mktemp "$dir/.token.XXXXXX")"
printf '%s\n' "$token" > "$tmp"
unset token
chmod 600 "$tmp"
mv -f "$tmp" "$dir/token"
echo "Saved: $dir/token (mode $(stat -c %a "$dir/token")). The token was not shown." >&2
