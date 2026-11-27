"""Immutable v2 generations, complete verification and atomic local pointer promotion."""

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

import media_contract_v2 as contract
from media_identity_v2 import KINDS, append_alias_ledger, apply_alias_ledger, reconcile_alias_ledger, source_key
from release_lib import canonical_bytes, sha256_hex

EMPTY_LEDGER = {"schemaVersion": "2.0.0", "bindings": [], "unresolvedAliases": []}
NAMESPACE_MAGIC = b"anilife.media.v2\n"


def identity(ref):
    return canonical_bytes(contract.target(ref))


def bucket(path):
    return sha256_hex(path.encode("utf-8"))[:2]


def binding_key(entry):
    if "alias" in entry:
        return canonical_bytes([entry["alias"]["namespace"], entry["alias"]["id"]])
    return canonical_bytes(["source", entry["target"]["kind"], source_key(entry["target"]["kind"], entry["sourceRef"])])


def _path(root, relative):
    parts = PurePosixPath(relative).parts
    if (not parts or PurePosixPath(relative).is_absolute() or str(PurePosixPath(relative)) != relative
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in (".", "..") or p.endswith(".")
                   or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p, re.I) for p in parts)):
        raise ValueError("Invalid generation path")
    dest = root.joinpath(*parts)
    if not dest.resolve().is_relative_to(root.resolve()):
        raise ValueError("Generation path escapes its root")
    return dest


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_record(root, relative, checks, *, limit=contract.MAX_FILE_BYTES, expected=None):
    path = _path(root, relative)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError("Invalid file type or byte bound")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("File exceeds byte bound")
    if expected is not None and (len(raw) != expected["bytes"] or sha256_hex(raw) != expected["sha256"]):
        raise ValueError("File size or hash mismatch")
    record = json.loads(raw, object_pairs_hook=_pairs)
    if canonical_bytes(record) != raw:
        raise ValueError("Noncanonical JSON")
    contract.validate_record(record, checks)
    return record


def _write(root, relative, record, checks):
    contract.validate_record(record, checks)
    raw = canonical_bytes(record)
    path = _path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": relative, "bytes": len(raw), "sha256": sha256_hex(raw)}


@contextmanager
def publication_lock(root):
    root = Path(root).resolve()
    if (root / ".git").exists() or (root / "data").exists():
        raise ValueError("Use the separate v2 output directory")
    marker = _path(root, ".v2-namespace")
    if marker.exists():
        with marker.open("rb") as handle:
            if handle.read(len(NAMESPACE_MAGIC) + 1) != NAMESPACE_MAGIC:
                raise ValueError("Invalid v2 namespace marker")
    if (root / "manifest.json").exists() and not marker.exists():
        with _path(root, "manifest.json").open("rb") as handle:
            raw = handle.read(contract.MAX_POINTER_BYTES + 1)
        if len(raw) > contract.MAX_POINTER_BYTES or json.loads(raw).get("schemaVersion") != contract.VERSION:
            raise ValueError("Refusing to write into a v1 namespace")
    root.mkdir(parents=True, exist_ok=True)
    lock = _path(root, ".publish.lock")
    if lock.is_symlink():
        raise ValueError("Publication lock cannot be a symlink")
    with lock.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if not marker.exists():
                marker.write_bytes(NAMESPACE_MAGIC)
            yield root
        finally:
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def verify_generation(generation, release_id, checks=None):
    generation = Path(generation)
    if generation.is_symlink() or generation.is_junction():
        raise ValueError("A generation cannot be a filesystem link")
    checks = checks or contract.validators()
    if not re.fullmatch(r"rel-[0-9a-f]{16}", release_id):
        raise ValueError("Invalid release identity")
    manifest = read_record(generation, "manifest.json", checks, limit=contract.MAX_MANIFEST_BYTES)
    if manifest.get("recordType") != "manifest" or manifest["releaseId"] != release_id:
        raise ValueError("Generation manifest identity mismatch")
    inventory, records, seen_buckets = {}, {}, set()
    for descriptor in manifest["buckets"]:
        record = read_record(generation, descriptor["path"], checks, expected=descriptor)
        name = record.get("bucket")
        if record.get("recordType") != "bucket" or descriptor["path"] != f"buckets/{name}.json" or name in seen_buckets:
            raise ValueError("Invalid or duplicate bucket inventory")
        seen_buckets.add(name)
        for item in record["files"]:
            path = item["path"]
            if path in inventory or bucket(path) != name:
                raise ValueError("Duplicate or misplaced payload")
            inventory[path] = item
            payload = read_record(generation, path, checks, expected=item)
            if "bindings" not in payload and payload["recordType"] not in {"detail", "episodes", "chapters", "catalogue", "search"}:
                raise ValueError("Invalid payload record type")
            if "bindings" in payload and not re.fullmatch(r"identity/[0-9a-f]{2}\.json", path):
                raise ValueError("Invalid identity shard path")
            if payload.get("recordType") in {"catalogue", "search"}:
                group = payload["recordType"]
                if not re.fullmatch(group + r"/[0-3][0-9a-f]/[0-9]{5}\.json", path):
                    raise ValueError("Invalid index page path")
            records[path] = payload
    content_hash = sha256_hex(canonical_bytes(sorted(inventory.values(), key=lambda item: item["path"])))
    if manifest["contentHash"] != content_hash or release_id != "rel-" + content_hash[:16]:
        raise ValueError("Generation content identity mismatch")
    ledger = copy.deepcopy(EMPTY_LEDGER)
    for group, descriptors in manifest["bootstrap"].items():
        for item in descriptors:
            if inventory.get(item["path"]) != item:
                raise ValueError("Bootstrap is absent from the verified inventory")
            payload = records[item["path"]]
            if group == "identity":
                if "bindings" not in payload:
                    raise ValueError("Invalid identity bootstrap")
                shard = item["path"].removeprefix("identity/").removesuffix(".json")
                for field in ("bindings", "unresolvedAliases"):
                    entries = payload.get(field, [])
                    if any(sha256_hex(binding_key(entry))[:2] != shard for entry in entries):
                        raise ValueError("Identity binding in the wrong shard")
                    ledger[field].extend(entries)
            elif payload.get("recordType") != group:
                raise ValueError("Bootstrap record type mismatch")
    from media_identity_v2 import validate_alias_ledger
    validate_alias_ledger(ledger)
    all_ledgers = {path for path, payload in records.items() if "bindings" in payload}
    if all_ledgers != {f"identity/{i:02x}.json" for i in range(256)}:
        raise ValueError("Incomplete identity shard coverage")
    if all_ledgers != {d["path"] for d in manifest["bootstrap"]["identity"]}:
        raise ValueError("Unlisted identity shard")
    details, owned_units = {}, set()
    for path, record in records.items():
        if record.get("recordType") != "detail":
            continue
        key = identity(record["ref"])
        if key in details or path != f"media/{record['ref']['kind']}/{record['ref']['mediaKey']}.json":
            raise ValueError("Duplicate or misplaced detail identity")
        details[key] = record
        offset, units = 0, set()
        for page_index, item in enumerate(record["unitPages"]["pages"]):
            if inventory.get(item["path"]) != item or item["path"] in owned_units:
                raise ValueError("Missing or multiply owned unit page")
            page = records[item["path"]]
            expected_type = "episodes" if record["ref"]["kind"] in {"ANIME", "MOVIE", "TV"} else "chapters"
            expected_path = f"units/{record['ref']['kind']}/{record['ref']['mediaKey']}/{page_index:05}.json"
            if (item["path"] != expected_path or page.get("recordType") != expected_type
                    or identity(page["ref"]) != key or page["offset"] != offset
                    or page["coverage"] != record["unitPages"]["coverage"]):
                raise ValueError("Unit page identity or offset mismatch")
            ids = {unit["unitId"] for unit in page["units"]}
            if units & ids:
                raise ValueError("Duplicate unit across pages")
            units |= ids
            offset += len(page["units"])
            owned_units.add(item["path"])
        if record["unitPages"]["coverage"] == "complete" and record.get("declaredUnitCount") != offset:
            raise ValueError("Complete units do not match the declared count")
    if owned_units != {path for path, p in records.items() if p.get("recordType") in {"episodes", "chapters"}}:
        raise ValueError("Orphan unit page")
    refs = [record["ref"] for record in details.values()]
    detail_keys = set(details)
    for detail in details.values():
        members = {identity(m["ref"]) for m in detail["franchise"]["members"]}
        unresolved = {identity(ref) for ref in detail["franchise"]["unresolved"]}
        if not members - detail_keys <= unresolved:
            raise ValueError("Missing franchise details must remain unresolved")
        if any(edge["resolved"] and identity(edge["related"]) not in details for edge in detail["relations"]):
            raise ValueError("Resolved relation is absent from this snapshot")
    if apply_alias_ledger(refs, ledger) != refs:
        raise ValueError("Contested alias still marked verified")
    known = {binding_key(entry): entry["target"] for entry in ledger["bindings"] if "alias" in entry}
    for ref in refs:
        for alias in ref["aliases"]:
            if alias["verified"] and known.get(canonical_bytes([alias["namespace"], alias["id"]])) != contract.target(ref):
                raise ValueError("Verified alias has no matching ledger binding")
    for group in ("catalogue", "search"):
        starts = {f"{group}/{shard:02x}/00000.json" for shard in range(64)}
        if {d["path"] for d in manifest["bootstrap"][group]} != starts:
            raise ValueError("Index bootstrap must contain every first shard page")
        for shard in range(64):
            paths = sorted(path for path in records if path.startswith(f"{group}/{shard:02x}/"))
            if paths != [f"{group}/{shard:02x}/{i:05}.json" for i in range(len(paths))]:
                raise ValueError("Index pages must be contiguous")
        seen = set()
        for path, payload in records.items():
            if payload.get("recordType") != group:
                continue
            for row in payload["rows" if group == "catalogue" else "entries"]:
                key = identity(row["ref"])
                detail = details.get(key)
                expected = contract.catalogue_row(detail) if group == "catalogue" and detail else contract.search_entry(detail) if detail else None
                if key in seen or detail is None or row != expected or int(sha256_hex(key)[:8], 16) % 64 != int(path.split("/")[1], 16):
                    raise ValueError("Index identity, shard or detail projection mismatch")
                seen.add(key)
        if seen != set(details):
            raise ValueError("Index omitted a detail")
    expected = set(inventory) | {d["path"] for d in manifest["buckets"]} | {"manifest.json"}
    actual = set()
    for directory, children, files in os.walk(generation, followlinks=False):
        for name in children + files:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("Filesystem link inside a generation")
        actual.update((Path(directory) / name).relative_to(generation).as_posix() for name in files)
    if actual != expected:
        raise ValueError("Generation contains unlisted files")
    return {"manifest": manifest, "ledger": ledger, "details": len(details), "files": len(inventory)}


def verify(root, release_id=None, checks=None):
    root = Path(root).resolve()
    checks = checks or contract.validators()
    if release_id is None:
        pointer = read_record(root, "manifest.json", checks, limit=contract.MAX_POINTER_BYTES)
        if pointer.get("recordType") != "pointer":
            raise ValueError("Invalid pointer record type")
        release_id = pointer["releaseId"]
        expected_path = f"releases/{release_id}/manifest.json"
        if pointer.get("recordType") != "pointer" or pointer["manifest"]["path"] != expected_path:
            raise ValueError("Pointer does not address its generation")
        read_record(root, expected_path, checks, limit=contract.MAX_MANIFEST_BYTES, expected=pointer["manifest"])
    return verify_generation(_path(root, f"releases/{release_id}"), release_id, checks)


def _promote(root, release_id, checks):
    verified = verify(root, release_id, checks)
    raw = canonical_bytes(verified["manifest"])
    pointer = {"schemaVersion": contract.VERSION, "recordType": "pointer", "releaseId": release_id,
               "manifest": {"path": f"releases/{release_id}/manifest.json", "bytes": len(raw), "sha256": sha256_hex(raw)}}
    contract.validate_record(pointer, checks)
    descriptor, name = tempfile.mkstemp(prefix=".pointer-", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(pointer))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / "manifest.json")
    finally:
        temporary.unlink(missing_ok=True)
    return verified


def promote(root, release_id):
    with publication_lock(root) as root:
        return _promote(root, release_id, contract.validators())


def _cleanup(staging, root):
    if staging.resolve().parent != root.resolve() or not staging.name.startswith(".v2-") or staging.is_symlink():
        raise ValueError("Unsafe staging cleanup path")
    if staging.exists():
        shutil.rmtree(staging)


def retained_history(root, checks):
    """Rollback changes the serving pointer, never previously assigned identities."""
    bindings, pending = [], {}
    generations = root / "releases"
    for path in sorted(generations.iterdir()) if generations.exists() else []:
        ledger = verify(root, path.name, checks)["ledger"]
        bindings = append_alias_ledger(bindings, ledger["bindings"])
        for entry in ledger.get("unresolvedAliases", []):
            key = binding_key(entry)
            candidates = {identity(t): t for t in entry["candidates"]}
            candidates.update({identity(t): t for t in pending.get(key, {}).get("candidates", [])})
            pending[key] = {**entry, "reason": "ambiguous" if len(candidates) > 1 else "unverified",
                            "candidates": [candidates[k] for k in sorted(candidates)]}
    for binding in bindings:
        key = binding_key(binding)
        if key in pending and binding["target"] not in pending[key]["candidates"]:
            pending[key]["candidates"].append(binding["target"])
            pending[key]["candidates"].sort(key=identity)
            pending[key]["reason"] = "ambiguous"
    return {"schemaVersion": contract.VERSION, "bindings": bindings,
            "unresolvedAliases": [pending[k] for k in sorted(pending)]}


def write_release(root, details, pages, generated_at, *, publish=False, coverage=None, source_bindings=()):
    checks = contract.validators()
    with publication_lock(root) as root:
        if (root / "manifest.json").exists():
            verify(root, checks=checks)
        previous = retained_history(root, checks)
        for binding in source_bindings:
            if "sourceRef" not in binding:
                raise ValueError("Explicit source bindings require a sourceRef")
            contract.validate_record({"schemaVersion": contract.VERSION, "bindings": [binding]}, checks)
        previous = {**previous, "bindings": append_alias_ledger(previous["bindings"], list(source_bindings))}
        details = sorted(copy.deepcopy(details), key=lambda d: identity(d["ref"]))
        if len({identity(d["ref"]) for d in details}) != len(details):
            raise ValueError("Duplicate detail identity")
        ledger = reconcile_alias_ledger(previous, [d["ref"] for d in details])
        for detail, ref in zip(details, apply_alias_ledger([d["ref"] for d in details], ledger)):
            detail["ref"] = ref
        staging = Path(tempfile.mkdtemp(prefix=".v2-", dir=root))
        try:
            inventory, bootstrap = [], {"catalogue": [], "search": [], "identity": []}
            def put(path, record):
                descriptor = _write(staging, path, record, checks)
                inventory.append(descriptor)
                return descriptor
            by_media = {}
            for page in pages:
                by_media.setdefault(identity(page["ref"]), []).append(page)
            for detail in details:
                ref = detail["ref"]
                owned = sorted(by_media.pop(identity(ref), []), key=lambda p: p["offset"])
                detail["unitPages"] = {"coverage": owned[0]["coverage"] if owned else "unresolved", "pages": [
                    put(f"units/{ref['kind']}/{ref['mediaKey']}/{index:05}.json", page) for index, page in enumerate(owned)]}
                put(f"media/{ref['kind']}/{ref['mediaKey']}.json", detail)
            if by_media:
                raise ValueError("Unit page has no detail owner")
            for group in ("catalogue", "search"):
                shards = [[] for _ in range(64)]
                for detail in details:
                    shard = int(sha256_hex(identity(detail["ref"]))[:8], 16) % 64
                    shards[shard].append(contract.catalogue_row(detail) if group == "catalogue" else contract.search_entry(detail))
                for shard, rows in enumerate(shards):
                    field = "rows" if group == "catalogue" else "entries"
                    header = {"schemaVersion": contract.VERSION, "recordType": group, "coverage": "partial", field: []}
                    base_size = len(canonical_bytes(header))
                    size = base_size
                    chunk, chunks = [], []
                    for row in rows:
                        row_size = len(canonical_bytes(row))
                        if chunk and (len(chunk) == 1000 or size + row_size + 1 > contract.MAX_FILE_BYTES):
                            chunks.append(chunk)
                            chunk = []
                            size = base_size
                        size += row_size + bool(chunk)
                        chunk.append(row)
                    chunks.append(chunk)
                    for index, chunk in enumerate(chunks):
                        descriptor = put(f"{group}/{shard:02x}/{index:05}.json",
                                         {"schemaVersion": contract.VERSION, "recordType": group, "coverage": "partial", field: chunk})
                        if index == 0:
                            bootstrap[group].append(descriptor)
            shards = [copy.deepcopy(EMPTY_LEDGER) for _ in range(256)]
            for field in ("bindings", "unresolvedAliases"):
                for entry in ledger[field]:
                    shards[int(sha256_hex(binding_key(entry))[:2], 16)][field].append(entry)
            for index, shard in enumerate(shards):
                bootstrap["identity"].append(put(f"identity/{index:02x}.json", shard))
            content_hash = sha256_hex(canonical_bytes(sorted(inventory, key=lambda item: item["path"])))
            release_id = "rel-" + content_hash[:16]
            buckets = {}
            for item in inventory:
                buckets.setdefault(bucket(item["path"]), []).append(item)
            descriptors = [_write(staging, f"buckets/{name}.json", {"schemaVersion": contract.VERSION,
                "recordType": "bucket", "bucket": name, "files": sorted(items, key=lambda item: item["path"])}, checks)
                for name, items in sorted(buckets.items())]
            _write(staging, "manifest.json", {"schemaVersion": contract.VERSION, "recordType": "manifest", "contract": "anilife.media",
                "releaseId": release_id, "contentHash": content_hash, "generatedAt": generated_at,
                "coverage": coverage or {kind: "partial" if any(d["ref"]["kind"] == kind for d in details) else "unresolved" for kind in sorted(KINDS)},
                "buckets": descriptors, "bootstrap": bootstrap}, checks)
            verify_generation(staging, release_id, checks)
            dest = _path(root, f"releases/{release_id}")
            if dest.exists():
                verify_generation(dest, release_id, checks)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                staging.rename(dest)
            return _promote(root, release_id, checks) if publish else verify(root, release_id, checks)
        finally:
            _cleanup(staging, root)
