from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

def wait_for_code(redirect_uri: str, timeout: int = 300) -> str:
    """Serve one request on the redirect URI's host/port and return the ?code= value."""
    u = urlparse(redirect_uri)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urlparse(self.path)
            if q.path != u.path:
                self.send_response(404); self.end_headers(); return
            params = parse_qs(q.query)
            result["code"] = params.get("code", [None])[0]
            result["error"] = params.get("error", [None])[0]
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"raingist: authorization received. Check the terminal, then close this tab." if result["code"]
                             else b"raingist: authorization failed, check the terminal.")

        def log_message(self, *a):   # keep the code out of logs
            pass

    class Server(HTTPServer):
        def handle_timeout(self):
            result["timed_out"] = True

    server = Server(("127.0.0.1", u.port or 80), Handler)
    server.timeout = timeout
    try:
        while "code" not in result:   # stray requests (e.g. /favicon.ico) get a 404 and we keep waiting
            server.handle_request()
            if result.get("timed_out"):
                raise TimeoutError(f"no OAuth redirect within {timeout}s")
    finally:
        server.server_close()
    if not result.get("code"):
        raise RuntimeError(f"authorization denied: {result.get('error')}")
    return result["code"]
