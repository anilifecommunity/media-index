"""Shared v2 identity rules; no network, account data or title-based matching."""

import re

from release_lib import canonical_bytes, sha256_hex

KINDS = {"ANIME", "MOVIE", "TV", "MANGA", "COMIC", "NOVEL"}
SOURCE_FIELDS = ("engine", "repositoryId", "providerId", "stableItemId")
NUMERIC_NAMESPACES = {"anilist:anime", "anilist:manga", "mal:anime", "mal:manga", "tmdb:movie", "tmdb:tv"}
ALIAS_KINDS = {
    "anilist:anime": {"ANIME"}, "mal:anime": {"ANIME"},
    "anilist:manga": {"MANGA", "NOVEL"}, "mal:manga": {"MANGA", "NOVEL"},
    "tmdb:movie": {"ANIME", "MOVIE"}, "tmdb:tv": {"ANIME", "TV"},
    "imdb": {"ANIME", "MOVIE", "TV"},
}
KEY_PREFIXES = {
    "ANIME": ("al-", "src-"), "MANGA": ("al-", "src-"), "NOVEL": ("al-", "src-"),
    "MOVIE": ("tmdb-movie-", "src-"), "TV": ("tmdb-tv-", "src-"), "COMIC": ("src-",),
}


def positive_id(value) -> int:
    if type(value) is not int or not 1 <= value <= 9_007_199_254_740_991:
        raise ValueError("Identity must be a positive JSON-safe integer")
    return value


def anilist_kind(media_type: str, media_format: str | None) -> str | None:
    if media_type == "ANIME":
        return "ANIME"
    if media_type == "MANGA":
        if media_format == "NOVEL":
            return "NOVEL"
        if media_format in ("MANGA", "ONE_SHOT"):
            return "MANGA"
    return None


def canonical_key(kind: str, namespace: str, value: int) -> str:
    positive_id(value)
    if (namespace == "anilist:anime" and kind == "ANIME"
            or namespace == "anilist:manga" and kind in {"MANGA", "NOVEL"}):
        return f"al-{value}"
    if namespace == "tmdb:movie" and kind == "MOVIE":
        return f"tmdb-movie-{value}"
    if namespace == "tmdb:tv" and kind == "TV":
        return f"tmdb-tv-{value}"
    raise ValueError("No canonical key for this kind/namespace")


def source_key(kind: str, source_ref: dict) -> str:
    if kind not in KINDS:
        raise ValueError("Unknown media kind")
    parts = []
    for field in SOURCE_FIELDS:
        value = source_ref.get(field)
        if (not isinstance(value, str) or not 1 <= len(value) <= 512
                or any(char.isspace() or ord(char) < 32 or char in "?#@" for char in value)
                or value.lower().startswith(("http:", "https:"))):
            raise ValueError("Source identity needs nonsecret stable identifiers/paths, not URLs or queries")
        parts.append(value)
    parts.insert(3, kind)
    return "src-" + sha256_hex(canonical_bytes(parts))


def validate_alias(alias: dict, kind: str) -> None:
    namespace = alias.get("namespace")
    if namespace not in ALIAS_KINDS or kind not in ALIAS_KINDS[namespace]:
        raise ValueError("Alias namespace does not identify this media kind")
    if namespace in NUMERIC_NAMESPACES:
        positive_id(alias.get("id"))
    elif not isinstance(alias.get("id"), str) or not re.fullmatch(r"tt[0-9]{7,10}", alias["id"]):
        raise ValueError("Invalid IMDb identity")
    if type(alias.get("verified")) is not bool:
        raise ValueError("Alias verification must be explicit")


def validate_ref(ref: dict) -> None:
    kind, key = ref.get("kind"), ref.get("mediaKey")
    if kind not in KINDS or not isinstance(key, str):
        raise ValueError("Missing media kind/key")
    aliases = ref.get("aliases")
    if not isinstance(aliases, list) or len(aliases) > 32:
        raise ValueError("Aliases must be a bounded array")
    seen = set()
    for alias in aliases:
        if not isinstance(alias, dict):
            raise ValueError("Invalid alias")
        validate_alias(alias, kind)
        identity = (alias["namespace"], alias["id"])
        if identity in seen:
            raise ValueError("Duplicate alias")
        seen.add(identity)
    if key.startswith("src-"):
        source = ref.get("sourceRef")
        if not isinstance(source, dict) or key != source_key(kind, source):
            raise ValueError("Source key does not match its stable source identity")
    else:
        matched = False
        for alias in aliases:
            if not alias["verified"]:
                continue
            try:
                matched |= canonical_key(kind, alias["namespace"], alias["id"]) == key
            except ValueError:
                pass
        if not matched:
            raise ValueError("Canonical key needs its exact verified scoped identity")
    if kind == "ANIME" and ref.get("format") in {"MANGA", "NOVEL", "ONE_SHOT"}:
        raise ValueError("Anime identity cannot carry a reading format")
    if kind == "MANGA" and ref.get("format") == "NOVEL":
        raise ValueError("Known AniList novels require the explicit NOVEL projection")
    if kind == "NOVEL" and key.startswith("al-") and ref.get("format") != "NOVEL":
        raise ValueError("AniList novel identity needs explicit format evidence")


def _target_key(target: dict) -> bytes:
    if (set(target) != {"kind", "mediaKey"} or target["kind"] not in KINDS
            or not isinstance(target["mediaKey"], str)
            or not target["mediaKey"].startswith(KEY_PREFIXES[target["kind"]])
            or not re.fullmatch(r"(?:al-[1-9][0-9]*|tmdb-movie-[1-9][0-9]*|tmdb-tv-[1-9][0-9]*|src-[0-9a-f]{64})", target["mediaKey"])):
        raise ValueError("Invalid alias target")
    if not target["mediaKey"].startswith("src-"):
        positive_id(int(target["mediaKey"].rsplit("-", 1)[1]))
    return canonical_bytes(target)


def _alias_key(alias: dict) -> bytes:
    return canonical_bytes([alias["namespace"], alias["id"]])


def append_alias_ledger(previous: list[dict], additions: list[dict]) -> list[dict]:
    ledger = {}
    for entry in previous + additions:
        target = entry["target"]
        _target_key(target)
        if "sourceRef" in entry:
            if entry.get("verified") is not True or "alias" in entry:
                raise ValueError("Source mappings need explicit verified evidence")
            key = canonical_bytes(["source", target["kind"], source_key(target["kind"], entry["sourceRef"])])
        else:
            alias = entry["alias"]
            validate_alias(alias, target["kind"])
            if not alias["verified"]:
                raise ValueError("Unverified matches cannot bind an alias")
            key = _alias_key(alias)
        if key in ledger and ledger[key]["target"] != target:
            raise ValueError("An existing identity cannot be reassigned")
        ledger.setdefault(key, entry)
    return [ledger[key] for key in sorted(ledger)]


def validate_alias_ledger(record: dict) -> None:
    if record.get("schemaVersion") != "2.0.0":
        raise ValueError("Unsupported alias ledger version")
    bindings = append_alias_ledger([], record["bindings"])
    known = {_alias_key(entry["alias"]): entry for entry in bindings if "alias" in entry}
    seen = set()
    for entry in record.get("unresolvedAliases", []):
        alias, candidates = entry["alias"], entry["candidates"]
        if alias.get("verified") is not False or not 1 <= len(candidates) <= 32:
            raise ValueError("Invalid unresolved alias evidence")
        key = _alias_key(alias)
        if key in seen:
            raise ValueError("Duplicate unresolved alias")
        seen.add(key)
        targets = [_target_key(target) for target in candidates]
        if len(set(targets)) != len(targets):
            raise ValueError("Duplicate unresolved target")
        for target in candidates:
            validate_alias(alias, target["kind"])
        if key in known and known[key]["target"] not in candidates:
            raise ValueError("Unresolved evidence must retain the historical target")
        reason = entry["reason"]
        if reason == "ambiguous" and len(targets) < 2:
            raise ValueError("Ambiguity needs distinct candidates")
        if reason == "changed" and (key not in known or len(targets) < 2 or known[key]["target"] not in candidates):
            raise ValueError("A changed alias must retain its historical target")
        if reason not in {"ambiguous", "changed", "unverified"}:
            raise ValueError("Unknown alias resolution reason")


def reconcile_alias_ledger(previous: dict, refs: list[dict]) -> dict:
    """Retain historical bindings; quarantine current ambiguous, changed or unverified aliases."""
    validate_alias_ledger(previous)
    bindings = previous["bindings"]
    known = {_alias_key(entry["alias"]): entry for entry in bindings if "alias" in entry}
    pending = {_alias_key(entry["alias"]): entry for entry in previous.get("unresolvedAliases", [])}
    observations = {}
    for ref in refs:
        validate_ref(ref)
        target = {"kind": ref["kind"], "mediaKey": ref["mediaKey"]}
        for alias in ref["aliases"]:
            observations.setdefault(_alias_key(alias), []).append({"alias": alias, "target": target})
    additions = []
    for key, entries in observations.items():
        entries = sorted(entries, key=canonical_bytes)
        candidates = {_target_key(entry["target"]): entry["target"] for entry in entries}
        observed_count = len(candidates)
        historical = known.get(key)
        changed = historical is not None and any(entry["target"] != historical["target"] for entry in entries)
        if historical:
            candidates[_target_key(historical["target"])] = historical["target"]
        if observed_count > 1 or changed or not all(entry["alias"]["verified"] for entry in entries):
            pending[key] = {
                "alias": {**entries[0]["alias"], "verified": False},
                "reason": "ambiguous" if observed_count > 1 else "changed" if changed else "unverified",
                "candidates": [candidates[k] for k in sorted(candidates)],
            }
        else:
            pending.pop(key, None)
            additions.append(entries[0])
    result = {"schemaVersion": "2.0.0", "bindings": append_alias_ledger(bindings, additions),
              "unresolvedAliases": [pending[key] for key in sorted(pending)]}
    validate_alias_ledger(result)
    return result


def apply_alias_ledger(refs: list[dict], ledger: dict) -> list[dict]:
    """Downgrade contested aliases without changing a media key or any local progress identity."""
    validate_alias_ledger(ledger)
    blocked = {_alias_key(entry["alias"]) for entry in ledger.get("unresolvedAliases", [])}
    results = []
    for ref in refs:
        result = {**ref, "aliases": [{**alias, "verified": False} if _alias_key(alias) in blocked else alias for alias in ref["aliases"]]}
        validate_ref(result)
        results.append(result)
    return results
