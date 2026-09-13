#!/usr/bin/env python3
"""Lightweight token-counting proxy for the opencode ablation arm.

Sits between opencode and the Eliza API, forwards requests, captures
`usage` from each API response, and writes accumulated token counts
to a session-scoped JSON file.

Usage:
  python3 eval/token_proxy.py --port 18888 --upstream https://api.eliza.yandex.net/raw/internal/v2/models/GLM-5.3-Flash_alexkay28/v1 --session-file /tmp/opencode_tokens.json

Then point opencode at http://localhost:18888 instead of the upstream.
"""

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import ssl
from urllib.parse import urlparse

_lock = threading.Lock()
_total_input = 0
_total_output = 0
_total_calls = 0


def load_session(path):
    global _total_input, _total_output, _total_calls
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        _total_input = data.get("input_tokens", 0)
        _total_output = data.get("output_tokens", 0)
        _total_calls = data.get("api_calls", 0)


def save_session(path):
    with _lock:
        with open(path, "w") as f:
            json.dump({
                "input_tokens": _total_input,
                "output_tokens": _total_output,
                "total_tokens": _total_input + _total_output,
                "api_calls": _total_calls,
            }, f, indent=2)


class ProxyHandler(BaseHTTPRequestHandler):
    upstream_host = None
    upstream_port = None
    upstream_scheme = None
    session_file = None
    soy_token = None

    def _forward(self):
        global _total_input, _total_output, _total_calls

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        parsed = urlparse(self.upstream_scheme + "://" + self.upstream_host + self.path)

        if self.upstream_scheme == "https":
            ctx = ssl.create_default_context()
            ctx.load_verify_locations(os.environ.get("SSL_CERT_FILE", "/etc/ssl/certs/yandex-ca.pem"))
            conn = http.client.HTTPSConnection(self.upstream_host, self.upstream_port or 443, context=ctx)
        else:
            conn = http.client.HTTPConnection(self.upstream_host, self.upstream_port or 80)

        headers = dict(self.headers)
        headers.pop("Host", None)
        headers.pop("host", None)
        headers["Host"] = self.upstream_host
        if self.soy_token:
            headers["Authorization"] = f"OAuth {self.soy_token}"
            headers["Ya-Pool"] = "notelm"

        conn.request(self.command, self.path, body, headers)
        resp = conn.getresponse()
        resp_body = resp.read()

        if self.path.endswith("/chat/completions") and resp.status == 200:
            try:
                data = json.loads(resp_body)
                usage = data.get("usage", {})
                inp = usage.get("prompt_tokens", 0) or 0
                out = usage.get("completion_tokens", 0) or 0
                with _lock:
                    _total_input += inp
                    _total_output += out
                    _total_calls += 1
                if self.session_file:
                    save_session(self.session_file)
            except Exception:
                pass

        self.send_response(resp.status)
        for key, val in resp.getheaders():
            if key.lower() not in ("transfer-encoding", "content-length", "connection"):
                self.send_header(key, val)
        self.send_header("Content-Length", len(resp_body))
        self.end_headers()
        self.wfile.write(resp_body)
        conn.close()

    def do_POST(self):
        self._forward()

    def do_GET(self):
        self._forward()

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18888)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--session-file", required=True)
    parser.add_argument("--soy-token", default=None)
    args = parser.parse_args()

    parsed = urlparse(args.upstream)
    ProxyHandler.upstream_host = parsed.hostname
    ProxyHandler.upstream_port = parsed.port
    ProxyHandler.upstream_scheme = parsed.scheme
    ProxyHandler.session_file = args.session_file
    ProxyHandler.soy_token = args.soy_token or os.environ.get("SOY_TOKEN", "")

    load_session(args.session_file)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), ProxyHandler)
    print(f"Proxy on :{args.port} -> {args.upstream} (session: {args.session_file})")
    server.serve_forever()


if __name__ == "__main__":
    main()
