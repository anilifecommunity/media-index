"""Contract tests for the v1 release pipeline.

Plain asserts and a bare runner, matching ``test_konoha_build.py``: the
release scripts must run without a test framework installed.

    python scripts/test_release.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import tempfile

import build_release
import release_lib as lib
import rollback_release
import validate_release
from validate_release import VerificationError, verify_release

FAILURES: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        FAILURES.append(f"{label}\n    expected {expected!r}\n    got      {actual!r}")


def check_true(label: str, value: bool) -> None:
    if not value:
        FAILURES.append(f"{label}\n    expected truthy, got {value!r}")


def expect_refusal(label: str, call) -> None:
    try:
        call()
    except VerificationError:
        return
    FAILURES.append(f"{label}\n    expected VerificationError, nothing raised")


def write(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lib.canonical_bytes(payload))


def make_fixture(root: pathlib.Path) -> pathlib.Path:
    data = root / "data"
    updated = "2026-11-17T00:00:00Z"

    index = [
        {
            "id": 1,
            "title": "Cowboy Bebop",
            "slug": "cowboy-bebop-1",
            "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx1.png",
            "poster_color": "#f16b50",
            "year": 1998,
            "status": "FINISHED",
            "format": "TV",
            "episodes": 2,
            "score": 86,
            "popularity": 474676,
            "genres": ["Action"],
        },
        {
            "id": 2,
            "title": "Unknown Adult State",
            "slug": "unknown-2",
            "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx2.png",
            "year": 2001,
            "status": "FINISHED",
            "format": "TV",
            "episodes": 12,
            "score": None,
            "popularity": 10,
            "genres": [],
        },
        {
            "id": 3,
            "title": "Adult Example",
            "slug": "adult-3",
            "poster": None,
            "year": 2020,
            "status": "RELEASING",
            "format": "ONA",
            "episodes": None,
            "score": 70,
            "popularity": 5,
            "genres": ["Ecchi"],
        },
    ]
    write(data / "index.json", index)
    write(data / "sync-status.json", {"source": "anilist+tmdb", "generator": "test", "last_updated": updated})
    write(data / "stats.json", {"total": 3, "episodes": 2, "last_updated": updated})
    write(
        data / "id-map.json",
        {
            "1": {"mal": 1, "tmdb": 30991, "confidence": "HIGH", "updated_at": updated},
            "2": {"mal": 2, "confidence": "MAPPED", "updated_at": updated},
            "3": {"mal": None, "confidence": None, "updated_at": updated},
        },
    )

    write(
        data / "anime" / "0" / "1" / "index.json",
        {
            "ids": {"anilist": 1, "mal": 1},
            "titles": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop", "native": "カウボーイビバップ"},
            "format": "TV",
            "status": "FINISHED",
            "season": "SPRING",
            "season_year": 1998,
            "episodes": 2,
            "duration": 24,
            "description": "Bounty hunters.<br><br>In space.",
            "genres": ["Action"],
            "score_anilist": 86,
            "popularity": 474676,
            "images": {
                "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx1.png",
                "poster_color": "#f16b50",
                "banner": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/1.jpg",
                "logo": "https://image.tmdb.org/t/p/w500/logo.png",
            },
            "anilist": {
                "id": 1,
                "title": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop", "native": "カウボーイビバップ"},
                "description": "Bounty hunters.<br><br>In space.",
                "format": "TV",
                "status": "FINISHED",
                "episodes": 2,
                "duration": 24,
                "genres": ["Action"],
                "averageScore": 86,
                "popularity": 474676,
                "isAdult": False,
                "countryOfOrigin": "JP",
                "tags": [{"name": "Space", "rank": 94, "isMediaSpoiler": False, "isGeneralSpoiler": False}],
                "studios": {"nodes": [{"id": 14, "name": "Sunrise", "isAnimationStudio": True}]},
                "startDate": {"year": 1998, "month": 4, "day": 3},
                "endDate": {"year": 1999, "month": 4, "day": 24},
                "relations": {
                    "edges": [
                        {
                            "relationType": "ADAPTATION",
                            "node": {
                                "id": 30173,
                                "idMal": 173,
                                "format": "MANGA",
                                "title": {"romaji": "Cowboy Bebop"},
                            },
                        },
                        {
                            "relationType": "SEQUEL",
                            "node": {
                                "id": 3,
                                "idMal": 3,
                                "format": "ONA",
                                "title": {"romaji": "Adult Example"},
                            },
                        },
                    ]
                },
            },
            "series": [1, 3],
            "recommendations": [{"id": 3, "title": {"romaji": "Adult Example"}}],
            "bangumi": {
                "id": 253,
                "name": "カウボーイビバップ",
                "name_cn": "星际牛仔",
                "search_names": ["Cowboy Bebop: The Movie"],
                "confidence": "STRONG",
            },
        },
    )
    write(
        data / "anime" / "0" / "1" / "episodes.json",
        [
            {
                "number": 1,
                "title": "Asteroid Blues",
                "overview": "Spike and Jet.",
                "air_date": "1998-04-03",
                "still": "https://image.tmdb.org/t/p/w500/still1.jpg",
                "runtime": 25,
                "rating": 7.02,
            },
            {
                "number": 2,
                "title": "Stray Dog Strut",
                "overview": None,
                "air_date": "",
                "still": None,
                "runtime": 25,
                "rating": None,
            },
        ],
    )
    # Deliberately no `anilist` block: the adult state is unknown, not "safe".
    write(
        data / "anime" / "0" / "2" / "index.json",
        {
            "ids": {"anilist": 2, "mal": 2},
            "titles": {"romaji": "Unknown Adult State", "english": None, "native": None},
            "format": "TV",
            "status": "FINISHED",
            "episodes": 12,
            "images": {},
        },
    )
    write(
        data / "anime" / "0" / "3" / "index.json",
        {
            "ids": {"anilist": 3, "mal": None},
            "titles": {"romaji": "Adult Example", "english": None, "native": None},
            "format": "ONA",
            "status": "RELEASING",
            "episodes": None,
            "images": {},
            "anilist": {"id": 3, "format": "ONA", "isAdult": True, "description": None},
        },
    )
    return data


def test_build(root: pathlib.Path, data: pathlib.Path) -> dict:
    out = root / "out"
    policy = {"sources": [{"name": "anilist", "status": "unverified", "permitted": False, "lastUpdated": None}]}
    summary = build_release.build(data, out, policy, generated_at="2026-11-17T00:00:00Z")
    check("media count", summary["counts"]["media"], 3)
    check("episode list count", summary["counts"]["episodeLists"], 1)
    check("episode count", summary["counts"]["episodes"], 2)
    check("adult count", summary["counts"]["adult"], 1)
    check("relation count", summary["counts"]["relations"], 2)
    check_true("release id shape", summary["releaseId"].startswith("rel-"))

    release_dir = out / "releases" / summary["releaseId"]
    media = json.loads((release_dir / "media" / lib.bucket_of("al-1") / "al-1.json").read_text("utf-8"))
    check("media key", media["mediaKey"], "al-1")
    check("title native", media["titles"]["native"], "カウボーイビバップ")
    check("synopsis strips markup", media["synopsis"]["text"], "Bounty hunters.\n\nIn space.")
    check("synopsis source", media["synopsis"]["source"], "anilist")
    check("synonym source", media["titles"]["synonyms"][0]["source"], "bangumi")
    check("tag spoiler", media["tags"][0]["spoiler"], False)
    check("image permission", media["images"]["poster"]["permission"], "reference-only")
    check("image attribution", media["images"]["poster"]["attribution"], "anilist")
    check("series keys", media["series"], ["al-1", "al-3"])

    release_manifest = json.loads((release_dir / "manifest.json").read_text("utf-8"))
    check(
        "source status carries snapshot time",
        release_manifest["sources"][0]["lastUpdated"],
        "2026-11-17T00:00:00Z",
    )

    manga_edge = next(edge for edge in media["relations"] if edge["kind"] == "MANGA")
    check("manga relation resolved", manga_edge["resolved"], False)
    check("manga relation key", manga_edge["mediaKey"], None)
    anime_edge = next(edge for edge in media["relations"] if edge["kind"] == "ANIME")
    check("anime relation resolved", anime_edge["resolved"], True)
    check("anime relation key", anime_edge["mediaKey"], "al-3")

    unknown = json.loads((release_dir / "media" / lib.bucket_of("al-2") / "al-2.json").read_text("utf-8"))
    check("unknown adult stays null", unknown["isAdult"], None)
    check("unknown adult visibility", unknown["visibility"], "unknown-conservative")

    episodes = json.loads(
        (release_dir / "episodes" / lib.bucket_of("al-1") / "al-1.json").read_text("utf-8")
    )
    check("episode availability", episodes["availability"], "AVAILABLE")
    check("episode number", episodes["episodes"][0]["number"], 1)
    check("episode null air date", episodes["episodes"][1]["airDate"], None)
    check("episode still source", episodes["episodes"][0]["still"]["source"], "tmdb")
    check("episode null still", episodes["episodes"][1]["still"], None)

    catalog = {}
    for path in (release_dir / "catalog").glob("*.json"):
        payload = json.loads(path.read_text("utf-8"))
        for row in payload["rows"]:
            catalog[row["mediaKey"]] = row
    check("catalog rows", len(catalog), 3)
    check("episodesAvailable false", catalog["al-2"]["episodesAvailable"], False)
    check("catalog visibility", catalog["al-2"]["visibility"], "unknown-conservative")
    check("catalog poster source", catalog["al-1"]["poster"]["source"], "anilist")

    search = {}
    for path in (release_dir / "search" / "universal").glob("*.json"):
        payload = json.loads(path.read_text("utf-8"))
        for row in payload["rows"]:
            search.setdefault(row["mediaKey"], set()).update(row["names"])
    check_true("romaji searchable", "cowboy bebop" in search["al-1"])
    check_true("native searchable", "カウボーイビバップ" in search["al-1"])
    check_true("chinese alias searchable", "星际牛仔" in search["al-1"])

    c_bucket = json.loads((release_dir / "search" / "universal" / "c.json").read_text("utf-8"))
    c_row = next(row for row in c_bucket["rows"] if row["mediaKey"] == "al-1")
    check_true("same-bucket aliases retained", len(c_row["names"]) >= 2)

    validation = verify_release(out, "current", full=True, schemas=False)
    check_true("files verified", validation["filesVerified"] > 0)
    check("verified media", validation["media"], 3)

    before = (release_dir / "media" / lib.bucket_of("al-1") / "al-1.json").read_bytes()
    legacy_before = (data / "index.json").read_bytes()
    again = build_release.build(data, out, policy, generated_at="2026-11-17T00:00:00Z")
    check("reused release", again["reused"], True)
    check("reused id", again["releaseId"], summary["releaseId"])
    check("no content rewrite", (release_dir / "media" / lib.bucket_of("al-1") / "al-1.json").read_bytes(), before)
    check("legacy tree untouched", (data / "index.json").read_bytes(), legacy_before)

    build_release.write_pointer(out, summary, published_at="2026-11-17T00:00:00Z")
    pointer = json.loads((out / "manifest.json").read_text("utf-8"))
    check("pointer release", pointer["releaseId"], summary["releaseId"])
    verify_release(out, "current", full=True, schemas=False)
    return summary


def test_rollback(root: pathlib.Path, data: pathlib.Path) -> None:
    out = root / "out"
    policy = {"sources": [{"name": "anilist", "status": "verified", "permitted": True, "lastUpdated": None}]}
    first = build_release.build(data, out, policy, generated_at="2026-11-17T00:00:00Z")
    build_release.write_pointer(out, first, published_at="2026-11-17T00:00:00Z")

    detail_path = data / "anime" / "0" / "1" / "index.json"
    detail = json.loads(detail_path.read_text("utf-8"))
    detail["titles"]["english"] = "Cowboy Bebop (changed)"
    write(detail_path, detail)

    second = build_release.build(data, out, policy, generated_at="2026-11-18T00:00:00Z")
    build_release.write_pointer(out, second, published_at="2026-11-18T00:00:00Z")
    check_true("new content hash", second["contentHash"] != first["contentHash"])
    check("two releases", len(validate_release._release_ids(out)), 2)

    rolled = rollback_release.rollback(out, "previous")
    check("rollback target", rolled["releaseId"], first["releaseId"])
    pointer = json.loads((out / "manifest.json").read_text("utf-8"))
    check("pointer after rollback", pointer["releaseId"], first["releaseId"])
    verify_release(out, "current", full=True, schemas=False)

    pointer_path = out / "manifest.json"
    good_pointer = pointer_path.read_bytes()
    broken = json.loads(good_pointer)
    broken["releaseId"] = "rel-0000000000000000"
    write(pointer_path, broken)
    expect_refusal("missing pointer target rejected", lambda: verify_release(out, "current", full=False))
    pointer_path.write_bytes(good_pointer)

    removed = build_release.prune(out, 1, second["releaseId"])
    check("prune keeps pointer and newest", removed, [])


def test_tamper(root: pathlib.Path) -> None:
    out = root / "out"
    release_id = validate_release._release_ids(out)[-1]
    release_dir = out / "releases" / release_id
    media_path = release_dir / "media" / lib.bucket_of("al-1") / "al-1.json"
    original = media_path.read_bytes()
    media_path.write_bytes(original.replace(b"Cowboy", b"Cowboy", 1) + b" ")
    expect_refusal("tampered media rejected", lambda: verify_release(out, release_id, full=True))
    media_path.write_bytes(original)
    verify_release(out, release_id, full=True)

    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["counts"]["media"] = 99
    write(manifest_path, manifest)
    expect_refusal("tampered manifest rejected", lambda: verify_release(out, release_id, full=True))

    shard_path = next((release_dir / "catalog").glob("*.json"))
    shard = json.loads(shard_path.read_text("utf-8"))
    shard["rows"][0]["visibility"] = "general"
    write(shard_path, shard)
    expect_refusal("tampered catalog rejected", lambda: verify_release(out, release_id, full=True))


def test_policy_gate(root: pathlib.Path) -> None:
    policy_path = root / "policy.json"
    write(
        policy_path,
        {
            "reviewedAt": "2026-11-17",
            "sources": [{"name": "anilist", "status": "unverified", "permitted": False, "fields": []}],
        },
    )
    code = build_release.main(
        ["--data", str(root / "data"), "--out", str(root / "refused"), "--policy", str(policy_path), "--publish", "--limit", "1"]
    )
    check("unverified publish refused", code, 2)
    check_true("nothing written on refusal", not (root / "refused" / "manifest.json").exists())


def test_schema_files_exist() -> None:
    expected = [
        "media.schema.json",
        "catalog-shard.schema.json",
        "episodes.schema.json",
        "search-shard.schema.json",
        "release-manifest.schema.json",
        "bucket-manifest.schema.json",
        "pointer.schema.json",
        "source-rights.schema.json",
    ]
    schema_dir = pathlib.Path(__file__).resolve().parent.parent / "schema" / "v1"
    for name in expected:
        check_true(f"schema present: {name}", (schema_dir / name).is_file())
        json.loads((schema_dir / name).read_text("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        data = make_fixture(root)
        test_build(root, data)
        test_rollback(root, data)
        test_tamper(root)
        test_policy_gate(root)
    test_schema_files_exist()

    if FAILURES:
        print(f"{len(FAILURES)} failure(s):\n")
        for failure in FAILURES:
            print(failure)
        return 1
    print("all release contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
