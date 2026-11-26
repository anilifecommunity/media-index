"""Pure v1 projection and bounded v2 validation shared by publication and fixtures."""

import json
from pathlib import Path, PurePosixPath

from media_identity_v2 import KINDS, anilist_kind, append_alias_ledger, canonical_key, validate_ref
from release_lib import canonical_bytes, normalize_name, visibility_of

VERSION = "2.0.0"
MAX_DETAIL_BYTES = 262144
MAX_FILE_BYTES = 2097152
MAX_POINTER_BYTES = 4096
MAX_MANIFEST_BYTES = 262144
MAX_LEDGER_BYTES = MAX_FILE_BYTES
ROOT = Path(__file__).resolve().parent.parent


def alias(namespace: str, value: int, source: str = "anilist") -> dict:
    return {"namespace": namespace, "id": value, "verified": True, "provenance": {"source": source}}


def anime_ref(anilist_id: int, media_format=None, mal_id=None) -> dict:
    aliases = [alias("anilist:anime", anilist_id)]
    if mal_id is not None:
        aliases.append(alias("mal:anime", mal_id, "anilist-cross-reference"))
    return {"kind": "ANIME", "mediaKey": canonical_key("ANIME", "anilist:anime", anilist_id), "format": media_format, "aliases": aliases}


def target(ref: dict) -> dict:
    return {"kind": ref["kind"], "mediaKey": ref["mediaKey"]}


def adapt_v1_media(record: dict) -> dict:
    if record.get("kind") != "ANIME" or not record.get("schemaVersion", "").startswith("1."):
        raise ValueError("Only the existing v1 anime contract can be projected")
    ref = anime_ref(record["ids"]["anilist"], record.get("format"), record["ids"].get("mal"))
    if ref["mediaKey"] != record["mediaKey"]:
        raise ValueError("v1 canonical identity mismatch")
    relations = []
    for edge in record.get("relations", []):
        node = edge.get("node") or {}
        kind = anilist_kind(edge["kind"], node.get("format"))
        namespace = "anilist:anime" if edge["kind"] == "ANIME" else "anilist:manga"
        related_aliases = [alias(namespace, edge["ids"]["anilist"])] if edge["kind"] in ("ANIME", "MANGA") else []
        related = {"kind": kind, "mediaKey": None, "aliases": related_aliases}
        if kind is not None:
            related.update(mediaKey=canonical_key(kind, namespace, edge["ids"]["anilist"]), format=node.get("format"))
        relations.append({"relationType": edge["relationType"], "related": related,
                          "resolved": bool(edge.get("resolved") and kind),
                          "confidence": "verified" if kind else "unresolved", "provenance": {"source": "anilist"}})
    ids = list(dict.fromkeys([record["ids"]["anilist"]] + record.get("seriesIds", [])))
    members = [{"ref": target(anime_ref(media_id)), "order": index, "role": "UNKNOWN", "sourceSeason": None,
                "absoluteOrdinal": None, "provenance": {"source": "legacy-series"}}
               for index, media_id in enumerate(ids[:16])]
    result = {
        "schemaVersion": VERSION, "recordType": "detail", "ref": ref,
        "titles": record["titles"], "status": record.get("status"),
        "synopsis": (record.get("synopsis") or {}).get("text"),
        "isAdult": record.get("isAdult"), "visibility": visibility_of(record.get("isAdult")),
        "images": record.get("images", {}), "genres": record.get("genres", []), "relations": relations,
        "franchise": {"coverage": "unresolved", "members": members, "unresolved": [m["ref"] for m in members], "truncated": len(ids) > 16},
        "unitPages": {"coverage": "unresolved", "pages": []}, "provenance": record["provenance"],
    }
    for key in ("season", "seasonYear", "startDate", "endDate", "studios", "score", "durationMinutes", "nextAiringEpisode"):
        if key in record:
            result[key] = record[key]
    result["declaredUnitCount"] = (record.get("episodes") or {}).get("declared")
    return result


def adapt_v1_episodes(record: dict, declared_count: int | None) -> list[dict]:
    if record.get("kind") != "ANIME" or not record.get("schemaVersion", "").startswith("1."):
        raise ValueError("Not a v1 anime episode list")
    ref = {"kind": "ANIME", "mediaKey": record["mediaKey"]}
    units = []
    for episode in record["episodes"]:
        number = episode["number"]
        if type(number) is not int or number < 1:
            raise ValueError("Invalid legacy episode identity")
        unit = {"unitId": f"episode-{number}", "displayOrdinal": str(number),
                      "sourceOrdinal": None, "sourceSeason": None, "absoluteOrdinal": None,
                      "title": episode["title"], "airDate": episode["airDate"],
                      "availability": "unknown", "provenance": {"source": episode["source"]}}
        for key in ("still", "runtimeMinutes", "rating", "synopsis"):
            if key in episode:
                unit[key] = episode[key]
        units.append(unit)
    coverage = "unresolved" if record["availability"] != "AVAILABLE" else "complete" if declared_count == len(units) else "partial"
    return unit_pages(ref, "episodes", coverage, units)


def unit_pages(ref: dict, record_type: str, coverage: str, units: list[dict]) -> list[dict]:
    if record_type not in ("episodes", "chapters"):
        raise ValueError("Unknown unit-page type")
    def empty_page(offset: int) -> dict:
        return {"schemaVersion": VERSION, "recordType": record_type, "ref": ref,
                "coverage": coverage, "offset": offset, "units": []}
    pages = []
    page = empty_page(0)
    size = len(canonical_bytes(page))
    for unit in units:
        unit_size = len(canonical_bytes(unit))
        if page["units"] and (len(page["units"]) >= 500 or size + unit_size + 1 > MAX_FILE_BYTES):
            pages.append(page)
            page = empty_page(page["offset"] + len(page["units"]))
            size = len(canonical_bytes(page))
        addition = unit_size + (1 if page["units"] else 0)
        if size + addition > MAX_FILE_BYTES:
            raise ValueError("A single unit exceeds the page byte bound")
        page["units"].append(unit)
        size += addition
    pages.append(page)
    return pages


def catalogue_row(detail: dict) -> dict:
    return {"ref": target(detail["ref"]), "title": detail["titles"]["display"],
            "format": detail["ref"].get("format"), "visibility": detail["visibility"],
            "poster": detail.get("images", {}).get("poster")}


def search_entry(detail: dict) -> dict:
    names = [detail["titles"].get(key) for key in ("display", "english", "romaji", "native")]
    names += [item["value"] for item in detail["titles"].get("synonyms", [])]
    tokens = sorted({normalize_name(name) for name in names if name})
    return {"ref": target(detail["ref"]), "tokens": tokens}


def validators() -> tuple:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    schemas = [json.loads(path.read_text(encoding="utf-8")) for version in ("v1", "v2")
               for path in (ROOT / "schema" / version).glob("*.schema.json")]
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    contract = next(schema for schema in schemas if schema["$id"].endswith("v2/contract.schema.json"))
    ledger = next(schema for schema in schemas if schema["$id"].endswith("v2/alias-ledger.schema.json"))
    return tuple(Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()) for schema in (contract, ledger))


def validate_record(record: dict, loaded_validators: tuple) -> None:
    from jsonschema.exceptions import ValidationError
    is_ledger = "bindings" in record
    try:
        loaded_validators[1 if is_ledger else 0].validate(record)
    except ValidationError as error:
        while error.context:
            error = max(error.context, key=lambda item: len(item.absolute_path))
        raise ValueError(f"Schema violation at {error.json_path} ({error.validator})") from None
    limits = {"detail": MAX_DETAIL_BYTES, "pointer": MAX_POINTER_BYTES, "manifest": MAX_MANIFEST_BYTES}
    limit = MAX_LEDGER_BYTES if is_ledger else limits.get(record["recordType"], MAX_FILE_BYTES)
    if len(canonical_bytes(record)) > limit:
        raise ValueError("Record exceeds the v2 byte bound")
    if is_ledger:
        append_alias_ledger([], record["bindings"])
        return
    if record["recordType"] == "detail":
        validate_ref(record["ref"])
        if record["visibility"] != visibility_of(record["isAdult"]):
            raise ValueError("Visibility does not match the explicit adult classification")
        franchise = record["franchise"]
        validate_files(record["unitPages"]["pages"])
        keys = [canonical_bytes(member["ref"]) for member in franchise["members"]]
        if len(set(keys)) != len(keys) or [member["order"] for member in franchise["members"]] != list(range(len(keys))):
            raise ValueError("Franchise identity/order is not unique and contiguous")
        if canonical_bytes(target(record["ref"])) not in keys:
            raise ValueError("The detail's own identity must remain in its franchise")
        if not {canonical_bytes(ref) for ref in franchise["unresolved"]} <= set(keys):
            raise ValueError("Unresolved members must belong to the franchise")
        if franchise["coverage"] == "complete" and (franchise["unresolved"] or franchise["truncated"]):
            raise ValueError("Incomplete membership cannot claim complete coverage")
        for edge in record["relations"]:
            related = edge["related"]
            if related["mediaKey"] is not None:
                validate_ref(related)
                if edge["resolved"] and edge["confidence"] != "verified":
                    raise ValueError("Resolved identity needs verified evidence")
            elif edge["resolved"] or edge["confidence"] == "verified":
                raise ValueError("Unresolved identity cannot claim verified resolution")
    if record["recordType"] in ("episodes", "chapters"):
        ids = [unit["unitId"] for unit in record["units"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate unit identities")
    if record["recordType"] in ("catalogue", "search"):
        rows = record["rows"] if record["recordType"] == "catalogue" else record["entries"]
        identities = [canonical_bytes(row["ref"]) for row in rows]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate media identities")
    if record["recordType"] in ("manifest", "pointer", "bucket"):
        if record["recordType"] == "manifest":
            files = record["buckets"]
            validate_files([file for group in record["bootstrap"].values() for file in group])
        elif record["recordType"] == "bucket":
            files = record["files"]
        else:
            files = [record["manifest"]]
        validate_files(files)


def validate_files(files: list[dict]) -> None:
    paths = [file["path"] for file in files]
    if len(paths) != len(set(paths)) or any(str(PurePosixPath(path)) != path for path in paths):
        raise ValueError("File inventory paths must be unique and canonical")
