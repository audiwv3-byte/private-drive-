"""Explicit opt-in HTTPS gate for an iPhone Safari PRIVATE DRIVE test.

No automatic startup and no public deployment. Run only with operator-supplied
TLS files, a private LAN bind address, an exact iPhone IP and a strong password.
The underlying in-memory WSGI auth app is *never* reachable directly.
"""
import base64
import hmac
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from pd_test_registration import make_test_registration_app

HOSTNAME = "pd-test.local"
ASSETS = Path(__file__).resolve().parent / "site_preview"
CONTENT = {
    "/registration.html": ("text/html; charset=utf-8", ASSETS / "registration.html"),
    "/registration-client.mjs": ("text/javascript; charset=utf-8", ASSETS / "registration-client.mjs"),
}
BOOTSTRAP = """'use strict';
window.__PD_PRIVATE_TEST_ENABLED__ = true;
window.__PD_LOCAL_TEST_TRANSPORT__ = async (route, payload) => {
  if (!['/test-registration/request-code','/test-registration/verify-code'].includes(route))
    throw Error('route_not_allowed');
  const response = await fetch(route, {
    method:'POST', headers:{'Content-Type':'application/json','X-PD-Test':'1'},
    credentials:'same-origin', cache:'no-store', body:JSON.stringify(payload)
  });
  return {status:response.status,body:await response.json()};
};
"""


def private_ipv4(value):
    ip = ipaddress.ip_address(value)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        raise ValueError("A non-loopback private IPv4 address is required")
    # Only RFC1918, not other special-purpose ranges such as TEST-NET.
    if not any(ip in n for n in (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )):
        raise ValueError("Only RFC1918 addresses are supported")
    return str(ip)


def make_private_gateway(iphone_ip, password, *, clock=None):
    allowed = private_ipv4(iphone_ip)
    if not isinstance(password, str) or len(password) < 20:
        raise ValueError("Set a random password of at least 20 characters")
    inner, inbox = make_test_registration_app(clock=clock)
    token = "Basic " + base64.b64encode(("pd-test:" + password).encode()).decode()

    def respond(start_response, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        start_response(status, [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"),
        ])
        return [body]

    def app(environ, start_response):
        # All checks precede any use of the loopback-only in-memory API.
        if environ.get("wsgi.url_scheme") != "https":
            return respond(start_response, "403 Forbidden", '{"error":"https_required"}')
        if environ.get("REMOTE_ADDR") != allowed:
            return respond(start_response, "403 Forbidden", '{"error":"device_denied"}')
        host = environ.get("HTTP_HOST", "").split(":", 1)[0].lower()
        if host != HOSTNAME:
            return respond(start_response, "403 Forbidden", '{"error":"host_denied"}')
        supplied = environ.get("HTTP_AUTHORIZATION", "")
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return respond(start_response, "401 Unauthorized", '{"error":"auth_required"}')
        route = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        if method == "GET" and route in CONTENT:
            mime, asset = CONTENT[route]
            return respond(start_response, "200 OK", asset.read_bytes(), mime)
        if method == "GET" and route == "/private-test-bootstrap.js":
            return respond(start_response, "200 OK", BOOTSTRAP, "text/javascript; charset=utf-8")
        if method == "POST" and route in ("/test-registration/request-code", "/test-registration/verify-code"):
            if environ.get("HTTP_ORIGIN") != "https://" + environ.get("HTTP_HOST", "") or environ.get("HTTP_X_PD_TEST") != "1":
                return respond(start_response, "403 Forbidden", '{"error":"origin_denied"}')
            try:
                size = int(environ.get("CONTENT_LENGTH", "0"))
                if not (0 < size <= 2048):
                    raise ValueError()
                raw = environ["wsgi.input"].read(size)
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError()
                # Only reserved dummy addresses. No real users or phones.
                if route.endswith("request-code"):
                    if body.get("channel") != "email" or not isinstance(body.get("destination"), str) or not body["destination"].lower().endswith("@example.test"):
                        return respond(start_response, "400 Bad Request", '{"error":"dummy_email_only"}')
            except (ValueError, KeyError, TypeError, UnicodeError):
                return respond(start_response, "400 Bad Request", '{"error":"invalid_json"}')
            forwarded = dict(environ, REMOTE_ADDR="127.0.0.1", CONTENT_LENGTH=str(len(raw)),
                             **{"wsgi.input": io.BytesIO(raw)})
            got = []
            result = b"".join(inner(forwarded, lambda s, h: got.append(s)))
            try:
                response = json.loads(result)
                # The test client deliberately ignores the token; never send it to the phone.
                response.pop("access_token", None)
                response.pop("destination", None)
            except (ValueError, TypeError):
                return respond(start_response, "500 Internal Server Error", '{"error":"bad_test_response"}')
            return respond(start_response, got[0], json.dumps(response))
        return respond(start_response, "404 Not Found", '{"error":"not_found"}')
    return app, inbox


def serve_private_tls(bind_ip, iphone_ip, password, certfile, keyfile, port=8443):
    """Manual operation only. Certificate must be trusted by Safari for pd-test.local."""
    bind_ip = private_ipv4(bind_ip)
    if bind_ip == private_ipv4(iphone_ip):
        raise ValueError("Server and iPhone IP addresses must differ")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile)
    app, inbox = make_private_gateway(iphone_ip, password)
    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))) if self.command == "POST" and self.headers.get("Content-Length", "0").isdigit() and int(self.headers.get("Content-Length", "0")) <= 2048 else b""
            status = []
            headers = []
            environ = {
                "wsgi.url_scheme": "https", "REMOTE_ADDR": self.client_address[0],
                "HTTP_HOST": self.headers.get("Host", ""),
                "HTTP_AUTHORIZATION": self.headers.get("Authorization", ""),
                "HTTP_ORIGIN": self.headers.get("Origin", ""),
                "HTTP_X_PD_TEST": self.headers.get("X-PD-Test", ""),
                "PATH_INFO": urlsplit(self.path).path, "REQUEST_METHOD": self.command,
                "CONTENT_LENGTH": str(len(raw)), "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "wsgi.input": io.BytesIO(raw)
            }
            result = b"".join(app(environ, lambda s, h: (status.append(s),headers.extend(h))))
            self.send_response(int(status[0].split()[0]))
            for key, val in headers:
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(result)
        do_GET = handle_request
        do_POST = handle_request
        def log_message(self, format, *args):
            pass  # Never log OTPs, identifiers, request paths or credentials.
    server = HTTPServer((bind_ip, int(port)), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print("PRIVATE DRIVE private Safari test gateway running; only the whitelisted iPhone may connect.")
    print("Test OTPs stay in the local process only. Stop with Ctrl+C; in-memory data is discarded.")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    # Deliberately no CLI autostart and no default listener.
    raise SystemExit("Import serve_private_tls and supply a trusted certificate, private IPs and password explicitly.")
