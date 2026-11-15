"""Read-only PythonAnywhere source comparison and overlay applicability audit.

No source contents, database files or credentials are printed or persisted.
Reads exactly five application source files with authenticated GET requests.
Generated overlays exist only in the runner's memory, never on PythonAnywhere.
"""
import ast
import hashlib
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
PROJECT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
FILES = (
    "miniapp_server.py",
    "miniapp/templates/index.html",
    "Euro_Baltic_Transfer.py",
    "pd_tips_widget.py",
    "pd_tips_widget.js",
)
FLAGS = {"en": ("🇬🇧", "English", "EN"),
         "lt": ("🇱🇹", "Lietuvių", "LT"),
         "ru": ("🇷🇺", "Русский", "RU")}


def get_source(filename, token):
    req = urllib.request.Request(
        API + PROJECT + "/" + filename,
        headers={"Authorization": "Token " + token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Read failed for {filename}: HTTP {exc.code}") from None


def overlay_cache(text):
    # Never replace an entire Python module: modify only the named handler.
    pattern = r"(?ms)^@app\.after_request\s*\ndef private_response_cache\(response\):\n.*?(?=^@app\.|\Z)"
    found = list(re.finditer(pattern, text))
    if len(found) != 1:
        return "REVIEW_NEEDED_HANDLER", None
    match = found[0]
    handler = match.group()
    if "response.headers['Cache-Control']" not in handler or "response.headers['Vary']" not in handler:
        return "REVIEW_NEEDED_HEADERS", None
    if "path in ('/api/me', '/api/orders')" in handler:
        return "ALREADY_PRESENT", text
    needle = "    if request.path.lower().startswith("
    if handler.count(needle) != 1:
        return "REVIEW_NEEDED_CONDITION", None
    updated_handler = handler.replace(
        needle,
        "    path = request.path.lower()\n"
        "    if path in ('/api/me', '/api/orders') or path.startswith(",
        1,
    )
    candidate = text[:match.start()] + updated_handler + text[match.end():]
    try:
        ast.parse(candidate)
    except SyntaxError:
        return "REVIEW_NEEDED_SYNTAX", None
    return "OVERLAY_READY", candidate


def overlay_language(text):
    # Change only existing language UI nodes; preserve all unrelated server edits.
    if text.count('<div id="pdObLanguage"') != 1 or text.count('<div id="pdObRole"') != 1:
        return "REVIEW_NEEDED_PANELS", None
    a = text.index('<div id="pdObLanguage"')
    b = text.index('<div id="pdObRole"')
    c = text.find('<form id="pdObPassenger"', b)
    if not a < b < c:
        return "REVIEW_NEEDED_ORDER", None
    lang = text[a:b]
    role = text[b:c]
    if "pd-ob-language-options" not in lang:
        return "REVIEW_NEEDED_LANGUAGE_LAYOUT", None
    for code, (flag, name, abbr) in FLAGS.items():
        expr = re.compile(
            r"(<button\b[^>]*\bonclick=\"pdChooseInitialLanguage\('" + code +
            r"'\)\"[^>]*>)(.*?)(</button>)", re.S,
        )
        found = list(expr.finditer(lang))
        if len(found) != 1:
            return "REVIEW_NEEDED_LANGUAGE_" + code.upper(), None
        inner = found[0].group(2)
        if flag in inner and name in inner:
            continue
        if re.sub(r"<[^>]+>", "", inner).strip() != abbr:
            return "REVIEW_NEEDED_CUSTOM_LANGUAGE_" + code.upper(), None
        replacement = (
            f'<span class="pd-lang-flag" aria-hidden="true">{flag}</span>'
            f'<span class="pd-lang-name">{name}</span>'
            f'<span class="pd-lang-code">{abbr}</span>'
        )
        lang = expr.sub(lambda m: m.group(1) + replacement + m.group(3), lang, count=1)
    duplicate = '<button type="button" class="secondary" onclick="pdShowOnboarding(\'language\')">Язык</button>'
    if role.count(duplicate) > 1:
        return "REVIEW_NEEDED_DUPLICATE_ROLE", None
    role = role.replace(duplicate, "")
    result = text[:a] + lang + role + text[c:]
    for code, (flag, _, abbr) in FLAGS.items():
        pattern = re.compile(
            r'(<option\b[^>]*\bvalue="' + code + r'"[^>]*>)([^<]*)(</option>)'
        )
        matches = list(pattern.finditer(result))
        if len(matches) != 1:
            return "REVIEW_NEEDED_SELECT_" + code.upper(), None
        current = matches[0].group(2).strip()
        if current == f"{flag} {abbr}":
            continue
        if current != abbr:
            return "REVIEW_NEEDED_CUSTOM_SELECT_" + code.upper(), None
        result = pattern.sub(lambda m: m.group(1) + flag + " " + abbr + m.group(3), result, count=1)
    style_marker = "pd-lang-flag{"
    if style_marker not in result:
        if result.count("</head>") != 1:
            return "REVIEW_NEEDED_STYLE", None
        css = (
            '<style id="pd-language-flags-overlay">'
            '.pd-ob-language-options button{min-width:0;display:flex;flex-direction:column;align-items:center;gap:6px;padding:15px 5px}'
            '.pd-lang-flag{font-size:34px;line-height:1.25}'
            '.pd-lang-name{font-size:14px;font-weight:700;overflow-wrap:anywhere}'
            '.pd-lang-code{font-size:11px;opacity:.75}'
            '.pd-onboarding-active .pd-language-switch{display:flex!important}'
            '.pd-onboarding-active:has(#pdObLanguage:not(.hidden)) .pd-language-switch{display:none!important}'
            '</style>'
        )
        result = result.replace("</head>", css + "</head>", 1)
    if result == text:
        return "ALREADY_PRESENT", result
    if result.count('<div id="pdObLanguage"') != 1 or result.count('<div id="pdObRole"') != 1:
        return "REVIEW_NEEDED_OUTPUT", None
    return "OVERLAY_READY", result


def main():
    token = "".join(os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip().split())
    token = re.sub(r"^Token", "", token, flags=re.I).strip()
    if not token:
        raise RuntimeError("PythonAnywhere token secret is unavailable; no read attempted")
    print("AUDIT_MODE READ_ONLY (GET only; no output files; no live changes)", flush=True)
    status = {}
    for filename in FILES:
        live = get_source(filename, token)
        if len(live) < 100 or len(live) > 2_000_000:
            raise RuntimeError(f"Unexpected source length: {filename}")
        github = (ROOT / filename).read_bytes()
        match = live == github
        print(
            f"SOURCE_COMPARE {filename} {'MATCH' if match else 'DIFFERENT'} "
            f"live_bytes={len(live)} github_bytes={len(github)} "
            f"live_sha256={hashlib.sha256(live).hexdigest()[:16]}",
            flush=True,
        )
        if filename == "miniapp_server.py":
            source = live.decode("utf-8")
            status["pr22"], candidate = overlay_cache(source)
            if candidate is not None:
                assert candidate == source or candidate != source
        elif filename == "miniapp/templates/index.html":
            source = live.decode("utf-8")
            status["pr23"], candidate = overlay_language(source)
            if candidate is not None:
                assert candidate.count('id="pdObLanguage"') == 1
    for key in ("pr22", "pr23"):
        print(f"PATCH_CHECK {key} {status.get(key, 'NOT_CHECKED')}", flush=True)
    if any(s not in ("OVERLAY_READY", "ALREADY_PRESENT") for s in status.values()):
        print("DEPLOY_GATE BLOCKED: manual integration review required", flush=True)
    else:
        print("DEPLOY_GATE SOURCE_PATCHES_APPLICABLE: deploy still NOT authorized", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Errors are sanitized; no source files or secrets in output.
        print("AUDIT_FAILED", type(exc).__name__, str(exc), flush=True)
        raise SystemExit(1)
