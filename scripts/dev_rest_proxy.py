"""Dev-only helper: maps Supabase-style `/rest/v1/...` URLs onto a bare PostgREST server.

Used only by the backend integration test (backend/tests/integration) so the real
SupabaseStore (supabase-py) can be exercised against a local PostgreSQL + PostgREST
without Docker. Not used in production (real Supabase already serves /rest/v1).

    python scripts/dev_rest_proxy.py --listen 54331 --target http://localhost:54330
"""
import argparse
import base64
import hashlib
import hmac
import http.server
import os
import socketserver

import httpx


def make_handler(target: str, sock: str | None = None, secret: str = "", anon_key: str = ""):
    client = httpx.Client(base_url="http://postgrest" if sock else target, timeout=30, trust_env=False,
                          transport=httpx.HTTPTransport(uds=sock) if sock else None)

    def allowed(headers) -> bool:
        """With a secret: only callers that hold this run's keys (other accounts can reach 127.0.0.1 too)."""
        if not secret:
            return True
        if anon_key and hmac.compare_digest(headers.get("apikey") or "", anon_key):
            return True
        parts = (headers.get("authorization") or "").removeprefix("Bearer ").split(".")
        if len(parts) != 3:
            return False
        want = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest())
        return hmac.compare_digest(want.rstrip(b"="), parts[2].encode())

    class Handler(http.server.BaseHTTPRequestHandler):
        def _proxy(self):
            if not allowed(self.headers):
                self.send_response(401)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            path = self.path
            if path.startswith("/rest/v1"):
                path = path[len("/rest/v1"):] or "/"
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            resp = client.request(self.command, path, content=body, headers=headers)
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "content-length", "connection", "content-encoding"):
                    self.send_header(k, v)
            self.send_header("content-length", str(len(resp.content)))
            self.end_headers()
            self.wfile.write(resp.content)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_HEAD = _proxy

        def log_message(self, *a):  # quiet
            pass

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=54331)
    ap.add_argument("--target", default="http://localhost:54330")
    ap.add_argument("--target-socket", help="Unix socket of PostgREST (scripts/scratch_db.sh)")
    args = ap.parse_args()

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    Server(("127.0.0.1", args.listen), make_handler(
        args.target, args.target_socket, os.environ.get("SCH_IT_JWT_SECRET", ""), os.environ.get("SCH_IT_ANON_KEY", ""))).serve_forever()
