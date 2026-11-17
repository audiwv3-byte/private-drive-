"""Tests for deterministic Issue #30 staging-only manifest: no live DB."""
import json
import tempfile
import unittest
from pathlib import Path

import pd_issue30_rc_build as rc


class ReleaseCandidateManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = rc.fetch_original_sources(__import__("os").environ.get("PA_API_TOKEN", ""))

    def test_reproduces_sha_pinned_release_manifest(self):
        manifest=rc.build_manifest(self.sources,Path(rc.__file__).parent)
        self.assertEqual(manifest["release_status"],"STAGING_ONLY_NOT_AUTHORIZED_FOR_PRODUCTION")
        self.assertTrue(all(manifest["contract_checks"].values()))
        self.assertEqual(len(manifest["source_files"]),4)
        self.assertEqual(len(manifest["repository_components"]),13)
        self.assertEqual(manifest["schema_migration_sequence"],
                         ["pd_document_review.ensure_tables","pd_issue30_document_storage_guard.ensure_tables"])
        self.assertNotIn("Token",json.dumps(manifest))
        self.assertNotIn("synthetic.jpg",json.dumps(manifest))

    def test_same_inputs_produce_identical_sha_manifest(self):
        one=rc.build_manifest(self.sources,Path(rc.__file__).parent)
        two=rc.build_manifest(self.sources,Path(rc.__file__).parent)
        self.assertEqual(one,two)

    def test_any_source_change_aborts_candidate(self):
        for name in rc.FILES:
            with self.subTest(path=name):
                changed=dict(self.sources)
                changed[name]=changed[name]+b"\n# change"
                with self.assertRaises(rc.CandidateBlocked):
                    rc.build_manifest(changed,Path(rc.__file__).parent)

    def test_missing_source_aborts_candidate(self):
        data=dict(self.sources)
        data.pop("miniapp_server.py")
        with self.assertRaises(rc.CandidateBlocked):
            rc.build_manifest(data,Path(rc.__file__).parent)

    def test_unexpected_source_aborts_candidate(self):
        data={**self.sources,"other.py":b"fake"}
        with self.assertRaises(rc.CandidateBlocked):
            rc.build_manifest(data,Path(rc.__file__).parent)

    def test_unpinned_helper_directory_aborts_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(rc.CandidateBlocked):
                rc.build_manifest(self.sources,temp)

    def test_required_helpers_are_content_hashes_not_github_blob_hashes(self):
        manifest=rc.build_manifest(self.sources,Path(rc.__file__).parent)
        module_name="pd_issue30_admin_review_routes.py"
        expected=rc.sha((Path(rc.__file__).parent/module_name).read_bytes())
        self.assertEqual(manifest["repository_components"][module_name]["sha256"],expected)

if __name__=="__main__":
    unittest.main()
