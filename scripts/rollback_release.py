#!/usr/bin/env python3
"""Atomically roll the mutable pointer back to a retained, verified release.

    python scripts/rollback_release.py --root build/v1 --list
    python scripts/rollback_release.py --root build/v1 --release previous
    python scripts/rollback_release.py --root build/v1 --release rel-0123456789abcdef

The target is fully hash-verified before the pointer is replaced. The current
pointer is left untouched on any failure, so a failed rollback is a no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import release_lib as lib
from validate_release import VerificationError, _load, _release_ids, verify_release

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_pointer(root: pathlib.Path, release_id: str) -> dict:
    release_dir = root / "releases" / release_id
    release = _load(release_dir / "manifest.json")
    return {
        "schemaVersion": lib.SCHEMA_VERSION,
        "contract": lib.CONTRACT,
        "releaseId": release_id,
        "releaseManifest": f"releases/{release_id}/manifest.json",
        "contentHash": release["contentHash"],
        "manifestSha256": lib.sha256_hex((release_dir / "manifest.json").read_bytes()),
        "generatedAt": release["generatedAt"],
        "publishedAt": _now(),
        "counts": release["counts"],
    }


def rollback(root: pathlib.Path, release: str, *, dry_run: bool = False) -> dict:
    verification = verify_release(root, release, full=True)
    release_id = verification["releaseId"]
    pointer = make_pointer(root, release_id)
    if not dry_run:
        temporary = root / ".manifest.json.tmp"
        temporary.write_bytes(lib.canonical_bytes(pointer))
        os.replace(temporary, root / "manifest.json")
    return pointer


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT / "build" / "v1")
    parser.add_argument("--release", default="previous", help="previous or rel-<hash>")
    parser.add_argument("--dry-run", action="store_true", help="verify and print, but do not write")
    parser.add_argument("--list", action="store_true", help="list retained releases and exit")
    args = parser.parse_args(argv)

    if args.list:
        pointer = args.root / "manifest.json"
        current = None
        if pointer.is_file():
            current = _load(pointer).get("releaseId")
        for release_id in _release_ids(args.root):
            marker = "*" if release_id == current else " "
            print(f"{marker} {release_id}")
        return 0

    try:
        pointer = rollback(args.root, args.release, dry_run=args.dry_run)
    except VerificationError as exc:
        print(f"rollback refused: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(pointer, indent=2))
    if args.dry_run:
        print("dry run: pointer not written", file=sys.stderr)
    else:
        print(f"pointer now names {pointer['releaseId']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
