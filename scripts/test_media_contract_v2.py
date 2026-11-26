"""Offline coverage for all v2 record types and lossless legacy compatibility views."""

import copy
import hashlib
import json
from pathlib import Path

from jsonschema.exceptions import ValidationError
import media_contract_v2 as v2

ROOT = Path(__file__).resolve().parent.parent
checks = v2.validators()
vectors = json.loads((ROOT / "fixtures/v2/identity-vectors.json").read_text(encoding="utf-8"))
shared = json.loads((ROOT / "fixtures/v2/record-vectors.json").read_text(encoding="utf-8"))
for record in shared["records"]:
    v2.validate_record(record, checks)
assert {record["ref"]["kind"] for record in shared["records"] if record["recordType"] == "detail"} == v2.KINDS
progress = shared["progressIdentities"]
assert progress[0]["unitId"] == progress[1]["unitId"]
assert v2.canonical_bytes(progress[0]) != v2.canonical_bytes(progress[1])


def refused(call):
    try:
        call()
    except (ValueError, ValidationError):
        return
    raise AssertionError("Invalid v2 record was accepted")


source_files = list((ROOT / "fixtures/v1/releases").glob("*/media/*/*.json"))
before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
details = []
for path in source_files:
    legacy = json.loads(path.read_text(encoding="utf-8"))
    projected = v2.adapt_v1_media(legacy)
    v2.validate_record(projected, checks)
    assert projected["ref"]["mediaKey"] == legacy["mediaKey"]
    assert projected["titles"] == legacy["titles"]
    assert projected["images"] == legacy["images"]
    assert projected["franchise"]["coverage"] == "unresolved"
    details.append(projected)
assert details and before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
for path in (ROOT / "fixtures/v1/releases").glob("*/episodes/*/*.json"):
    legacy = json.loads(path.read_text(encoding="utf-8"))
    pages = v2.adapt_v1_episodes(legacy, declared_count=len(legacy["episodes"]))
    for page in pages:
        v2.validate_record(page, checks)
    units = [unit for page in pages for unit in page["units"]]
    assert [unit["displayOrdinal"] for unit in units] == [str(episode["number"]) for episode in legacy["episodes"]]
    assert all(unit["sourceOrdinal"] is None and unit["absoluteOrdinal"] is None for unit in units)

# The same number in another kind or namespace remains a separate catalogue/progress identity.
for vector in vectors["canonical"]:
    detail = copy.deepcopy(details[0])
    ref = {key: vector[key] for key in ("kind", "mediaKey", "format")}
    ref["aliases"] = [v2.alias(vector["namespace"], vector["id"], "contract-fixture")]
    detail.update(ref=ref, relations=[])
    detail["franchise"]["members"] = [{"ref": v2.target(ref), "order": 0, "role": "UNKNOWN", "sourceSeason": None,
                                        "absoluteOrdinal": None, "provenance": {"source": "contract-fixture"}}]
    detail["franchise"]["unresolved"] = [v2.target(ref)]
    v2.validate_record(detail, checks)
    row = v2.catalogue_row(detail)
    v2.validate_record({"schemaVersion": v2.VERSION, "recordType": "catalogue", "coverage": "partial", "rows": [row]}, checks)
    v2.validate_record({"schemaVersion": v2.VERSION, "recordType": "search", "coverage": "partial", "entries": [v2.search_entry(detail)]}, checks)

ref = {"kind": "NOVEL", "mediaKey": "al-30001"}
unit = {"unitId": "source-chapter-7", "displayOrdinal": "1.5", "sourceOrdinal": "raw-7", "sourceSeason": None,
        "absoluteOrdinal": None, "title": None, "availability": "unknown", "provenance": {"source": "contract-fixture"}}
chapters = {"schemaVersion": v2.VERSION, "recordType": "chapters", "ref": ref, "coverage": "partial", "offset": 0, "units": [unit]}
v2.validate_record(chapters, checks)
refused(lambda: v2.validate_record({**chapters, "units": [unit, unit]}, checks))
refused(lambda: v2.validate_record({**chapters, "ref": {"kind": "TV", "mediaKey": "tmdb-tv-42"}}, checks))
refused(lambda: v2.validate_record({**chapters, "units": [{**unit, "unitId": "https://host/stream?token=x"}]}, checks))

unknown = copy.deepcopy(details[0])
unknown.update(isAdult=None, visibility="unknown-conservative")
v2.validate_record(unknown, checks)
refused(lambda: v2.validate_record({**unknown, "visibility": "general"}, checks))
broken = copy.deepcopy(unknown)
broken["franchise"]["coverage"] = "complete"
refused(lambda: v2.validate_record(broken, checks))
oversized = copy.deepcopy(unknown)
oversized["titles"].update(english="x" * 60000, romaji="x" * 60000, native="x" * 60000, synonyms=[{"value": "x" * 1024, "source": "fixture"}] * 128)
oversized["synopsis"] = "x" * 60000
checks[0].validate(oversized)
refused(lambda: v2.validate_record(oversized, checks))

file = {"path": "media/ANIME/f3/al-1.json", "sha256": "0" * 64, "bytes": 100}
bucket = {"schemaVersion": v2.VERSION, "recordType": "bucket", "bucket": "f3", "files": [file]}
v2.validate_record(bucket, checks)
refused(lambda: v2.validate_record({**bucket, "files": [file, file]}, checks))
for path in ("../secret.json", "/absolute.json", "a/../secret.json", "a//file.json", "https://other/file.json"):
    refused(lambda: v2.validate_record({**bucket, "files": [{**file, "path": path}]}, checks))
manifest = {"schemaVersion": v2.VERSION, "recordType": "manifest", "contract": "anilife.media", "releaseId": "rel-" + "0" * 16,
            "contentHash": "0" * 64, "generatedAt": "2026-11-25T00:00:00Z", "coverage": {kind: "unresolved" for kind in v2.KINDS},
            "buckets": [{**file, "path": "manifests/f3.json"}], "bootstrap": {"catalogue": [], "search": [], "identity": []}}
v2.validate_record(manifest, checks)
v2.validate_record({"schemaVersion": v2.VERSION, "recordType": "pointer", "releaseId": manifest["releaseId"],
                    "manifest": {**file, "path": "releases/rel-0000000000000000/manifest.json"}}, checks)
print("all v2 metadata/unit contract checks passed")
