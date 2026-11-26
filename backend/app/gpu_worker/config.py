"""Worker configuration (environment variables) and credential file."""
from __future__ import annotations

import ipaddress
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# production secrets have no business on this machine: refuse to run next to them
FORBIDDEN = re.compile(r"^(SUPABASE_|NEXT_PUBLIC_SUPABASE_|DATABASE_URL$|LLM_API_KEY$|GEMINI_API_KEY$|GOOGLE_API_KEY$|"
                       r"CRON_SECRET$|OCR_SPACE_API_KEY$)", re.I)


#: the production API. Until the Release B sign-off the worker serves only development and staging task systems; connecting to
#: production needs GPU_WORKER_PRODUCTION_HOST set to exactly this host (a deliberate step taken with the Release B sign-off)
PRODUCTION_HOSTS = ("sch-hub-api.onrender.com",)


class ConfigError(Exception):
    pass


@dataclass
class Config:
    hub_url: str
    token_file: Path
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b-instruct"
    num_ctx: int = 16384
    model_timeout: float = 180.0
    idle_min: float = 300.0        # wait after an empty queue; doubles up to idle_max
    idle_max: float = 3600.0
    active_hours: tuple[int, int] | None = None    # KST, e.g. (9, 18)
    lock_file: Path = Path.home() / ".local/state/sch-gpu-worker/lock"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        e = dict(os.environ if env is None else env)
        bad = sorted(k for k, v in e.items() if v and FORBIDDEN.match(k))
        if bad:
            raise ConfigError(f"Refusing to start: {', '.join(bad)} must not be set on the GPU server.")
        url = check_hub_url(e.get("GPU_WORKER_HUB_URL", ""), production_host=e.get("GPU_WORKER_PRODUCTION_HOST", ""))
        c = cls(hub_url=url, token_file=Path(e.get("GPU_WORKER_TOKEN_FILE")
                                             or Path.home() / ".config/sch-gpu-worker/token").expanduser())
        c.ollama_url = e.get("OLLAMA_BASE_URL") or c.ollama_url
        c.model = e.get("OLLAMA_MODEL") or c.model
        try:
            c.num_ctx = int(e.get("OLLAMA_NUM_CTX") or c.num_ctx)
            c.model_timeout = float(e.get("OLLAMA_JOB_TIMEOUT_SECONDS") or c.model_timeout)
            c.idle_min = max(5.0, float(e.get("GPU_WORKER_IDLE_MIN_SECONDS") or c.idle_min))
            c.idle_max = max(c.idle_min, float(e.get("GPU_WORKER_IDLE_MAX_SECONDS") or c.idle_max))
        except ValueError as exc:
            raise ConfigError("A numeric setting is not a number.") from exc
        hours = e.get("GPU_WORKER_ACTIVE_HOURS", "").strip()
        if hours:
            m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", hours)
            if not m or not (0 <= int(m[1]) < int(m[2]) <= 24):
                raise ConfigError("GPU_WORKER_ACTIVE_HOURS must look like 9-18 (Korea time).")
            c.active_hours = int(m[1]), int(m[2])
        if e.get("GPU_WORKER_LOCK_FILE"):
            c.lock_file = Path(e["GPU_WORKER_LOCK_FILE"]).expanduser()
        return c


def check_hub_url(url: str, production_host: str = "") -> str:
    """https, or plain http to this machine (tests). No path, credentials or query. Not the production API without the Release B sign-off."""
    url = url.strip().rstrip("/")
    try:
        p = urlsplit(url)
        host, _ = p.hostname or "", p.port
    except ValueError:
        raise ConfigError("GPU_WORKER_HUB_URL is not a valid URL.") from None
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not host or p.username or p.path or p.query or p.fragment or not (p.scheme == "https" or (p.scheme == "http" and local)):
        raise ConfigError("GPU_WORKER_HUB_URL must be https://<api host> without a path.")
    if host.lower() in PRODUCTION_HOSTS and production_host.strip().lower() != host.lower():
        raise ConfigError(f"GPU_WORKER_HUB_URL is the production API ({host}). The worker serves development and staging only; production needs "
                          "the Release B sign-off and then GPU_WORKER_PRODUCTION_HOST set to that exact host.")
    return url


def read_token(path: Path) -> str:
    """The credential: a regular file that only its owner can read. Read again for every job, so rotation needs no
    restart."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ConfigError(f"Cannot read the token file {path}: {exc.strerror}") from None
    with os.fdopen(fd) as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ConfigError(f"{path} must be a file of this account that nobody else can read (chmod 600).")
        token = f.read(500).strip()
    if not re.fullmatch(r"schgw_[0-9a-f]{32}_[A-Za-z0-9_-]{43}", token):
        raise ConfigError(f"{path} does not contain a worker token.")
    return token
