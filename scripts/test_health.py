"""Checks for the publication-readiness diagnostic.

    python scripts/test_health.py
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

import publish_health as health
import release_lib as lib

FAILURES: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        FAILURES.append(f"{label}\n    expected {expected!r}\n    got      {actual!r}")


def check_true(label: str, value: bool) -> None:
    if not value:
        FAILURES.append(f"{label}\n    expected truthy, got {value!r}")


def write(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lib.canonical_bytes(payload))


def fixture(root: pathlib.Path, *, stamp: str = "2026-11-17T00:00:00Z", duplicate: bool = False) -> pathlib.Path:
    data = root / "data"
    write(data / "index.json", [{"id": 1, "title": "One"}, {"id": 1 if duplicate else 2, "title": "Two"}])
    write(data / "stats.json", {"total": 2, "last_updated": stamp})
    write(
        data / "sync-status.json",
        {
            "source": "anilist+tmdb",
            "generator": "test",
            "last_updated": stamp,
            "sources": {
                "anilist": {"last_updated": stamp},
                "tmdb": {"last_updated": stamp},
            },
        },
    )
    write(data / "id-map.json", {"1": {"mal": 1}, "2": {"mal": 2}})
    write(data / "genres.json", ["Action"])
    write(data / "years.json", [2020])
    for media_id in (1, 2):
        write(data / "anime" / "0" / str(media_id) / "index.json", {"ids": {"anilist": media_id}})
    return data


def policy_file(
    root: pathlib.Path,
    *,
    name: str = "policy.json",
    status: str = "unverified",
    permitted: bool = False,
) -> pathlib.Path:
    path = root / name
    write(
        path,
        {
            "reviewedAt": "2026-11-17",
            "sources": [{"name": "anilist", "status": status, "permitted": permitted, "fields": []}],
        },
    )
    return path


def run(data: pathlib.Path, policy: pathlib.Path, **kwargs) -> dict:
    return health.run(data, policy, **kwargs)


def main() -> int:
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        data = fixture(root)
        policy = policy_file(root, status="verified", permitted=True)

        report = run(data, policy, now=now)
        check("healthy state", report["state"], "ok")
        check("healthy age", report["ageHours"], 12.0)
        names = {item["name"] for item in report["checks"]}
        check_true("per-source freshness checked", {"source:anilist", "source:tmdb"} <= names)
        check("healthy exit", {"ok": 0, "stale": 1, "failed": 2, "blocked": 3}[report["state"]], 0)

        stale = run(data, policy, now=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc))
        check("stale state", stale["state"], "stale")

        blocked = run(data, policy_file(root, name="unverified.json"), now=now)
        check("blocked state", blocked["state"], "blocked")
        with contextlib.redirect_stdout(io.StringIO()):
            allowed_code = health.main(
                [
                    "--data",
                    str(data),
                    "--policy",
                    str(root / "unverified.json"),
                    "--allow-blocked",
                    "--json",
                ]
            )
        check("allow-blocked exit code", allowed_code, 0)

        required = run(data, policy_file(root, name="strict.json"), now=now, require_permitted=True)
        check("require-permitted fails", required["state"], "failed")

        broken = fixture(root / "broken")
        (broken / "stats.json").unlink()
        missing = run(broken, policy, now=now)
        check("missing file fails", missing["state"], "failed")

        duplicate = fixture(root / "duplicate", duplicate=True)
        duplicated = run(duplicate, policy, now=now)
        check("duplicate ids fail", duplicated["state"], "failed")

        absent = fixture(root / "absent")
        (absent / "anime" / "0" / "2" / "index.json").unlink()
        details = run(absent, policy, now=now)
        check("missing detail fails", details["state"], "failed")

        deep = run(data, policy, now=now, deep=True)
        check("deep audit ok", deep["state"], "ok")

        rendered = health.markdown(report)
        check("markdown mentions state", "Publication health: `ok`" in rendered, True)
        check("markdown tabulates checks", "| freshness |" in rendered, True)

    if FAILURES:
        print(f"{len(FAILURES)} failure(s):\n")
        for failure in FAILURES:
            print(failure)
        return 1
    print("all health checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
