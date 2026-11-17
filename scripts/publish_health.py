#!/usr/bin/env python3
"""Publication readiness check, independent of whether a commit succeeded.

    python scripts/publish_health.py --markdown
    python scripts/publish_health.py --deep --max-age-hours 72

States:
    ok       data is fresh and internally consistent
    stale    data is readable but older than the freshness SLO
    blocked  source rights are not verified; collection must stay off
    failed   a required file is missing or inconsistent

Exit codes: 0 ok, 1 stale, 2 failed, 3 blocked.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
DEFAULT_POLICY = ROOT / "policy" / "source-rights.json"

REQUIRED = ("index.json", "stats.json", "sync-status.json", "id-map.json", "genres.json", "years.json")


def _load(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _age_hours(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round((now - parsed).total_seconds() / 3600, 1)


def _check(checks: list[dict], name: str, state: str, detail: str) -> None:
    checks.append({"name": name, "state": state, "detail": detail})


def run(
    data_dir: pathlib.Path,
    policy_path: pathlib.Path,
    *,
    now: datetime | None = None,
    max_age_hours: float = 72,
    require_permitted: bool = False,
    deep: bool = False,
    release_root: pathlib.Path | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    checks: list[dict] = []
    failed = stale = blocked = False

    payloads = {}
    for name in REQUIRED:
        path = data_dir / name
        if not path.is_file():
            _check(checks, f"file:{name}", "failed", "missing")
            failed = True
            continue
        try:
            payloads[name] = _load(path)
            _check(checks, f"file:{name}", "ok", f"{path.stat().st_size:,} bytes")
        except json.JSONDecodeError as exc:
            _check(checks, f"file:{name}", "failed", f"invalid JSON: {exc}")
            failed = True

    index = payloads.get("index.json")
    stats = payloads.get("stats.json")
    sync = payloads.get("sync-status.json")
    id_map = payloads.get("id-map.json")

    if index is not None and stats is not None:
        if len(index) == stats.get("total"):
            _check(checks, "catalogue:count", "ok", f"{len(index):,} rows match stats.total")
        else:
            _check(
                checks,
                "catalogue:count",
                "failed",
                f"index has {len(index):,} rows, stats.total says {stats.get('total')!r}",
            )
            failed = True
        duplicate = len(index) - len({row.get("id") for row in index})
        _check(checks, "catalogue:unique-ids", "ok" if duplicate == 0 else "failed", f"{duplicate} duplicate rows")
        failed = failed or duplicate > 0

    if index is not None and id_map is not None:
        missing = sum(1 for row in index if str(row.get("id")) not in id_map)
        _check(
            checks,
            "ids:coverage",
            "ok" if missing == 0 else "stale",
            f"{missing:,} catalogue rows without an id-map entry",
        )
        stale = stale or missing > 0

    if index is not None:
        absent = 0
        for row in index:
            media_id = row.get("id")
            if media_id is None:
                continue
            path = data_dir / "anime" / str(media_id // 1000) / str(media_id) / "index.json"
            if not path.is_file():
                absent += 1
        _check(
            checks,
            "catalogue:detail-files",
            "ok" if absent == 0 else "failed",
            f"{absent:,} catalogue rows without a detail file",
        )
        failed = failed or absent > 0

    age = _age_hours(sync.get("last_updated") if sync else None, now)
    if age is None:
        _check(checks, "freshness", "failed", "sync-status has no last_updated")
        failed = True
    elif age > max_age_hours:
        _check(checks, "freshness", "stale", f"{age} h old, SLO {max_age_hours} h")
        stale = True
    else:
        _check(checks, "freshness", "ok", f"{age} h old, SLO {max_age_hours} h")

    sources = (sync or {}).get("sources") or {}
    for name in sorted(sources):
        source_age = _age_hours((sources[name] or {}).get("last_updated"), now)
        if source_age is None:
            _check(checks, f"source:{name}", "failed", "no last_updated")
            failed = True
        elif source_age > max_age_hours:
            _check(checks, f"source:{name}", "stale", f"{source_age} h old, SLO {max_age_hours} h")
            stale = True
        else:
            _check(checks, f"source:{name}", "ok", f"{source_age} h old, SLO {max_age_hours} h")

    try:
        policy = _load(policy_path)
    except (OSError, json.JSONDecodeError) as exc:
        _check(checks, "policy", "failed", f"cannot read {policy_path}: {exc}")
        policy = {"sources": []}
        failed = True

    unverified = [
        item["name"]
        for item in policy.get("sources", [])
        if item.get("status") != "verified" or not item.get("permitted")
    ]
    if unverified:
        state = "failed" if require_permitted else "blocked"
        _check(checks, "policy:rights", state, "not verified/permitted: " + ", ".join(unverified))
        if require_permitted:
            failed = True
        else:
            blocked = True
    else:
        _check(checks, "policy:rights", "ok", f"{len(policy.get('sources', []))} sources verified")

    if release_root and (release_root / "manifest.json").is_file():
        import validate_release

        try:
            result = validate_release.verify_release(release_root, "current", full=False)
            _check(checks, "release:pointer", "ok", f"{result['releaseId']} ({result['media']:,} media)")
        except validate_release.VerificationError as exc:
            _check(checks, "release:pointer", "failed", str(exc))
            failed = True

    if deep:
        import audit_dataset

        report = audit_dataset.audit(data_dir)
        problems = report["problems"]
        if problems["duplicate_index_ids"] or problems["detail_missing"] or problems["mal_mapping_broken"]:
            _check(checks, "audit:deep", "failed", json.dumps(problems, sort_keys=True))
            failed = True
        else:
            _check(
                checks,
                "audit:deep",
                "ok",
                f"{report['counts']['catalogue_rows']:,} rows, "
                f"{report['counts']['episode_files']:,} episode files, "
                f"{report['counts']['data_bytes'] / 1024 / 1024:.1f} MiB",
            )

    state = "failed" if failed else "stale" if stale else "blocked" if blocked else "ok"
    return {
        "state": state,
        "checkedAt": now.isoformat().replace("+00:00", "Z"),
        "lastUpdated": sync.get("last_updated") if sync else None,
        "ageHours": age,
        "maxAgeHours": max_age_hours,
        "checks": checks,
    }


def markdown(report: dict) -> str:
    lines = [
        f"### Publication health: `{report['state']}`",
        "",
        f"- Checked: `{report['checkedAt']}`",
        f"- Last data update: `{report['lastUpdated']}` ({report['ageHours']} h)",
        "",
        "| Check | State | Detail |",
        "| --- | --- | --- |",
    ]
    for item in report["checks"]:
        detail = str(item["detail"]).replace("|", "\\|")
        lines.append(f"| {item['name']} | {item['state']} | {detail} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA)
    parser.add_argument("--policy", type=pathlib.Path, default=DEFAULT_POLICY)
    parser.add_argument("--max-age-hours", type=float, default=72)
    parser.add_argument("--require-permitted", action="store_true", help="treat unverified rights as failure")
    parser.add_argument("--deep", action="store_true", help="read every detail file (slow)")
    parser.add_argument("--release-root", type=pathlib.Path)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-blocked", action="store_true", help="exit 0 for the expected rights block")
    args = parser.parse_args(argv)

    report = run(
        args.data,
        args.policy,
        max_age_hours=args.max_age_hours,
        require_permitted=args.require_permitted,
        deep=args.deep,
        release_root=args.release_root,
    )
    if args.markdown:
        print(markdown(report))
    if args.json or not args.markdown:
        print(json.dumps(report, indent=2))

    code = {"ok": 0, "stale": 1, "failed": 2, "blocked": 3}[report["state"]]
    if code == 3 and args.allow_blocked:
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
