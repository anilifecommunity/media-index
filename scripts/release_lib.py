"""Shared, dependency-free helpers for the v1 release contract.

Everything here is pure: given the same input bytes it produces the same
output bytes. That property is what makes ``releaseId`` content-addressed and
lets the publisher skip a release whose catalogue has not changed.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from typing import Any, Iterable

SCHEMA_VERSION = "1.1.0"
CONTRACT = "anilife.media"
CATALOG_SHARDS = 64
BUCKETS = 256

MANGA_FORMATS = {"MANGA", "NOVEL", "ONE_SHOT"}

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(?:br|/p|/div|/li)\s*/?\s*>", re.IGNORECASE)
_SPACE = re.compile(r"[ \t\r\f\v]+")


def canonical_bytes(payload: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, no ASCII escaping, no whitespace."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_key(anilist_id: int) -> str:
    """Stable first-party key. Derived, never reassigned."""
    return f"al-{int(anilist_id)}"


def anilist_id_of(key: str) -> int:
    if not key.startswith("al-"):
        raise ValueError(f"not an AniList-origin mediaKey: {key!r}")
    return int(key[3:])


def bucket_of(key: str) -> str:
    return sha256_hex(key.encode("utf-8"))[:2]


def catalog_shard_of(key: str) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[2:10], "big") % CATALOG_SHARDS


def normalize_name(value: str) -> str:
    """Case-fold, compatibility-normalize and strip Latin diacritics; keep kana intact."""
    result: list[str] = []
    for ch in unicodedata.normalize("NFD", value):
        if unicodedata.combining(ch) and result and "LATIN" in unicodedata.name(result[-1], ""):
            continue
        result.append(ch)
    folded = unicodedata.normalize("NFC", "".join(result)).casefold()
    folded = unicodedata.normalize("NFKC", folded)
    return _SPACE.sub(" ", folded).strip()


def search_bucket_of_normalized(normalized: str) -> str:
    if not normalized:
        return "num"
    first = normalized[0]
    if "a" <= first <= "z":
        return first
    if "0" <= first <= "9":
        return "num"
    return f"other-{int(hashlib.sha256(normalized.encode('utf-8')).hexdigest()[0], 16) % 8}"


def visibility_of(is_adult: bool | None) -> str:
    if is_adult is True:
        return "adult"
    if is_adult is False:
        return "general"
    return "unknown-conservative"


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(_TAG.sub("", _BREAK.sub("\n", value)))
    text = "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def image_source(url: str) -> str:
    if "anilist.co" in url:
        return "anilist"
    if "image.tmdb.org" in url:
        return "tmdb"
    if "ani.zip" in url or "anizip" in url:
        return "anizip"
    return "unknown"


def image_ref(url: str | None, kind: str, color: str | None = None) -> dict | None:
    """A pointer, never an ownership claim. Binary mirroring needs separate approval."""
    if not url:
        return None
    ref: dict[str, Any] = {
        "url": url,
        "source": image_source(url),
        "kind": kind,
        "permission": "reference-only",
    }
    if color is not None:
        ref["color"] = color
    if kind in ("poster", "banner", "logo"):
        ref["attribution"] = ref["source"]
    return ref


def partial_date(value: dict | None) -> dict | None:
    if not value or not value.get("year"):
        return None
    return {
        "year": value["year"],
        "month": value.get("month"),
        "day": value.get("day"),
    }


def relation_kind(node: dict) -> str:
    fmt = (node.get("format") or "").upper()
    if fmt in MANGA_FORMATS:
        return "MANGA"
    if fmt in {"TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC"}:
        return "ANIME"
    if node.get("type") in ("ANIME", "MANGA"):
        return node["type"]
    return "UNKNOWN"


def unique_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_media_record(
    detail: dict,
    index_row: dict,
    *,
    ids: dict,
    episodes_available: bool,
    known_anime: set[int],
) -> dict:
    titles = detail.get("titles") or {}
    anilist = detail.get("anilist") or {}
    anilist_titles = anilist.get("title") or {}
    english = titles.get("english") or anilist_titles.get("english")
    romaji = titles.get("romaji") or anilist_titles.get("romaji")
    native = titles.get("native") or anilist_titles.get("native")
    display = english or romaji or native or index_row.get("title")
    is_adult = anilist.get("isAdult") if "isAdult" in anilist else None
    anilist_id = int(detail.get("ids", {}).get("anilist") or index_row["id"])

    images = detail.get("images") or {}
    relations: list[dict] = []
    for edge in ((anilist.get("relations") or {}).get("edges")) or []:
        node = edge.get("node") or {}
        node_id = node.get("id")
        if not node_id:
            continue
        kind = relation_kind(node)
        resolved = kind == "ANIME" and int(node_id) in known_anime
        relations.append(
            {
                "relationType": edge.get("relationType") or "UNKNOWN",
                "kind": kind,
                "ids": {"anilist": int(node_id), "mal": node.get("idMal")},
                "mediaKey": media_key(int(node_id)) if resolved else None,
                "resolved": resolved,
                "name": (node.get("title") or {}).get("romaji"),
                "node": {
                    "id": int(node_id),
                    "idMal": node.get("idMal"),
                    "title": node.get("title"),
                    "format": node.get("format"),
                    "countryOfOrigin": node.get("countryOfOrigin"),
                    "description": clean_text(node.get("description")),
                    "poster": (node.get("coverImage") or {}).get("large"),
                    "isAdult": node.get("isAdult"),
                    "episodes": node.get("episodes"),
                },
            }
        )

    recommendations: list[dict] = []
    for node in detail.get("recommendations") or []:
        node_id = node.get("id")
        if not node_id:
            continue
        resolved = int(node_id) in known_anime
        recommendations.append(
            {
                "ids": {"anilist": int(node_id)},
                "mediaKey": media_key(int(node_id)) if resolved else None,
                "resolved": resolved,
                "card": node,
            }
        )

    series: list[str] = []
    series_ids: list[int] = []
    for value in detail.get("series") or []:
        try:
            series_ids.append(int(value))
            series.append(media_key(int(value)))
        except (TypeError, ValueError):
            continue

    bangumi = detail.get("bangumi") or None
    bangumi_record = None
    if bangumi:
        bangumi_record = {
            "id": bangumi.get("id"),
            "confidence": bangumi.get("confidence") or "UNKNOWN",
            "names": unique_keep_order(
                [bangumi.get("name"), bangumi.get("name_cn"), *(bangumi.get("search_names") or [])]
            ),
        }

    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "mediaKey": media_key(anilist_id),
        "kind": "ANIME",
        "ids": {
            "anilist": anilist_id,
            "mal": ids.get("mal"),
            "tmdb": ids.get("tmdb"),
            "kitsu": ids.get("kitsu"),
            "anidb": ids.get("anidb"),
            "simkl": ids.get("simkl"),
            "tvdb": ids.get("tvdb"),
            "bangumi": ids.get("bangumi"),
        },
        "titles": {
            "english": english,
            "romaji": romaji,
            "native": native,
            "display": display,
            "synonyms": title_synonyms(detail, (english, romaji, native)),
        },
        "synopsis": (
            {
                "text": clean_text(anilist.get("description") or detail.get("description")),
                "language": None,
                "source": "anilist",
                "spoiler": False,
            }
            if clean_text(anilist.get("description") or detail.get("description"))
            else None
        ),
        "format": detail.get("format") or index_row.get("format"),
        "status": detail.get("status") or index_row.get("status"),
        "season": detail.get("season"),
        "seasonYear": detail.get("season_year") or index_row.get("year"),
        "episodes": {
            "declared": detail.get("episodes"),
            "available": episodes_available,
            "numbering": "position",
        },
        "durationMinutes": detail.get("duration"),
        "genres": detail.get("genres") or [],
        "tags": [
            {
                "name": tag.get("name"),
                "rank": tag.get("rank"),
                "spoiler": bool(tag.get("isMediaSpoiler") or tag.get("isGeneralSpoiler")),
            }
            for tag in anilist.get("tags") or []
            if tag.get("name")
        ],
        "score": (
            {"value": anilist["averageScore"], "scale": 100, "source": "anilist"}
            if anilist.get("averageScore") is not None
            else None
        ),
        "popularity": anilist.get("popularity") or detail.get("popularity"),
        "isAdult": is_adult,
        "visibility": visibility_of(is_adult),
        "countryOfOrigin": anilist.get("countryOfOrigin"),
        "startDate": partial_date(anilist.get("startDate")),
        "endDate": partial_date(anilist.get("endDate")),
        "studios": [
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "animation": bool(node.get("isAnimationStudio")),
            }
            for node in ((anilist.get("studios") or {}).get("nodes") or [])
            if node.get("id") and node.get("name")
        ],
        "images": {
            key: ref
            for key, ref in (
                ("poster", image_ref(images.get("poster"), "poster", images.get("poster_color"))),
                ("banner", image_ref(images.get("banner"), "banner")),
                ("logo", image_ref(images.get("logo"), "logo")),
            )
            if ref is not None
        },
        "relations": relations,
        "recommendations": recommendations,
        "series": series,
        "seriesIds": series_ids,
        "anilist": anilist or None,
        "trailer": anilist.get("trailer"),
        "nextAiringEpisode": anilist.get("nextAiringEpisode"),
        "meanScore": anilist.get("meanScore"),
        "favourites": anilist.get("favourites"),
        "bangumi": bangumi_record,
        "provenance": {
            "source": "anilist+tmdb",
        },
    }
    return record


def build_catalog_row(media: dict) -> dict:
    titles = media["titles"]
    poster = media["images"].get("poster")
    return {
        "mediaKey": media["mediaKey"],
        "kind": media["kind"],
        "ids": {"anilist": media["ids"]["anilist"], "mal": media["ids"]["mal"]},
        "titles": {
            "english": titles["english"],
            "romaji": titles["romaji"],
            "native": titles["native"],
            "display": titles["display"],
        },
        "format": media["format"],
        "status": media["status"],
        "season": media["season"],
        "seasonYear": media["seasonYear"],
        "episodes": media["episodes"]["declared"],
        "episodesAvailable": media["episodes"]["available"],
        "score": media["score"]["value"] if media["score"] else None,
        "popularity": media["popularity"],
        "genres": media["genres"],
        "isAdult": media["isAdult"],
        "visibility": media["visibility"],
        "poster": (
            {"url": poster["url"], "source": poster["source"], "color": poster.get("color")}
            if poster
            else None
        ),
    }


def search_names(media: dict) -> list[str]:
    values = [
        media["titles"]["english"],
        media["titles"]["romaji"],
        media["titles"]["native"],
        *(item["value"] for item in media["titles"]["synonyms"]),
    ]
    return unique_keep_order(
        name for name in (normalize_name(value) for value in values if value) if name
    )


def build_episode_record(
    media_key_value: str,
    rows: list[dict],
    *,
    match_confidence: str | None,
) -> dict:
    episodes = []
    for row in rows:
        number = row.get("number")
        if number is None:
            continue
        number = int(number)
        if float(row.get("number")) != number:
            raise ValueError(
                f"{media_key_value}: non-integral episode number {row.get('number')!r}"
            )
        still_url = row.get("still")
        episodes.append(
            {
                "number": number,
                "title": row.get("title"),
                "synopsis": row.get("overview"),
                "airDate": row.get("air_date") or None,
                "runtimeMinutes": row.get("runtime"),
                "rating": row.get("rating"),
                "still": (
                    {"url": still_url, "source": image_source(still_url)}
                    if still_url
                    else None
                ),
                "source": "tmdb",
            }
        )
    episodes.sort(key=lambda item: item["number"])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mediaKey": media_key_value,
        "kind": "ANIME",
        "availability": "AVAILABLE" if episodes else "NO_CONFIDENT_MATCH",
        "numbering": "position",
        "episodes": episodes,
        "provenance": {
            "source": "tmdb+anizip",
            "match": match_confidence,
        },
    }


def title_synonyms(detail: dict, primary: Iterable[str | None]) -> list[dict]:
    """Aliases we can actually source. Never invent translations or romanization."""
    taken = {normalize_name(value) for value in primary if value}
    synonyms: list[dict] = []
    bangumi = detail.get("bangumi") or {}
    candidates: list[tuple[str, str | None, str]] = []
    if bangumi.get("name"):
        candidates.append((bangumi["name"], "ja", "bangumi"))
    if bangumi.get("name_cn"):
        candidates.append((bangumi["name_cn"], "zh", "bangumi"))
    for item in bangumi.get("search_names") or []:
        candidates.append((item, None, "bangumi"))
    for value, language, source in candidates:
        normalized = normalize_name(value)
        if not normalized or normalized in taken:
            continue
        taken.add(normalized)
        synonyms.append({"value": value, "language": language, "source": source})
    return synonyms
