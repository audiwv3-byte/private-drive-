"""PRIVATE DRIVE Issue #30 release candidate manifest — GET-only, NON-DEPLOYABLE.

Reads only verified PythonAnywhere *source files* via GET. Produces a SHA-256
manifest of the deterministic patched source and repository helpers; does not
download user records, connect to a real DB or write anything to PythonAnywhere.
Never contains secrets, real documents, production source text or personal data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import pd_issue30_patch_live_dispatcher_offline as dispatcher
import pd_issue30_patch_live_wsgi_offline as wsgi
import pd_issue30_patch_live_admin_html_offline as html

ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES = {
    "pd_onboarding.py": dispatcher.onboarding.EXPECTED_SHA256,
    "miniapp_server.py": wsgi.EXPECTED_SHA256,
    "miniapp/templates/index.html": html.EXPECTED_SHA256,
}
# Exact set needed to run the combined opt-in server/UI feature; no unrelated
# service source, environment variables, credentials or personal data.
HELPERS = (
    "pd_document_review.py",
    "pd_issue30_stage_adapter.py",
    "pd_issue30_decision_bridge.py",
    "pd_issue30_document_storage_guard.py",
    "pd_issue30_admin_review_routes.py",
    "miniapp/static/pd_issue30_admin_review.js",
    "miniapp/static/pd_issue30_admin_review.css",
)
PATCHERS = (
    "pd_issue30_patch_live_onboarding_offline.py",
    "pd_issue30_patch_live_dispatcher_offline.py",
    "pd_issue30_patch_live_wsgi_offline.py",
    "pd_issue30_patch_live_admin_html_offline.py",
)
MIGRATIONS = ("pd_document_review.ensure_tables", "pd_issue30_document_storage_guard.ensure_tables")


class CandidateBlocked(RuntimeError):
    pass


def sha(value):
    return hashlib.sha256(value).hexdigest()


def build_manifest(sources, root):
    """Inputs MUST be original GET-only verified source bytes, never production DB."""
    base = Path(root).resolve()
    if set(sources) != set(FILES):
        raise CandidateBlocked("Missing/unexpected source payloads")
    for name, expected in FILES.items():
        if not isinstance(sources[name], bytes) or sha(sources[name]) != expected:
            raise CandidateBlocked("STOP: deployed source fingerprint differs: " + name)
    patched = {
        "pd_onboarding.py": dispatcher.patch_source(sources["pd_onboarding.py"]).encode(),
        "miniapp_server.py": wsgi.patch_source(sources["miniapp_server.py"]).encode(),
        "miniapp/templates/index.html": html.patch_source(sources["miniapp/templates/index.html"]).encode(),
    }
    onboarding_src = patched["pd_onboarding.py"].decode()
    wsgi_src = patched["miniapp_server.py"].decode()
    admin_html = patched["miniapp/templates/index.html"].decode()
    gates = {
        "pilot_guard": "pd_issue30_store.pilot_insert_missing" in onboarding_src,
        "admin_decision_bridge": "pd_issue30_bridge.guard_admin_approval" in onboarding_src,
        "no_legacy_photo_upsert": "ON CONFLICT(telegram_id,side) DO UPDATE SET image" not in onboarding_src,
        "admin_route_registered_once": wsgi_src.count("pd_issue30_admin_routes.register(app,core,auth,pd_onboarding.read_photos)") == 1,
        "html_review_panel_once": admin_html.count("mountIssue30Review(") == 1,
        "html_server_review_gate": "!pdDocsApproved" in admin_html,
        "html_mobile_css": '/static/pd_issue30_admin_review.css' in admin_html,
        "html_document_review_js": '/static/pd_issue30_admin_review.js' in admin_html,
    }
    if not all(gates.values()):
        raise CandidateBlocked("STOP: release candidate contract failed")
    sources_manifest = {}
    for name in sorted(FILES):
        sources_manifest[name] = {
            "baseline_sha256": FILES[name],
            "patched_sha256": sha(patched[name]),
            "patched_bytes": len(patched[name]),
        }
    code_manifest = {}
    for name in sorted(HELPERS + PATCHERS):
        target = (base / name).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise CandidateBlocked("Required helper missing: " + name)
        content = target.read_bytes()
        if not content:
            raise CandidateBlocked("Empty required helper: " + name)
        code_manifest[name] = {"sha256": sha(content), "bytes": len(content)}
    return {
        "candidate": "PRIVATE DRIVE Issue #30",
        "release_status": "STAGING_ONLY_NOT_AUTHORIZED_FOR_PRODUCTION",
        "schema_migration_sequence": list(MIGRATIONS),
        "source_files": sources_manifest,
        "repository_components": code_manifest,
        "contract_checks": gates,
        "workflow": "backup-then-migrate-then-publish-all-components-atomically-then-smoke",
        "rollback": "restore-code-and-wsgi-first; preserve-new-additive-tables; no-automatic-full-db-restore",
    }


def fetch_original_sources(token):
    """GET-only; never output or persist source bodies."""
    import requests
    if not token:
        raise CandidateBlocked("Missing token for GET-only source validation")
    session = requests.Session()
    session.headers["Authorization"] = "Token " + token.strip()
    results = {}
    for name in FILES:
        url = "https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path" + quote(ROOT + name, safe="/")
        response = session.get(url, timeout=35)
        response.raise_for_status()
        results[name] = response.content
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="issue30_rc_manifest.json")
    args = parser.parse_args()
    token = os.environ.get("PA_API_TOKEN", "")
    data = build_manifest(fetch_original_sources(token), Path(__file__).parent)
    destination = Path(args.manifest)
    # Only a manifest (never fetched source files) is persisted as a CI artifact.
    destination.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("RC_STAGING_ONLY")
    print("CHECKS", len(data["contract_checks"]), "PASSED")
    print("SOURCE_BASELINES", len(data["source_files"]), "VERIFIED")
    print("MODULES", len(data["repository_components"]), "SHA256_VERIFIED")
    print("MANIFEST_SHA256", sha(destination.read_bytes()))


if __name__ == "__main__":
    main()
