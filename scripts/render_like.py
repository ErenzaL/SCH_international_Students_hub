"""Run a command the way a Render free instance would hold it: at most MEMORY_MB for the whole process tree (killed when it goes over,
like the out-of-memory killer) and CPU_SHARE of one core (stopped and continued in 100 ms slices). No root, no containers.

    python3 scripts/render_like.py --memory-mb 512 --cpu 0.1 --report OUT.json -- uvicorn app.main:app --port 8061

Approximation, stated in every report: memory = proportional set size (PSS) of all processes of the tree, which is what they use of RAM
including their share of libraries; a cgroup also charges page cache, which the kernel can reclaim before it kills. CPU slices of 10 ms per
100 ms give 0.1 CPU on average; Render's limit is smoother. Both are close enough to find what would not fit.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def tree(root: int) -> list[int]:
    kids: dict[int, list[int]] = {}
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                ppid = int((p / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            kids.setdefault(ppid, []).append(int(p.name))
    out, todo = [], [root]
    while todo:
        pid = todo.pop()
        out.append(pid)
        todo.extend(kids.get(pid, []))
    return out


def usage(pids: list[int]) -> tuple[int, int]:
    """(PSS, RSS) of the processes, in KiB"""
    pss = rss = 0
    for pid in pids:
        try:
            for ln in Path(f"/proc/{pid}/smaps_rollup").read_text().split("\n"):
                if ln.startswith("Pss:"):
                    pss += int(ln.split()[1])
                elif ln.startswith("Rss:"):
                    rss += int(ln.split()[1])
        except OSError:
            pass
    return pss, rss


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory-mb", type=int, default=512)
    ap.add_argument("--cpu", type=float, default=0.1)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    child = subprocess.Popen(cmd, cwd=a.cwd, start_new_session=True)
    limit_kib = a.memory_mb * 1024
    slot, run = 0.1, max(0.005, 0.1 * min(a.cpu, 1.0))
    started, peak, peak_rss, samples, killed = time.time(), 0, 0, [], None
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    last_sample = 0.0
    try:
        while child.poll() is None and not stop["now"]:
            if a.cpu < 1.0:
                os.killpg(child.pid, signal.SIGCONT)
                time.sleep(run)
                os.killpg(child.pid, signal.SIGSTOP)
                time.sleep(slot - run)
            else:
                time.sleep(slot)
            now = time.time()
            if now - last_sample >= 0.2:
                last_sample = now
                pss, rss = usage(tree(child.pid))
                peak, peak_rss = max(peak, pss), max(peak_rss, rss)
                samples.append((round(now - started, 1), pss // 1024))
                if pss > limit_kib:
                    killed = dict(at_seconds=round(now - started, 1), pss_mb=pss // 1024)
                    os.killpg(child.pid, signal.SIGKILL)
                    break
    finally:
        try:
            os.killpg(child.pid, signal.SIGCONT)
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    a.report.write_text(json.dumps(dict(command=" ".join(cmd)[:300], memory_mb=a.memory_mb, cpu=a.cpu, seconds=round(time.time() - started, 1),
                                        peak_pss_mb=peak // 1024, peak_rss_mb=peak_rss // 1024, out_of_memory=killed, exit_code=child.returncode,
                                        samples=samples[-3000:], note=__doc__.split("Approximation, stated in every report: ")[1].strip()), indent=1))
    print(f"peak {peak // 1024} MB PSS ({peak_rss // 1024} MB RSS)" + (f"; KILLED over {a.memory_mb} MB at {killed['at_seconds']} s" if killed else ""), file=sys.stderr)
    return 137 if killed else 0


if __name__ == "__main__":
    raise SystemExit(main())
