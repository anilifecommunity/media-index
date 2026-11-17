"""Compatibility checks for the legacy `/data/` paths old clients still read.

    python scripts/test_compat.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

FAILURES: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        FAILURES.append(f"{label}\n    expected {expected!r}\n    got      {actual!r}")


def check_true(label: str, value: bool) -> None:
    if not value:
        FAILURES.append(f"{label}\n    expected truthy, got {value!r}")


def load(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    required_root_files = [
        "index.json",
        "id-map.json",
        "airing.json",
        "backdrops.json",
        "genres.json",
        "years.json",
        "stats.json",
        "sync-status.json",
        "dub-index.json",
        "dub-episodes.json",
        "filler-index.json",
    ]
    for name in required_root_files:
        check_true(f"compat root file: {name}", (DATA / name).is_file())

    index = load(DATA / "index.json")
    stats = load(DATA / "stats.json")
    id_map = load(DATA / "id-map.json")
    check("index rows equal stats.total", len(index), stats.get("total"))
    check_true("catalogue is not empty", len(index) > 0)

    required_row = {
        "id",
        "title",
        "slug",
        "poster",
        "year",
        "status",
        "format",
        "episodes",
        "score",
        "popularity",
        "genres",
    }
    for row in index[:50]:
        missing = required_row - set(row)
        check_true(f"row {row.get('id')} keeps legacy keys", not missing)

    sample = [row for row in index[:400] if row.get("id")]
    sampled_details = episodes_checked = mappings_checked = 0
    for row in sample:
        media_id = int(row["id"])
        detail_path = DATA / "anime" / str(media_id // 1000) / str(media_id) / "index.json"
        if not detail_path.is_file():
            FAILURES.append(f"missing legacy detail path for {media_id}")
            continue
        detail = load(detail_path)
        check_true(f"detail {media_id} ids", detail.get("ids", {}).get("anilist") == media_id)
        check_true(f"detail {media_id} titles", "titles" in detail)
        check_true(f"detail {media_id} images", "images" in detail)
        sampled_details += 1

        episodes_path = DATA / "anime" / str(media_id // 1000) / str(media_id) / "episodes.json"
        if episodes_path.is_file() and episodes_checked < 25:
            episodes = load(episodes_path)
            numbers = [int(item["number"]) for item in episodes]
            check(f"episode numbering {media_id}", numbers, list(range(1, len(episodes) + 1)))
            for item in episodes:
                check_true(f"episode {media_id}/{item['number']} keys", {"title", "overview", "air_date", "still", "runtime"} <= set(item))
            episodes_checked += 1

        mal_id = detail.get("ids", {}).get("mal")
        if mal_id and mappings_checked < 25:
            mapping_path = DATA / "mappings" / "mal" / str(mal_id // 1000) / f"{mal_id}.json"
            check_true(f"legacy MAL mapping path {mal_id}", mapping_path.is_file())
            if mapping_path.is_file():
                check(f"MAL mapping {mal_id}", load(mapping_path).get("anilist_id"), media_id)
            mappings_checked += 1

    check_true("sampled detail records", sampled_details >= min(50, len(sample)))
    check_true("sampled episode lists", episodes_checked > 0)
    check_true("sampled MAL mappings", mappings_checked > 0)

    catalogue_ids = {str(row.get("id")) for row in index}
    for anilist_id, entry in id_map.items():
        if anilist_id not in catalogue_ids:
            # Bangumi and Fribb may add alias-only rows for ids outside the published catalogue.
            # The app ignores them; the full legacy shape is only promised for catalogue ids.
            continue
        for key in ("tmdb", "mal", "kitsu", "anidb", "simkl", "tvdb", "tvdb_season", "confidence", "updated_at"):
            if key not in entry:
                FAILURES.append(f"id-map entry {anilist_id} missing {key}")
                break

    schedule = sorted((DATA / "schedule").glob("*.json"))
    check_true("schedule months present", len(schedule) > 0)
    for month_path in schedule:
        payload = load(month_path)
        check_true(f"schedule {month_path.name} is a list", isinstance(payload, list))

    recs = DATA / "recs" / "neighbours-v1.tsv.gz"
    check_true("recommendation graph present", recs.is_file())
    check_true("recommendation graph not empty", recs.is_file() and recs.stat().st_size > 0)

    if FAILURES:
        print(f"{len(FAILURES)} failure(s):\n")
        for failure in FAILURES:
            print(failure)
        return 1
    print(
        f"legacy compatibility OK: {len(index):,} rows, "
        f"{sampled_details} details, {episodes_checked} episode lists, {mappings_checked} mappings"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
