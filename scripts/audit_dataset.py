#!/usr/bin/env python3
"""Audit the published Konoha-compatible tree in ``data/``.

Reads only committed files. Emits a machine-readable JSON summary with
``--json`` or a Markdown report used by ``docs/AUDIT-BASELINE.md``.

Exit code is 0 unless ``--strict`` is passed and a P0 invariant fails.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Freshness SLOs used by the health check and this audit. Values are deliberately
# conservative: they describe the current daily publisher, not a promise of live data.
SLO_HOURS = {
    "anilist": 72,
    "tmdb": 72,
}


def _load(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _age_hours(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return round((now - parsed).total_seconds() / 3600, 1)


def audit(data_dir: pathlib.Path = DATA, sample: int = 0) -> dict:
    now = datetime.now(timezone.utc)
    stats = _load(data_dir / "stats.json")
    sync = _load(data_dir / "sync-status.json")
    index = _load(data_dir / "index.json")
    id_map = _load(data_dir / "id-map.json")

    ids = [row.get("id") for row in index]
    duplicate_index_ids = sorted(
        str(value) for value, count in Counter(ids).items() if count > 1
    )
    missing_index_fields = Counter()
    for row in index:
        for field in ("id", "title", "poster", "status", "format"):
            if row.get(field) in (None, ""):
                missing_index_fields[field] += 1

    if sample and sample < len(index):
        step = max(1, len(index) // sample)
        scanned = index[::step][:sample]
    else:
        scanned = index

    adult_present = adult_true = 0
    native_missing = romaji_missing = english_missing = 0
    detail_missing = 0
    episodes_declared = episodes_files = 0
    episode_count_mismatch = 0
    relations_total = relations_with_kind = 0
    mal_forward = mal_inverse = mal_broken = 0
    mapping_ids: set[str] = set()

    mal_dir = data_dir / "mappings" / "mal"
    for path in mal_dir.rglob("*.json"):
        mapping_ids.add(path.stem)
        payload = _load(path)
        target = payload.get("anilist_id")
        if target is None:
            mal_broken += 1
        elif str(target) in id_map:
            mal_forward += 1

    for row in scanned:
        media_id = row.get("id")
        if media_id is None:
            continue
        detail_path = data_dir / "anime" / str(media_id // 1000) / str(media_id) / "index.json"
        if not detail_path.is_file():
            detail_missing += 1
            continue
        detail = _load(detail_path)
        titles = detail.get("titles") or {}
        native_missing += 1 if not titles.get("native") else 0
        romaji_missing += 1 if not titles.get("romaji") else 0
        english_missing += 1 if not titles.get("english") else 0
        anilist = detail.get("anilist") or {}
        if "isAdult" in anilist:
            adult_present += 1
            adult_true += 1 if anilist["isAdult"] else 0
        edges = ((anilist.get("relations") or {}).get("edges")) or []
        for edge in edges:
            relations_total += 1
            node = edge.get("node") or {}
            if node.get("format") or node.get("type"):
                relations_with_kind += 1
        episodes_path = (
            data_dir / "anime" / str(media_id // 1000) / str(media_id) / "episodes.json"
        )
        if episodes_path.is_file():
            episodes = _load(episodes_path)
            episodes_files += 1
            declared = row.get("episodes")
            if declared and len(episodes) != declared:
                episode_count_mismatch += 1
            episodes_declared += declared or 0

    mal_inverse = len(mapping_ids)
    episode_files = 0
    episode_rows = 0
    for path in (data_dir / "anime").rglob("episodes.json"):
        episode_files += 1
        try:
            episode_rows += len(_load(path))
        except json.JSONDecodeError:
            episode_rows += 0
    counted_files = {
        "anime_detail": sum(1 for _ in (data_dir / "anime").rglob("index.json")),
        "anime_episodes": episode_files,
        "mal_mappings": mal_inverse,
        "skip": sum(1 for _ in (data_dir / "skip").rglob("*.json")),
        "schedule": sum(1 for _ in (data_dir / "schedule").rglob("*.json")),
    }
    data_bytes = sum(p.stat().st_size for p in data_dir.rglob("*") if p.is_file())

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "sync_status": sync,
        "age_hours": _age_hours(sync.get("last_updated"), now),
        "slo_hours": SLO_HOURS,
        "sampling": {"records_scanned": len(scanned), "catalogue_rows": len(index)},
        "counts": {
            "catalogue_rows": len(index),
            "stats_total": stats.get("total"),
            "stats_episodes": stats.get("episodes"),
            "episodes_declared_scanned": episodes_declared,
            "episode_rows": episode_rows,
            "episode_files": episode_files,
            "detail_missing_scanned": detail_missing,
            **counted_files,
            "data_bytes": data_bytes,
        },
        "problems": {
            "duplicate_index_ids": duplicate_index_ids,
            "detail_missing": detail_missing,
            "episode_count_mismatch": episode_count_mismatch,
            "missing_index_fields": dict(missing_index_fields),
            "native_title_missing": native_missing,
            "romaji_title_missing": romaji_missing,
            "english_title_missing": english_missing,
            "mal_mapping_broken": mal_broken,
            "mal_forward_matches": mal_forward,
        },
        "coverage": {
            "adult_flag_present": adult_present,
            "adult_true": adult_true,
            "relations_total": relations_total,
            "relations_with_kind": relations_with_kind,
        },
    }


def markdown(report: dict) -> str:
    counts = report["counts"]
    problems = report["problems"]
    coverage = report["coverage"]
    age = report["age_hours"]
    slo = report["slo_hours"]["anilist"]
    status = "STALE" if age is not None and age > slo else "OK"
    rows = [
        ("Catalogue rows", f"{counts['catalogue_rows']:,}"),
        ("`stats.total`", f"{counts['stats_total']:,}"),
        ("Episode records (`stats.episodes`)", f"{counts['stats_episodes']:,}"),
        ("Episode rows on disk", f"{counts['episode_rows']:,}"),
        ("Detail files", f"{counts['anime_detail']:,}"),
        ("Episode files", f"{counts['episode_files']:,}"),
        ("MAL mapping files", f"{counts['mal_mappings']:,}"),
        ("Skip files", f"{counts['skip']:,}"),
        ("Schedule files", f"{counts['schedule']:,}"),
        ("Committed `data/` bytes", f"{counts['data_bytes']:,} ({counts['data_bytes'] / 1024 / 1024:.1f} MiB)"),
    ]
    findings = [
        ("Sync age", f"{age} h (SLO {slo} h)", status),
        ("Duplicate index ids", f"{len(problems['duplicate_index_ids'])}", "FAIL" if problems["duplicate_index_ids"] else "OK"),
        ("`stats.episodes` vs rows on disk", f"{counts['stats_episodes']:,} vs {counts['episode_rows']:,}", "FAIL" if counts["stats_episodes"] != counts["episode_rows"] else "OK"),
        ("Missing detail files", f"{problems['detail_missing']} of {report['sampling']['records_scanned']:,} scanned", "FAIL" if problems["detail_missing"] else "OK"),
        ("Episode count mismatches", f"{problems['episode_count_mismatch']:,}", "WARN" if problems["episode_count_mismatch"] else "OK"),
        ("Broken MAL mappings", f"{problems['mal_mapping_broken']:,}", "FAIL" if problems["mal_mapping_broken"] else "OK"),
        ("Adult flag coverage", f"{coverage['adult_flag_present']:,}/{report['sampling']['records_scanned']:,} scanned detail records", "OK" if coverage["adult_flag_present"] == report["sampling"]["records_scanned"] else "WARN"),
        ("Relations carrying a kind", f"{coverage['relations_with_kind']:,}/{coverage['relations_total']:,}", "WARN"),
        ("Missing native titles", f"{problems['native_title_missing']:,}", "INFO"),
        ("Missing English titles", f"{problems['english_title_missing']:,}", "INFO"),
    ]
    lines = [
        "# Verified dataset baseline",
        "",
        f"Generated by `python scripts/audit_dataset.py --markdown --sample {report['sampling']['records_scanned']}`.",
        "Do not edit by hand; rerun the command and replace this file with its output.",
        "Pass `--sample 0` for a full scan (slow on Windows because every detail file is read).",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Generator: `{report['sync_status'].get('generator')}`",
        f"- Declared sources: `{report['sync_status'].get('source')}`",
        f"- Last data update: `{report['sync_status'].get('last_updated')}`",
        f"- Detail records scanned: {report['sampling']['records_scanned']:,} of {report['sampling']['catalogue_rows']:,}",
        "",
        "## Counts",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines += [
        "",
        "## Findings",
        "",
        "| Check | Value | Status |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {value} | {state} |" for name, value, state in findings]
    lines += [
        "",
        "Status legend: `FAIL` blocks publication; `WARN` is a documented gap;",
        "`INFO` is expected for a catalogue that preserves unknown values.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    parser.add_argument("--markdown", action="store_true", help="emit the baseline Markdown report")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a P0 invariant fails")
    parser.add_argument("--sample", type=int, default=0, help="scan only N evenly spaced detail records")
    parser.add_argument("--data", type=pathlib.Path, default=DATA)
    args = parser.parse_args(argv)

    report = audit(args.data, sample=args.sample)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        if args.markdown:
            print(markdown(report))
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.strict:
        problems = report["problems"]
        counts = report["counts"]
        if (
            problems["duplicate_index_ids"]
            or problems["detail_missing"]
            or problems["mal_mapping_broken"]
            or counts["stats_episodes"] != counts["episode_rows"]
        ):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
