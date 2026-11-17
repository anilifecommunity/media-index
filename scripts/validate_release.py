#!/usr/bin/env python3
"""Verify a v1 release tree, including every content hash and the pointer.

    python scripts/validate_release.py --root build/v1
    python scripts/validate_release.py --root build/v1 --release rel-0123456789abcdef
    python scripts/validate_release.py --root build/v1 --schemas

``--schemas`` additionally validates manifests and a deterministic sample of
records against ``schema/v1/*.schema.json``; it needs ``jsonschema`` installed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import release_lib as lib

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED_SCHEMAS = {
    "media": "media.schema.json",
    "catalog": "catalog-shard.schema.json",
    "episodes": "episodes.schema.json",
    "search": "search-shard.schema.json",
    "bucket": "bucket-manifest.schema.json",
    "release": "release-manifest.schema.json",
    "pointer": "pointer.schema.json",
}


class VerificationError(Exception):
    pass


def _load(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _release_ids(root: pathlib.Path) -> list[str]:
    directory = root / "releases"
    if not directory.is_dir():
        return []
    ordered = []
    for path in directory.iterdir():
        if not (path.is_dir() and path.name.startswith("rel-")):
            continue
        manifest = path / "manifest.json"
        generated = ""
        if manifest.is_file():
            try:
                generated = _load(manifest).get("generatedAt", "")
            except json.JSONDecodeError:
                generated = ""
        ordered.append((generated, path.name))
    ordered.sort()
    return [name for _, name in ordered]


def resolve_release(root: pathlib.Path, release: str | None) -> str:
    available = _release_ids(root)
    if not available:
        raise VerificationError(f"no releases under {root / 'releases'}")
    if release in (None, "current"):
        pointer = root / "manifest.json"
        if pointer.is_file():
            release_id = _load(pointer).get("releaseId")
            if release_id in available:
                return release_id
        return available[-1]
    if release == "previous":
        if len(available) < 2:
            raise VerificationError("no previous release retained")
        return available[-2]
    if release not in available:
        raise VerificationError(f"unknown release {release!r}; have {', '.join(available)}")
    return release


def _validate_schemas(root: pathlib.Path, release_dir: pathlib.Path, release: dict) -> int:
    try:
        import jsonschema  # type: ignore
    except ImportError as exc:  # pragma: no cover - CI installs it
        raise VerificationError("--schemas requires jsonschema (pip install jsonschema)") from exc

    schema_dir = ROOT / "schema" / "v1"
    loaded = {}
    for label, filename in REQUIRED_SCHEMAS.items():
        schema = _load(schema_dir / filename)
        validator = jsonschema.Draft202012Validator(schema)
        validator.check_schema(schema)
        loaded[label] = validator

    validated = 0

    def check(label: str, payload) -> None:
        nonlocal validated
        errors = sorted(loaded[label].iter_errors(payload), key=lambda err: list(err.path))
        if errors:
            first = errors[0]
            raise VerificationError(f"{label} schema: {first.message} at {list(first.path)}")
        validated += 1

    check("release", release)
    for item in release["manifests"]["media"]:
        check("bucket", _load(release_dir / item["path"]))
    for item in release["manifests"]["episodes"]:
        check("bucket", _load(release_dir / item["path"]))
    for item in release["catalog"]["files"]:
        check("catalog", _load(release_dir / item["path"]))
    for item in release["search"]["files"]:
        check("search", _load(release_dir / item["path"]))
    check("media", _load(release_dir / "media" / _first_media(release_dir, release)[0]))
    check("episodes", _load(release_dir / _first_episode(release_dir, release)))
    pointer = root / "manifest.json"
    if pointer.is_file():
        check("pointer", _load(pointer))
    return validated


def _first_media(release_dir: pathlib.Path, release: dict) -> tuple[str, dict]:
    for item in release["manifests"]["media"]:
        bucket = _load(release_dir / item["path"])
        if bucket["files"]:
            return bucket["files"][0]["path"], bucket
    raise VerificationError("release has no media records")


def _first_episode(release_dir: pathlib.Path, release: dict) -> str:
    for item in release["manifests"]["episodes"]:
        bucket = _load(release_dir / item["path"])
        if bucket["files"]:
            return bucket["files"][0]["path"]
    raise VerificationError("release has no episode records")


def verify_release(
    root: pathlib.Path,
    release: str | None = None,
    *,
    full: bool = True,
    schemas: bool = False,
) -> dict:
    release_id = resolve_release(root, release)
    release_dir = root / "releases" / release_id
    release = _load(release_dir / "manifest.json")

    _check(release.get("releaseId") == release_id, "release manifest id does not match directory")
    _check(release.get("contract") == lib.CONTRACT, "wrong contract name")
    _check(release.get("schemaVersion") == lib.SCHEMA_VERSION, "wrong schema version")

    pointer = root / "manifest.json"
    if pointer.is_file():
        pointer_payload = _load(pointer)
        if pointer_payload.get("releaseId") == release_id:
            _check(
                pointer_payload.get("contentHash") == release.get("contentHash"),
                "pointer contentHash disagrees with release manifest",
            )
            _check(
                pointer_payload.get("manifestSha256")
                == lib.sha256_hex((release_dir / "manifest.json").read_bytes()),
                "pointer manifestSha256 disagrees with release manifest bytes",
            )

    content: list[dict] = []
    content.extend(release["catalog"]["files"])
    content.extend(release["search"]["files"])
    content.extend(release["ids"]["files"])
    content.append(release["identity"]["ledger"])

    media_entries: list[dict] = []
    for item in release["manifests"]["media"]:
        path = release_dir / item["path"]
        payload = path.read_bytes()
        _check(len(payload) == item["bytes"], f"bucket manifest size mismatch: {item['path']}")
        _check(lib.sha256_hex(payload) == item["sha256"], f"bucket manifest hash mismatch: {item['path']}")
        bucket = json.loads(payload)
        _check(bucket.get("bucket") == path.stem, f"bucket name mismatch: {item['path']}")
        media_entries.extend(bucket["files"])

    episode_entries: list[dict] = []
    for item in release["manifests"]["episodes"]:
        path = release_dir / item["path"]
        payload = path.read_bytes()
        _check(len(payload) == item["bytes"], f"bucket manifest size mismatch: {item['path']}")
        _check(lib.sha256_hex(payload) == item["sha256"], f"bucket manifest hash mismatch: {item['path']}")
        bucket = json.loads(payload)
        _check(bucket.get("bucket") == path.stem, f"bucket name mismatch: {item['path']}")
        episode_entries.extend(bucket["files"])

    keys = [entry["key"] for entry in media_entries]
    _check(len(keys) == len(set(keys)), "duplicate mediaKey across bucket manifests")
    _check(len(keys) == release["counts"]["media"], "media manifest count disagrees with counts.media")
    _check(
        len(episode_entries) == release["counts"]["episodeLists"],
        "episode manifest count disagrees with counts.episodeLists",
    )
    content.extend(media_entries)
    content.extend(episode_entries)
    content.sort(key=lambda item: item["path"])

    _check(
        len({item["path"] for item in content}) == len(content),
        "duplicate content path in release inventory",
    )

    checked = 0
    if full:
        for item in content:
            path = release_dir / item["path"]
            _check(path.is_file(), f"missing content file: {item['path']}")
            payload = path.read_bytes()
            _check(len(payload) == item["bytes"], f"size mismatch: {item['path']}")
            _check(lib.sha256_hex(payload) == item["sha256"], f"hash mismatch: {item['path']}")
            checked += 1
    else:
        for item in content[:50] + content[-50:]:
            path = release_dir / item["path"]
            _check(path.is_file(), f"missing content file: {item['path']}")
            payload = path.read_bytes()
            _check(lib.sha256_hex(payload) == item["sha256"], f"hash mismatch: {item['path']}")
            checked += 1

    digest = lib.sha256_hex(
        "\n".join(f"{item['path']}\0{item['sha256']}" for item in content).encode("utf-8")
    )
    _check(f"sha256:{digest}" == release["contentHash"], "contentHash does not match the file inventory")
    _check(
        release_id == f"rel-{digest[:16]}",
        "releaseId is not derived from the content hash (records may have been tampered with)",
    )

    episodes_total = 0
    for entry in episode_entries[:200] if not full else episode_entries:
        record = _load(release_dir / entry["path"])
        episodes_total += len(record.get("episodes") or [])
        _check(record.get("mediaKey") == entry["key"], f"episode record key mismatch: {entry['path']}")
    if full:
        _check(
            episodes_total == release["counts"].get("episodes"),
            "episode total disagrees with counts.episodes",
        )

    validation = {
        "releaseId": release_id,
        "contentHash": release["contentHash"],
        "filesVerified": checked,
        "media": len(media_entries),
        "episodeLists": len(episode_entries),
        "bytes": sum(item["bytes"] for item in content),
    }
    if schemas:
        validation["schemaValidated"] = _validate_schemas(root, release_dir, release)
    return validation


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT / "build" / "v1")
    parser.add_argument("--release", default="current", help="current, previous, or rel-<hash>")
    parser.add_argument("--sample", action="store_true", help="hash only the first and last 50 files")
    parser.add_argument("--schemas", action="store_true", help="also validate JSON Schemas")
    parser.add_argument("--list", action="store_true", help="list retained releases and exit")
    args = parser.parse_args(argv)

    if args.list:
        for release_id in _release_ids(args.root):
            print(release_id)
        return 0

    try:
        result = verify_release(
            args.root,
            args.release,
            full=not args.sample,
            schemas=args.schemas,
        )
    except VerificationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
