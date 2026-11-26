"""QA-only shared HTTPS origin for native API and existing web dispatcher."""
import argparse
import ipaddress
import os
import secrets
import ssl
from pathlib import Path
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from ops.qa.qa42_local_https import prepare
from ops.qa.qa42_device_tls import generate

def make_application():
    native, tokens, dispatch, csrf = prepare()
    password = secrets.token_urlsafe(32)
    os.environ.update(PD_DISPATCH_SESSION_SECRET=secrets.token_hex(32),
        PD_DISPATCH_PASSWORD_HASH=generate_password_hash(password),
        PD_DISPATCH_ADMIN_ID="201", PD_DISPATCH_TEST_SYNC="0")
    from pd_dispatcher_staging_wsgi import create_app
    web = create_app()
    def application(environ, start_response):
        path = environ.get("PATH_INFO", "")
        # Browser owns dispatcher paths; native API keeps its original auth.
        if path == "/native-orders" or path.startswith("/native-pilot-orders"):
            return native(environ, start_response)
        if path == "/dispatch" or path.startswith("/dispatch/") or path in (
                "/pd-logo-transparent.png", "/assets/pd-black-gold.css"):
            return web(environ, start_response)
        start_response("404 Not Found", [("Content-Type", "text/plain"), ("Cache-Control", "no-store")])
        return [b"Not available in local QA"]
    return application, tokens, password

def make_tls_server(address, directory, app):
    directory = generate(address, directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(directory/"server.pem"), str(directory/"server.key"))
    return make_server(address, 443, app, ssl_context=context, threaded=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--allow-private-lan", action="store_true")
    args = parser.parse_args()
    ip = ipaddress.IPv4Address(args.address)
    if not ip.is_loopback and not args.allow_private_lan:
        raise RuntimeError("Explicit private LAN opt-in required")
    directory = Path(args.directory).resolve()
    if directory.is_relative_to(Path.cwd().resolve()):
        raise RuntimeError("Keep temporary keys outside repository")
    app, tokens, password = make_application()
    server = make_tls_server(str(ip), directory, app)
    # Local owner-only fixture file; never print or commit credentials.
    fd = os.open(directory/"fixtures.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    import json
    with os.fdopen(fd, "w") as out:
        json.dump({"tokens": tokens, "dispatcher_password": password}, out)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        (directory/"fixtures.json").unlink(missing_ok=True)
        (directory/"server.key").unlink(missing_ok=True)

if __name__ == "__main__":
    main()
