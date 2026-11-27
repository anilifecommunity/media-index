"""Shared identity golden vectors, schema constraints and append-only alias bindings."""

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from media_identity_v2 import anilist_kind, append_alias_ledger, apply_alias_ledger, canonical_key, reconcile_alias_ledger, source_key, validate_alias_ledger, validate_ref

root = Path(__file__).resolve().parent.parent
vectors = json.loads((root / "fixtures/v2/identity-vectors.json").read_text(encoding="utf-8"))
schema = json.loads((root / "schema/v2/media-ref.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())
registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
ledger_schema = json.loads((root / "schema/v2/alias-ledger.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(ledger_schema)
ledger_validator = Draft202012Validator(ledger_schema, registry=registry, format_checker=FormatChecker())


def valid(ref):
    validator.validate(ref)
    validate_ref(ref)


def refused(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid identity was accepted")


refs = []
for vector in vectors["canonical"]:
    assert canonical_key(vector["kind"], vector["namespace"], vector["id"]) == vector["mediaKey"]
    ref = {key: vector[key] for key in ("kind", "mediaKey", "format")}
    ref["aliases"] = [{"namespace": vector["namespace"], "id": vector["id"], "verified": True,
                       "provenance": {"source": "contract-fixture"}}]
    valid(ref)
    refs.append(ref)
assert len({(ref["kind"], ref["mediaKey"]) for ref in refs}) == len(refs)
for vector in vectors["source"]:
    engine, repository, provider, kind, item = vector["parts"]
    source = dict(zip(("engine", "repositoryId", "providerId", "stableItemId"), (engine, repository, provider, item)))
    source["provenance"] = {"source": "contract-fixture"}
    assert source_key(kind, source) == vector["mediaKey"]
    ref = {"kind": kind, "mediaKey": vector["mediaKey"], "aliases": [], "sourceRef": source}
    valid(ref)
    for field in ("repositoryId", "providerId", "stableItemId"):
        altered = {**source, field: source[field] + "-other"}
        assert source_key(kind, altered) != vector["mediaKey"]
    refused(lambda: validate_ref({**ref, "mediaKey": "src-" + "0" * 64}))
    for secret in ("https://example.test/item?token=secret", "item#secret", "user@host", "item?key=value", "item\n42"):
        refused(lambda: source_key(kind, {**source, "stableItemId": secret}))

assert anilist_kind("ANIME", "MOVIE") == "ANIME"
assert anilist_kind("MANGA", "NOVEL") == "NOVEL"
assert anilist_kind("MANGA", None) is None
assert anilist_kind("MANGA", "FUTURE_FORMAT") is None
assert vectors["legacyNovelProjection"]["from"]["mediaKey"] == vectors["legacyNovelProjection"]["to"]["mediaKey"]
for bad_id in (True, False, 0, -1, "42", 1.5, 9_007_199_254_740_992):
    refused(lambda: canonical_key("ANIME", "anilist:anime", bad_id))
refused(lambda: canonical_key("MOVIE", "anilist:anime", 42))
refused(lambda: validate_ref({**refs[0], "kind": "MOVIE"}))
refused(lambda: validate_ref({**refs[1], "format": "NOVEL"}))
unverified = copy.deepcopy(refs[0])
unverified["aliases"][0]["verified"] = False
refused(lambda: validate_ref(unverified))
refused(lambda: validate_ref({**refs[0], "aliases": refs[0]["aliases"] * 2}))
imdb = {"namespace": "imdb", "id": "tt1234567", "verified": True, "provenance": {"source": "fixture"}}
valid({**refs[3], "aliases": refs[3]["aliases"] + [imdb]})

entry = {"alias": refs[0]["aliases"][0], "target": {"kind": "ANIME", "mediaKey": "al-42"}}
assert append_alias_ledger([entry], [entry]) == [entry]
assert append_alias_ledger([], [entry]) == [entry]
refused(lambda: append_alias_ledger([entry], [{**entry, "target": {"kind": "ANIME", "mediaKey": "al-99"}}]))
refused(lambda: append_alias_ledger([], [{**entry, "alias": {**entry["alias"], "verified": False}}]))
refused(lambda: append_alias_ledger([], [{**entry, "target": {"kind": "ANIME", "mediaKey": "tmdb-movie-42"}}]))
movie_source = {"engine": "stremio", "repositoryId": "official", "providerId": "video", "stableItemId": "42", "provenance": {"source": "verified-fixture"}}
source_binding = {"sourceRef": movie_source, "verified": True, "target": {"kind": "MOVIE", "mediaKey": "tmdb-movie-42"}}
bindings = append_alias_ledger([entry], [source_binding])
ledger_validator.validate({"schemaVersion": "2.0.0", "bindings": bindings})
assert entry in bindings and source_binding in bindings
assert source_key("MOVIE", movie_source) == vectors["source"][2]["mediaKey"]
refused(lambda: append_alias_ledger(bindings, [{**source_binding, "target": {"kind": "MOVIE", "mediaKey": "tmdb-movie-99"}}]))

conflicts = json.loads((root / "fixtures/v2/alias-conflict-vectors.json").read_text(encoding="utf-8"))
empty = {"schemaVersion": "2.0.0", "bindings": []}
contested = conflicts["refs"]
original = copy.deepcopy(contested)
fresh = reconcile_alias_ledger(empty, contested)
ledger_validator.validate(fresh)
assert all(entry["alias"]["namespace"] != "mal:anime" for entry in fresh["bindings"])
assert fresh["unresolvedAliases"][0]["reason"] == conflicts["expected"]["reason"]
assert fresh["unresolvedAliases"][0]["candidates"] == conflicts["expected"]["candidates"]
assert reconcile_alias_ledger(empty, list(reversed(contested))) == fresh
projected = apply_alias_ledger(contested, fresh)
assert [ref["mediaKey"] for ref in projected] == conflicts["expected"]["primaryMediaKeysAfterReconciliation"]
assert all(not ref["aliases"][1]["verified"] and ref["aliases"][0]["verified"] for ref in projected)
assert contested == original
prior = {**empty, "bindings": [conflicts["priorBinding"], source_binding]}
historical = reconcile_alias_ledger(prior, contested)
assert conflicts["priorBinding"] in historical["bindings"] and source_binding in historical["bindings"]
assert reconcile_alias_ledger(historical, []) == historical  # Absence is not new resolving evidence.
changed = reconcile_alias_ledger(prior, contested[1:])
assert changed["unresolvedAliases"][0]["reason"] == "changed"
assert conflicts["priorBinding"] in changed["bindings"]
assert len(changed["unresolvedAliases"][0]["candidates"]) == 2
resolved = reconcile_alias_ledger(historical, contested[:1])
assert resolved["unresolvedAliases"] == []
assert conflicts["priorBinding"] in resolved["bindings"]
unverified = copy.deepcopy(contested[:1])
unverified[0]["aliases"][1]["verified"] = False
assert reconcile_alias_ledger(empty, unverified)["unresolvedAliases"][0]["reason"] == "unverified"
assert apply_alias_ledger([ref], fresh)[0] == ref  # Source-only local identity survives unrelated conflicts.
for invalid in (
    {**fresh, "unresolvedAliases": fresh["unresolvedAliases"] * 2},
    {**fresh, "unresolvedAliases": [{**fresh["unresolvedAliases"][0], "candidates": conflicts["expected"]["candidates"][:1]}]},
    {**empty, "unresolvedAliases": changed["unresolvedAliases"]},
    {**fresh, "unresolvedAliases": [{**fresh["unresolvedAliases"][0], "alias": {**fresh["unresolvedAliases"][0]["alias"], "verified": True}}]},
):
    refused(lambda: validate_alias_ledger(invalid))
refused(lambda: append_alias_ledger([], [{**entry, "target": {"kind": "ANIME", "mediaKey": "al-9007199254740992"}}]))
# A disputed primary origin cannot be downgraded into a seemingly valid canonical record.
primary_conflict = {**fresh, "unresolvedAliases": [{
    "alias": {**contested[0]["aliases"][0], "verified": False}, "reason": "unverified",
    "candidates": [{"kind": "ANIME", "mediaKey": "al-17295"}],
}]}
refused(lambda: apply_alias_ledger(contested, primary_conflict))
print("all v2 identity/schema checks passed")
