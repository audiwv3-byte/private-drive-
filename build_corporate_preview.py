"""Build the allowlisted PRIVATE DRIVE corporate preview ZIP or static site."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "site_preview"
FILES = (
    "index.html",
    "privacy.html",
    "terms.html",
    "pilot-privacy.html",
    "assets/private-drive-gold-car.webp",
    "assets/corporate.css",
    "assets/pd-logo.webp",
    "assets/hero.webp",
    "assets/service-airport.webp",
    "assets/service-parcel.webp",
    "assets/service-driver.webp",
    "assets/airport.webp",
    "assets/kaunas.webp",
    "assets/klaipeda.webp",
    "assets/warsaw.webp",
)
OUTPUT = ROOT / "build" / "corporate-preview"
RENDER_OUTPUT = ROOT / "build" / "render-preview"

class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.has_form = False
        self.has_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.has_form = True
        if tag in ("script", "iframe", "object", "embed"):
            self.has_script = True
        for key in ("href", "src", "action"):
            if key in attrs:
                self.urls.append(attrs[key])

def validate_source():
    expected = set(FILES)
    for name in FILES:
        path = SOURCE / name
        if not path.is_file():
            raise ValueError("Missing allowlisted asset: " + name)
        if name.endswith(".html"):
            text = path.read_text(encoding="utf-8")
            parser = AssetLinks()
            parser.feed(text)
            if parser.has_form or parser.has_script:
                raise ValueError("Interactive or executable content blocked: " + name)
            for url in parser.urls:
                if url.startswith(("#", "mailto:", "https://")):
                    continue
                if url not in expected:
                    raise ValueError("Unapproved local link in " + name + ": " + url)
            if "http://" in text:
                raise ValueError("Insecure HTTP reference in " + name)
    return expected

def build_static_files(destination, notice):
    validate_source()
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in FILES:
        data = (SOURCE / name).read_bytes()
        if name.endswith(".html"):
            text = data.decode("utf-8")
            if "<head>" not in text:
                raise ValueError("Cannot inject preview guard: " + name)
            if "<body>" not in text:
                raise ValueError("Cannot insert preview notice: " + name)
            inject = ('<meta name="robots" content="noindex,nofollow,noarchive">'
                      '<meta name="referrer" content="no-referrer">'
                      '<meta http-equiv="Content-Security-Policy" content="'
                      "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                      "form-action 'none'; base-uri 'none'\">"
                      '<style id="pd-private-preview-banner">'
                      '.pd-preview-notice{max-width:none;margin:0;background:#443019;color:#ffebbd;'
                      'font:650 13px/1.4 system-ui,sans-serif;padding:8px 12px;text-align:center}'
                      '</style>')
            text = text.replace("<head>", "<head>" + inject, 1)
            text = text.replace("<body>", f'<body><div class="pd-preview-notice">{notice}</div>', 1)
            data = text.encode("utf-8")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = hashlib.sha256(data).hexdigest()
    (destination / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    return manifest

def build(destination=OUTPUT):
    destination = Path(destination)
    manifest = build_static_files(
        destination, "ИЗОЛИРОВАННЫЙ ПРЕДПРОСМОТР · ЗАКАЗЫ И ПЛАТЕЖИ ОТКЛЮЧЕНЫ"
    )
    (destination / "_headers").write_text(
        "/*\n"
        "  X-Robots-Tag: noindex, nofollow, noarchive\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: no-referrer\n"
        "  X-Frame-Options: DENY\n"
        "  Content-Security-Policy: default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'\n"
        "  Cache-Control: no-store\n",
        encoding="utf-8",
    )
    (destination / "AUDIT.json").write_text(json.dumps({
        "environment": "offline-preview-only",
        "publicly_hosted": False,
        "auth_required_before_https_deployment": True,
        "files_sha256": manifest,
        "excluded": ["registration.html", "registration-client.mjs", "private-test-bootstrap.js",
                     "compare.html", "preview.html", "Flutter Web", "API", "payment integration"]
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = destination.parent / "private-drive-corporate-preview.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for file in sorted(destination.rglob("*")):
            if file.is_file():
                z.write(file, file.relative_to(destination).as_posix())
    return archive

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true", help="Build the public test directory without packaging.")
    if parser.parse_args().render:
        build_static_files(RENDER_OUTPUT, "Тестовый предпросмотр PRIVATE DRIVE")
        print(RENDER_OUTPUT)
    else:
        print(build())
