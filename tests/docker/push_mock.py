"""Dịch vụ push giả HTTPS cho test giao diện Web Push (e2e24.js): nhận POST, trả 201 (đường dẫn /gone/* trả 410).
Chạy: python push_mock.py <cổng> <cert> <key>"""
import ssl, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(410 if self.path.startswith("/gone") else 201)
        self.send_header("Content-Length", "0"); self.end_headers()


srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(sys.argv[2], sys.argv[3])
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
