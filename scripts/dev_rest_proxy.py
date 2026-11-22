"""Dev-only helper: maps Supabase-style `/rest/v1/...` URLs onto a bare PostgREST server.

Used only by the backend integration test (backend/tests/integration) so the real
SupabaseStore (supabase-py) can be exercised against a local PostgreSQL + PostgREST
without Docker. Not used in production (real Supabase already serves /rest/v1).

    python scripts/dev_rest_proxy.py --listen 54331 --target http://localhost:54330
"""
import argparse
import http.server
import socketserver

import httpx


def make_handler(target: str):
    client = httpx.Client(base_url=target, timeout=30)

    class Handler(http.server.BaseHTTPRequestHandler):
        def _proxy(self):
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
    args = ap.parse_args()

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    Server(("127.0.0.1", args.listen), make_handler(args.target)).serve_forever()
