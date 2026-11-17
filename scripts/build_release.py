#!/usr/bin/env python3
"""Build the immutable v1 release from the committed ``data/`` tree.

The legacy Konoha tree is the input and is never modified. Output is written
to ``release-repo/`` (or ``--out``); it can be verified with
``scripts/validate_release.py`` and published by pointing ``manifest.json`` at
it. ``--publish`` performs that pointer swap atomically.

    python scripts/build_release.py --out build/v1 --publish

Publishing requires every emitted source to be marked ``permitted`` in
``policy/source-rights.json`` unless ``--allow-unverified-sources`` is passed.
The explicit override exists so a staging publication can be demonstrated
without pretending that legal review happened.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import release_lib as lib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
DEFAULT_POLICY = ROOT / "policy" / "source-rights.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write(path: pathlib.Path, payload) -> tuple[int, str]:
    data = lib.canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data), lib.sha256_hex(data)


def source_status(policy: dict, updated_at: str) -> list[dict]:
    return [
        {
            "name": item["name"],
            "status": "verified" if item.get("status") == "verified" else item.get("status", "unverified"),
            "permitted": bool(item.get("permitted")),
            "permissionReference": item.get("permissionReference"),
            "lastUpdated": updated_at,
        }
        for item in policy.get("sources", [])
    ]


def unpermitted_sources(policy: dict) -> list[str]:
    return [
        item["name"]
        for item in policy.get("sources", [])
        if item.get("status") != "verified" or not item.get("permitted")
    ]


def build(
    data_dir: pathlib.Path,
    out_dir: pathlib.Path,
    policy: dict,
    *,
    limit: int = 0,
    generated_at: str | None = None,
    include_raw: bool = False,
) -> dict:
    sync = _load_json(data_dir / "sync-status.json")
    index = _load_json(data_dir / "index.json")
    id_map = _load_json(data_dir / "id-map.json")
    updated_at = sync.get("last_updated") or _now()
    generated_at = generated_at or _now()

    rows = sorted(index, key=lambda row: int(row["id"]))
    if limit:
        rows = rows[:limit]
    known_anime = {int(row["id"]) for row in rows}

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=".release-", dir=out_dir))
    try:
        return _build_into(
            staging,
            out_dir,
            data_dir,
            policy,
            rows=rows,
            known_anime=known_anime,
            id_map=id_map,
            updated_at=updated_at,
            generated_at=generated_at,
            include_raw=include_raw,
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _build_into(
    staging: pathlib.Path,
    out_dir: pathlib.Path,
    data_dir: pathlib.Path,
    policy: dict,
    *,
    rows: list[dict],
    known_anime: set[int],
    id_map: dict,
    updated_at: str,
    generated_at: str,
    include_raw: bool,
) -> dict:
    content_files: list[dict] = []
    aux_files: list[dict] = []
    media_manifest: dict[str, list[dict]] = {}
    episode_manifest: dict[str, list[dict]] = {}
    catalog_rows: dict[int, list[dict]] = {shard: [] for shard in range(lib.CATALOG_SHARDS)}
    search_rows: dict[str, dict[str, dict]] = {}
    ids_anilist: dict[int, dict[str, str]] = {}
    ids_mal: dict[int, dict[str, str]] = {}
    ledger: list[dict] = []

    counts = {
        "media": 0,
        "episodeLists": 0,
        "episodes": 0,
        "relations": 0,
        "adult": 0,
    }

    def record(path: pathlib.Path, payload) -> None:
        size, digest = _write(path, payload)
        relative = path.relative_to(staging).as_posix()
        content_files.append({"path": relative, "bytes": size, "sha256": digest})

    def record_aux_bytes(dest: str, data: bytes) -> None:
        path = staging / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = {"path": dest, "bytes": len(data), "sha256": lib.sha256_hex(data)}
        aux_files.append(entry)
        content_files.append(entry)

    def copy_aux(source: pathlib.Path, dest: str) -> None:
        if source.is_file():
            record_aux_bytes(dest, source.read_bytes())

    def record_aux_json(dest: str, payload) -> None:
        record_aux_bytes(dest, lib.canonical_bytes(payload))

    for position, row in enumerate(rows, start=1):
        anilist_id = int(row["id"])
        key = lib.media_key(anilist_id)
        shard = anilist_id // 1000
        detail_path = data_dir / "anime" / str(shard) / str(anilist_id) / "index.json"
        if not detail_path.is_file():
            raise SystemExit(f"missing detail file: {detail_path}")
        detail = _load_json(detail_path)

        episodes_path = data_dir / "anime" / str(shard) / str(anilist_id) / "episodes.json"
        episode_rows: list[dict] = []
        if episodes_path.is_file():
            episode_rows = _load_json(episodes_path) or []

        ids = id_map.get(str(anilist_id)) or {}
        media = lib.build_media_record(
            detail,
            row,
            ids=ids,
            episodes_available=bool(episode_rows),
            known_anime=known_anime,
            include_raw=include_raw,
        )

        bucket = lib.bucket_of(key)
        media_path = staging / "media" / bucket / f"{key}.json"
        size, digest = _write(media_path, media)
        media_manifest.setdefault(bucket, []).append(
            {"key": key, "path": media_path.relative_to(staging).as_posix(), "bytes": size, "sha256": digest}
        )
        content_files.append(
            {"path": media_path.relative_to(staging).as_posix(), "bytes": size, "sha256": digest}
        )

        if episode_rows:
            episode_record = lib.build_episode_record(
                key,
                episode_rows,
                match_confidence=ids.get("confidence"),
            )
            episode_path = staging / "episodes" / bucket / f"{key}.json"
            size, digest = _write(episode_path, episode_record)
            episode_manifest.setdefault(bucket, []).append(
                {
                    "key": key,
                    "path": episode_path.relative_to(staging).as_posix(),
                    "bytes": size,
                    "sha256": digest,
                }
            )
            content_files.append(
                {"path": episode_path.relative_to(staging).as_posix(), "bytes": size, "sha256": digest}
            )
            counts["episodeLists"] += 1
            counts["episodes"] += len(episode_record["episodes"])

        catalog = lib.build_catalog_row(media)
        catalog_rows[lib.catalog_shard_of(key)].append(catalog)

        for name in lib.search_names(media):
            bucket_name = lib.search_bucket_of_normalized(name)
            bucket_rows = search_rows.setdefault(bucket_name, {}).setdefault(
                key,
                {"mediaKey": key, "names": [], "visibility": media["visibility"]},
            )
            if name not in bucket_rows["names"]:
                bucket_rows["names"].append(name)

        ids_anilist.setdefault(shard, {})[str(anilist_id)] = key
        mal_id = media["ids"].get("mal")
        if mal_id:
            ids_mal.setdefault(int(mal_id) // 1000, {})[str(mal_id)] = key

        ledger.append(
            {
                "mediaKey": key,
                "kind": "ANIME",
                "ids": {"anilist": anilist_id, "mal": mal_id},
            }
        )

        counts["media"] += 1
        counts["relations"] += len(media["relations"])
        counts["adult"] += 1 if media["visibility"] == "adult" else 0

        if position % 2000 == 0:
            print(f"  {position:,}/{len(rows):,} records", file=sys.stderr, flush=True)

    for shard, shard_rows in sorted(catalog_rows.items()):
        if not shard_rows:
            continue
        shard_rows.sort(key=lambda item: item["mediaKey"])
        record(
            staging / "catalog" / f"{shard:02d}.json",
            {"schemaVersion": lib.SCHEMA_VERSION, "shard": shard, "rows": shard_rows},
        )

    for bucket_name in sorted(search_rows):
        rows_out = [search_rows[bucket_name][key] for key in sorted(search_rows[bucket_name])]
        for row_out in rows_out:
            row_out["names"].sort()
        record(
            staging / "search" / "universal" / f"{bucket_name}.json",
            {"schemaVersion": lib.SCHEMA_VERSION, "bucket": bucket_name, "rows": rows_out},
        )

    for shard, mapping in sorted(ids_anilist.items()):
        record(
            staging / "ids" / "anilist" / "anime" / f"{shard:03d}.json",
            {
                "schemaVersion": lib.SCHEMA_VERSION,
                "provider": "anilist",
                "kind": "ANIME",
                "shard": shard,
                "ids": mapping,
            },
        )
    for shard, mapping in sorted(ids_mal.items()):
        record(
            staging / "ids" / "mal" / "anime" / f"{shard:03d}.json",
            {
                "schemaVersion": lib.SCHEMA_VERSION,
                "provider": "mal",
                "kind": "ANIME",
                "shard": shard,
                "ids": mapping,
            },
        )

    record(
        staging / "identity" / "ledger.json",
        {
            "schemaVersion": lib.SCHEMA_VERSION,
            "contract": lib.CONTRACT,
            "entries": ledger,
        },
    )

    all_catalog = [row for shard_rows in catalog_rows.values() for row in shard_rows]

    def compact(row: dict) -> dict:
        return {
            "mediaKey": row["mediaKey"],
            "anilistId": row["ids"]["anilist"],
            "titles": row["titles"],
            "poster": row["poster"],
            "year": row["seasonYear"],
            "format": row["format"],
            "status": row["status"],
            "episodes": row["episodes"],
            "episodesAvailable": row["episodesAvailable"],
            "score": row["score"],
            "popularity": row["popularity"],
            "genres": row["genres"],
            "isAdult": row["isAdult"],
            "visibility": row["visibility"],
        }

    browse = [compact(row) for row in all_catalog]

    def popularity(row: dict) -> int:
        return row["popularity"] or 0

    def score_of(row: dict) -> int:
        return row["score"] if row["score"] is not None else -1

    popular = sorted(browse, key=lambda row: (-popularity(row), row["mediaKey"]))
    top_rated = sorted(browse, key=lambda row: (-score_of(row), -popularity(row), row["mediaKey"]))
    newest = sorted(browse, key=lambda row: (-(row["year"] or 0), -popularity(row), row["mediaKey"]))
    upcoming = [row for row in popular if row["status"] == "NOT_YET_RELEASED"]
    movies = [row for row in popular if row["format"] == "MOVIE"]
    releasing = [row for row in popular if row["status"] == "RELEASING"]
    season_year = max((row["year"] or 0 for row in releasing), default=0)
    season = [row for row in popular if row["status"] == "RELEASING" and (row["year"] or 0) == season_year]

    home_rows = {
        "spotlight": popular[:5],
        "trending": releasing[:30],
        "popular": popular[:30],
        "topRated": top_rated[:30],
        "season": season[:30],
        "newest": newest[:30],
        "upcoming": upcoming[:30],
        "movies": movies[:30],
    }
    record(
        staging / "catalog" / "home.json",
        {
            "schemaVersion": lib.SCHEMA_VERSION,
            "generatedAt": updated_at,
            "rows": home_rows,
        },
    )
    home_entry = content_files[-1]
    record(
        staging / "catalog" / "browse.json",
        {
            "schemaVersion": lib.SCHEMA_VERSION,
            "generatedAt": updated_at,
            "rows": popular,
        },
    )
    browse_entry = content_files[-1]

    # Auxiliary surfaces the clients already read from the legacy tree. They stay verbatim because
    # their shapes are already consumed in production; the release manifest pins their hashes.
    copy_aux(data_dir / "dub-index.json", "dub/index.json")
    copy_aux(data_dir / "dub-episodes.json", "dub/episodes.json")
    copy_aux(data_dir / "filler-index.json", "filler/index.json")
    copy_aux(data_dir / "backdrops.json", "backdrops.json")
    copy_aux(data_dir / "airing.json", "airing.json")
    copy_aux(data_dir / "recs" / "neighbours-v1.tsv.gz", "recommendations/neighbours-v1.tsv.gz")

    for schedule in sorted((data_dir / "schedule").glob("*.json")):
        copy_aux(schedule, f"schedule/{schedule.name}")
    selected_ids = {int(row["id"]) for row in rows}
    for skip in sorted((data_dir / "skip").rglob("*.json")):
        if skip.stem.isdigit() and int(skip.stem) not in selected_ids:
            continue
        copy_aux(skip, f"skip/{skip.relative_to(data_dir / 'skip').as_posix()}")
    for lili in sorted((data_dir / "anime").rglob("lili.json")):
        relative = lili.relative_to(data_dir / "anime")
        if len(relative.parts) == 3:
            shard, media_id, _ = relative.parts
            if media_id.isdigit() and int(media_id) not in selected_ids:
                continue
            copy_aux(lili, f"sources/lili/{shard}/{media_id}.json")

    genres_path = data_dir / "genres.json"
    years_path = data_dir / "years.json"
    record_aux_json(
        "facets.json",
        {
            "genres": _load_json(genres_path) if genres_path.is_file() else [],
            "years": _load_json(years_path) if years_path.is_file() else [],
            "formats": sorted({row["format"] for row in browse if row["format"]}),
            "statuses": sorted({row["status"] for row in browse if row["status"]}),
        },
    )

    aux_files.sort(key=lambda item: item["path"])
    content_files.sort(key=lambda item: item["path"])
    content_digest = lib.sha256_hex(
        "\n".join(f"{item['path']}\0{item['sha256']}" for item in content_files).encode("utf-8")
    )
    content_hash = f"sha256:{content_digest}"
    release_id = f"rel-{content_digest[:16]}"
    target = out_dir / "releases" / release_id

    manifest_entries: dict[str, list[dict]] = {"media": [], "episodes": []}
    for label, inventory in (("media", media_manifest), ("episodes", episode_manifest)):
        for bucket_name, files in sorted(inventory.items()):
            files.sort(key=lambda item: item["key"])
            path = staging / "manifests" / label / f"{bucket_name}.json"
            size, digest = _write(
                path,
                {"schemaVersion": lib.SCHEMA_VERSION, "bucket": bucket_name, "files": files},
            )
            manifest_entries[label].append(
                {
                    "path": path.relative_to(staging).as_posix(),
                    "bytes": size,
                    "sha256": digest,
                }
            )

    counts["auxFiles"] = len(aux_files)
    release_manifest = {
        "schemaVersion": lib.SCHEMA_VERSION,
        "contract": lib.CONTRACT,
        "releaseId": release_id,
        "generatedAt": generated_at,
        "contentHash": content_hash,
        "counts": counts,
        "sources": source_status(policy, updated_at),
        "catalog": {
            "files": [
                item
                for item in content_files
                if item["path"].startswith("catalog/")
                and item["path"] not in ("catalog/home.json", "catalog/browse.json")
            ]
        },
        "home": home_entry,
        "browse": browse_entry,
        "search": {
            "files": [item for item in content_files if item["path"].startswith("search/")]
        },
        "ids": {
            "files": [item for item in content_files if item["path"].startswith("ids/")]
        },
        "aux": {"files": aux_files},
        "identity": {
            "ledger": next(
                dict(item) for item in content_files if item["path"] == "identity/ledger.json"
            )
        },
        "manifests": {
            "media": {"files": manifest_entries["media"]},
            "episodes": {"files": manifest_entries["episodes"]},
        },
    }
    _, manifest_digest = _write(staging / "manifest.json", release_manifest)

    if target.exists() and (target / "manifest.json").is_file():
        shutil.rmtree(staging)
        manifest_digest = lib.sha256_hex((target / "manifest.json").read_bytes())
        generated_at = _load_json(target / "manifest.json").get("generatedAt", generated_at)
        reused = True
    else:
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        reused = False

    summary = {
        "releaseId": release_id,
        "contentHash": content_hash,
        "manifestSha256": manifest_digest,
        "generatedAt": generated_at,
        "counts": counts,
        "reused": reused,
        "totalBytes": sum(item["bytes"] for item in content_files),
        "target": str(target),
    }
    return summary


def write_pointer(out_dir: pathlib.Path, summary: dict, published_at: str | None = None) -> dict:
    pointer = {
        "schemaVersion": lib.SCHEMA_VERSION,
        "contract": lib.CONTRACT,
        "releaseId": summary["releaseId"],
        "releaseManifest": f"releases/{summary['releaseId']}/manifest.json",
        "contentHash": summary["contentHash"],
        "manifestSha256": summary["manifestSha256"],
        "generatedAt": summary["generatedAt"],
        "publishedAt": published_at or _now(),
        "counts": summary["counts"],
    }
    path = out_dir / "manifest.json"
    if path.is_file():
        try:
            existing = _load_json(path)
        except json.JSONDecodeError:
            existing = None
        if (
            existing
            and existing.get("releaseId") == summary["releaseId"]
            and existing.get("contentHash") == summary["contentHash"]
            and existing.get("manifestSha256") == summary["manifestSha256"]
            and existing.get("counts") == summary["counts"]
        ):
            return existing
    temporary = out_dir / ".manifest.json.tmp"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(lib.canonical_bytes(pointer))
    os.replace(temporary, path)
    return pointer


def prune(out_dir: pathlib.Path, keep: int, protected: str) -> list[str]:
    """Retain ``keep`` newest releases plus the pointer target and ``protected``."""
    if keep < 1:
        return []
    keep_ids = {protected}
    pointer = out_dir / "manifest.json"
    if pointer.is_file():
        try:
            keep_ids.add(_load_json(pointer).get("releaseId"))
        except json.JSONDecodeError:
            pass
    releases = []
    for path in (out_dir / "releases").glob("rel-*"):
        manifest = path / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            generated = _load_json(manifest).get("generatedAt", "")
        except json.JSONDecodeError:
            generated = ""
        releases.append((generated, path))
    releases.sort(reverse=True)
    removed = []
    for _, path in releases[keep:]:
        if path.name in keep_ids:
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "v1")
    parser.add_argument("--policy", type=pathlib.Path, default=DEFAULT_POLICY)
    parser.add_argument("--publish", action="store_true", help="swap the mutable manifest pointer")
    parser.add_argument(
        "--allow-unverified-sources",
        action="store_true",
        help="publish even though rights are unverified (staging/demo only)",
    )
    parser.add_argument("--prune-keep", type=int, default=2, help="retained releases (0 disables)")
    parser.add_argument("--limit", type=int, default=0, help="build only the first N catalogue rows")
    parser.add_argument("--generated-at", help="fixed timestamp for reproducible fixtures")
    parser.add_argument("--published-at", help="fixed pointer timestamp for reproducible fixtures")
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="include the full raw AniList-shaped record in each media file (large)",
    )
    args = parser.parse_args(argv)

    policy = _load_json(args.policy)
    unpermitted = unpermitted_sources(policy)
    if args.publish and unpermitted and not args.allow_unverified_sources:
        print(
            "refusing to publish: sources not verified/permitted: " + ", ".join(unpermitted),
            file=sys.stderr,
        )
        print("see docs/SOURCE-POLICY.md; pass --allow-unverified-sources for staging only", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    summary = build(
        args.data,
        args.out,
        policy,
        limit=args.limit,
        generated_at=args.generated_at,
        include_raw=args.include_raw,
    )
    if args.publish:
        pointer = write_pointer(args.out, summary, published_at=args.published_at)
        summary["pointer"] = pointer
        summary["pruned"] = prune(args.out, args.prune_keep, summary["releaseId"])

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
