"""Exercise the actual v2 writer/verifier, publication failure and retained generations."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import build_release_v2
import release_v2 as v2
from release_lib import canonical_bytes
from test_release import make_fixture

ROOT = Path(__file__).resolve().parent.parent
STAMP = "2026-11-27T00:00:00Z"
RECORDS = json.loads((ROOT / "fixtures/v2/record-vectors.json").read_text(encoding="utf-8"))["records"]
DETAILS = [r for r in RECORDS if r.get("recordType") == "detail"]
PAGES = [r for r in RECORDS if r.get("recordType") in {"episodes", "chapters"}]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="anilife-v2-test-")
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "v2"

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, details=None, pages=None, publish=True):
        return v2.write_release(self.root, DETAILS if details is None else details,
                                PAGES if pages is None else pages, STAMP, publish=publish)

    def test_all_kinds_and_byte_stable_rebuild(self):
        source = copy.deepcopy(DETAILS)
        first = self.build()
        pointer = (self.root / "manifest.json").read_bytes()
        second = v2.write_release(self.root, list(reversed(DETAILS)), list(reversed(PAGES)), "2026-11-28T00:00:00Z", publish=True)
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(pointer, (self.root / "manifest.json").read_bytes())
        self.assertEqual(len(DETAILS), v2.verify(self.root)["details"])
        self.assertEqual(source, DETAILS)
        self.assertEqual(6, len({d["ref"]["kind"] for d in DETAILS}))
        self.assertFalse([p for p in self.root.glob(".v2-*") if p.is_dir()])

    def test_tampering_and_unlisted_files_fail_without_changing_pointer(self):
        result = self.build()
        generation = self.root / "releases" / result["manifest"]["releaseId"]
        pointer = (self.root / "manifest.json").read_bytes()
        payload = next(generation.glob("media/*/*.json"))
        original = payload.read_bytes()
        payload.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            v2.verify(self.root)
        payload.write_bytes(original)
        (generation / "unexpected.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            v2.verify(self.root)
        self.assertEqual(pointer, (self.root / "manifest.json").read_bytes())

    def test_bad_units_are_rejected_after_hashing_and_keep_previous_pointer(self):
        self.build()
        pointer = (self.root / "manifest.json").read_bytes()
        pages = copy.deepcopy(PAGES)
        pages[0]["offset"] = 1
        with self.assertRaises(ValueError):
            self.build(pages=pages)
        self.assertEqual(pointer, (self.root / "manifest.json").read_bytes())
        duplicate = copy.deepcopy(PAGES[0])
        duplicate["offset"] = len(duplicate["units"])
        with self.assertRaises(ValueError):
            self.build(pages=PAGES + [duplicate])
        self.assertEqual(pointer, (self.root / "manifest.json").read_bytes())

    def test_failed_swap_keeps_last_good_and_rollback_repairs_corrupt_pointer(self):
        first = self.build()
        old = (self.root / "manifest.json").read_bytes()
        changed = copy.deepcopy(DETAILS)
        changed[0]["titles"]["display"] += " revised"
        candidate = self.build(details=changed, publish=False)
        self.assertNotEqual(first["manifest"]["releaseId"], candidate["manifest"]["releaseId"])
        with mock.patch("release_v2.os.replace", side_effect=OSError("simulated storage failure")):
            with self.assertRaises(OSError):
                v2.promote(self.root, candidate["manifest"]["releaseId"])
        self.assertEqual(old, (self.root / "manifest.json").read_bytes())
        v2.promote(self.root, candidate["manifest"]["releaseId"])
        (self.root / "manifest.json").write_bytes(b"broken")
        v2.promote(self.root, first["manifest"]["releaseId"])
        self.assertEqual(old, (self.root / "manifest.json").read_bytes())
        self.assertEqual(2, len(list((self.root / "releases").iterdir())))

    def test_existing_generation_never_overwritten(self):
        result = self.build()
        path = self.root / "releases" / result["manifest"]["releaseId"] / "manifest.json"
        path.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(b"invalid", path.read_bytes())

    def test_source_binding_history_survives_serving_rollback(self):
        first = self.build()
        source = next(d["ref"]["sourceRef"] for d in DETAILS if d["ref"]["kind"] == "MOVIE" and "sourceRef" in d["ref"])
        binding = {"sourceRef": source, "verified": True, "target": {"kind": "MOVIE", "mediaKey": "tmdb-movie-42"}}
        second = v2.write_release(self.root, DETAILS, PAGES, STAMP, publish=True, source_bindings=[binding])
        self.assertIn(binding, second["ledger"]["bindings"])
        v2.promote(self.root, first["manifest"]["releaseId"])
        old = (self.root / "manifest.json").read_bytes()
        with self.assertRaises(ValueError):
            v2.write_release(self.root, DETAILS, PAGES, STAMP, publish=True,
                             source_bindings=[{**binding, "target": {"kind": "MOVIE", "mediaKey": "tmdb-movie-99"}}])
        self.assertEqual(old, (self.root / "manifest.json").read_bytes())
        self.assertIn(binding, self.build()["ledger"]["bindings"])

    def test_verified_alias_change_is_quarantined_without_reassignment(self):
        details = copy.deepcopy(DETAILS)
        anime = next(d for d in details if d["ref"]["kind"] == "ANIME")
        claim = {"namespace": "mal:anime", "id": 123, "verified": True, "provenance": {"source": "contract-test"}}
        anime["ref"]["aliases"].append(claim)
        first = self.build(details=details)
        changed = copy.deepcopy(anime)
        changed["ref"]["mediaKey"] = "al-99"
        changed["ref"]["aliases"][0]["id"] = 99
        changed["franchise"] = {"coverage": "unresolved", "truncated": False,
                                "members": [{**changed["franchise"]["members"][0], "ref": {"kind": "ANIME", "mediaKey": "al-99"}}],
                                "unresolved": [{"kind": "ANIME", "mediaKey": "al-99"}]}
        result = self.build(details=[changed], pages=[])
        bound = next(b for b in result["ledger"]["bindings"] if b.get("alias", {}).get("namespace") == "mal:anime")
        self.assertEqual(anime["ref"]["mediaKey"], bound["target"]["mediaKey"])
        self.assertEqual("changed", result["ledger"]["unresolvedAliases"][0]["reason"])
        v2.promote(self.root, first["manifest"]["releaseId"])
        self.assertEqual("changed", self.build(details=[changed], pages=[])["ledger"]["unresolvedAliases"][0]["reason"])

    def test_missing_bootstrap_and_false_complete_claims_are_rejected(self):
        result = self.build()
        generation = self.root / "releases" / result["manifest"]["releaseId"]
        path = generation / "manifest.json"
        manifest = json.loads(path.read_bytes())
        for group in ("catalogue", "search", "identity"):
            broken = copy.deepcopy(manifest)
            broken["bootstrap"][group].pop()
            path.write_bytes(canonical_bytes(broken))
            with self.assertRaises(ValueError):
                v2.verify_generation(generation, result["manifest"]["releaseId"])
        path.write_bytes(canonical_bytes(manifest))
        details = copy.deepcopy(DETAILS)
        details[0]["franchise"]["members"].append({**details[0]["franchise"]["members"][0],
            "ref": {"kind": "ANIME", "mediaKey": "al-999"}, "order": 1})
        details[0]["franchise"].update(coverage="complete", unresolved=[])
        with self.assertRaises(ValueError):
            self.build(details=details)
        pages = copy.deepcopy(PAGES)
        pages[0]["coverage"] = "complete"
        with self.assertRaises(ValueError):
            self.build(pages=pages)

    def test_no_v1_namespace_write_and_one_publisher_only(self):
        self.root.mkdir()
        pointer = canonical_bytes({"schemaVersion": "1.1.0", "releaseId": "existing-v1"})
        (self.root / "manifest.json").write_bytes(pointer)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(pointer, (self.root / "manifest.json").read_bytes())
        (self.root / "manifest.json").unlink()
        with v2.publication_lock(self.root):
            with self.assertRaises(OSError):
                with v2.publication_lock(self.root):
                    self.fail("second writer acquired the same namespace")

    def test_path_and_filesystem_link_escape(self):
        for path in ("../outside.json", "/outside.json", "C:/outside.json", "a\\b.json", "a/../b.json", "nul.json"):
            with self.assertRaises(ValueError):
                v2._path(self.root, path)
        result = self.build()
        generation = self.root / "releases" / result["manifest"]["releaseId"]
        payload = next(generation.glob("media/*/*.json"))
        outside = self.base / "outside.json"
        outside.write_bytes(payload.read_bytes())
        payload.unlink()
        try:
            payload.symlink_to(outside)
        except OSError:
            self.skipTest("host cannot create symlinks; CI Linux exercises the escape")
        with self.assertRaises(ValueError):
            v2.verify(self.root)

    def test_actual_legacy_pipeline_keeps_v1_and_source_bytes_untouched(self):
        data = make_fixture(self.base)
        before = {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()}
        policy = {"sources": [{"name": "anilist", "status": "verified", "permitted": True}]}
        with self.assertRaises(ValueError):
            build_release_v2.build(data, data, policy, generated_at=STAMP)
        with self.assertRaises(ValueError):
            build_release_v2.build(data, self.root, policy, limit=1, publish=True)
        result = build_release_v2.build(data, self.root, policy, generated_at=STAMP, publish=True)
        self.assertEqual(3, result["details"])
        self.assertEqual(before, {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()})
        policy_path = self.base / "blocked-policy.json"
        policy_path.write_text(json.dumps({"sources": [{"name": "anilist", "status": "unverified", "permitted": False}]}))
        old = (self.root / "manifest.json").read_bytes()
        self.assertEqual(1, build_release_v2.main(["--out", str(self.root), "--policy", str(policy_path), "--publish"]))
        policy_path.write_text(json.dumps(policy))
        self.assertEqual(1, build_release_v2.main(["--out", str(self.root), "--policy", str(policy_path), "--publish", "--limit", "1"]))
        with mock.patch("build_release_v2.publish_health.run", return_value={"state": "stale"}):
            self.assertEqual(1, build_release_v2.main(["--out", str(self.root), "--policy", str(policy_path), "--publish"]))
        self.assertEqual(old, (self.root / "manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
