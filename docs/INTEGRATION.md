# Media Index v1 integration contract

Audience: the Android and Web implementers. Pin to a **contract release ID**, not to `@main`.
This document describes what is implemented in this repository today; it is not a promise about
fields that are still `null` or marked blocked in `docs/SOURCE-POLICY.md`.

## 1. Discovery and integrity

Live (once the refresh workflow has published its first v1 release):

```
https://cdn.jsdelivr.net/gh/anilifecommunity/media-index@main/manifest.json
https://cdn.jsdelivr.net/gh/anilifecommunity/media-index@main/releases/{releaseId}/manifest.json
```

The same layout exists in `fixtures/v1/` for offline integration tests.

Pointer shape (`schema/v1/pointer.schema.json`):

```json
{
  "schemaVersion": "1.0.0",
  "contract": "anilife.media",
  "releaseId": "rel-0123456789abcdef",
  "releaseManifest": "releases/rel-0123456789abcdef/manifest.json",
  "contentHash": "sha256:…",
  "manifestSha256": "…",
  "generatedAt": "2026-11-17T00:00:00Z",
  "publishedAt": "2026-11-17T00:05:00Z",
  "counts": { "media": 20900, "episodeLists": 7446, "episodes": 159624, "relations": 0, "adult": 0 }
}
```

Client algorithm:

1. Fetch `manifest.json` with `cache: "no-cache"` and a short timeout. Keep the previous pointer if
   this fails; do not clear the catalogue.
2. Compare `releaseId`. If unchanged, stop - nothing else needs fetching.
3. Fetch the release manifest, verify `manifestSha256` matches the pointer, and check
   `schemaVersion` is a major you support.
4. Before using a media/episode file, fetch its bucket manifest and verify `sha256` and `bytes`.
   Bucket manifests are small; cache them per release.
5. Promote the new release only after the checks in step 3-4 pass for the records you use. Keep the
   previous release available for instant rollback.

`releases/{releaseId}/...` is immutable and content-addressed. Cache it indefinitely. Only
`manifest.json` is mutable. jsDelivr caches `@main` for up to twelve hours and the publisher purges
the pointer and changed paths after each commit, but a client must still tolerate a stale pointer.

## 2. Paths

| Path | Contents |
| --- | --- |
| `releases/{id}/catalog/{00..63}.json` | discovery rows, stable hash shard of `mediaKey` |
| `releases/{id}/media/{bucket}/{mediaKey}.json` | canonical detail, relations and recommendations inline |
| `releases/{id}/episodes/{bucket}/{mediaKey}.json` | episode list; only present when a confident match exists |
| `releases/{id}/search/universal/{a..z,num,other-0..7}.json` | normalised title variants for prefix search |
| `releases/{id}/ids/anilist/anime/{shard}.json` | AniList id → `mediaKey` |
| `releases/{id}/ids/mal/anime/{shard}.json` | MAL anime id → `mediaKey` |
| `releases/{id}/identity/ledger.json` | alias ledger: `mediaKey`, `kind`, `ids` |
| `releases/{id}/manifests/media/{bucket}.json` | per-file `sha256`/`bytes` for media records |
| `releases/{id}/manifests/episodes/{bucket}.json` | per-file `sha256`/`bytes` for episode records |
| `releases/{id}/catalog/home.json` | precomputed spotlight/trending/popular/topRated/season/newest/upcoming/movies snapshot rows |
| `releases/{id}/catalog/browse.json` | every catalogue row, compact, sorted for stable client filtering |
| `releases/{id}/schedule/{YYYY-MM}.json` | airing months, padded a week either side |
| `releases/{id}/dub/{index,episodes}.json` | dubbed ids and latest dubbed episode |
| `releases/{id}/filler/index.json` | filler episode numbers |
| `releases/{id}/backdrops.json` | landscape art by AniList id |
| `releases/{id}/airing.json` | titles with a scheduled next episode |
| `releases/{id}/facets.json` | genres, years, formats, statuses |
| `releases/{id}/recommendations/neighbours-v1.tsv.gz` | recommendation graph |
| `releases/{id}/skip/{shard}/{id}.json` | AniSkip candidates per title |
| `releases/{id}/sources/lili/{shard}/{id}.json` | provider stream URLs (pointers, not metadata) |

`bucket` is the first two hex characters of `sha256(mediaKey)`. `shard` for ids is
`floor(providerId / 1000)`, preserving the legacy sharding convention. Catalogue shards are
`sha256(mediaKey)[2:10] % 64`. A key never moves between shards.

`manifest.home` and `manifest.browse` pin the two compact catalogue files directly. Every
auxiliary file is listed with `sha256`/`bytes` in `manifest.aux.files`; verify it like any other
file. A `media` record carries the raw AniList-shaped `anilist` object and `seriesIds` for clients
migrating from the legacy detail, plus `trailer`, `nextAiringEpisode`, `meanScore`, `favourites`,
relation `node` cards and recommendation `card` records.

Relations are **inline** in the media record rather than a separate endpoint. At this catalogue
size they are small and every consumer that needs a relation already fetched the record; a second
file would double the tree for no benefit. This is the one intentional deviation from the proposed
endpoint list in the handoff.

## 3. Identity

- `mediaKey` for anything AniList-origin is `al-<anilistId>`. It is derived deterministically and
  is never reassigned. Existing numeric AniList ids remain valid forever.
- `kind` is `ANIME` for every catalogue record today. Relation nodes may be `ANIME`, `MANGA` or
  `UNKNOWN`; a manga node has no first-class media record yet, so `resolved` is `false` and
  `mediaKey` is `null`.
- `ids` uses explicit provider namespaces. MAL anime and MAL manga ids are not interchangeable;
  the current tree only carries `mal` for anime records.
- The alias ledger is the source of truth for ids that cannot be derived from an AniList id. Do not
  merge two records on name similarity. Ambiguous joins stay unresolved.

## 4. Field semantics

- Unknown is `null`, never `0`, `""` or a fabricated value. `titles.english`/`native` being `null`
  means the source did not state it.
- `isAdult` is `true`, `false` or `null`. `visibility` is the transport-level answer:
  - `general` - source explicitly says not adult;
  - `adult` - source explicitly says adult;
  - `unknown-conservative` - **treat as potentially adult** in suggestions, search and home rails.
    Do not infer safety from a missing `Hentai` genre.
- `synopsis.text` is plain text with markup removed. `language` is `null` when the source does not
  state one; do not label it English by assumption.
- `episodes.declared` is the source episode count. `episodes.available` is `false` when no confident
  episode match exists. No episode file is written in that case - that is an answer, not a failure.
- Episode `number` is consumer-visible position, renumbered from 1 per the existing Konoha rule. Raw
  TMDB season/number is not in the published tree today; it is a documented omission, not a
  silently copied value. Never relabel a viewer's progress from this field.
- `relations[].relationType` is the provider's directed edge type (`ADAPTATION`, `PREQUEL`,
  `SEQUEL`, `SIDE_STORY`, `SUMMARY`, …). `kind` is the related record's media kind.
- Images are references with `source`, `kind`, `permission: "reference-only"` and attribution.
  There is no guaranteed offline mirror. Supply a local placeholder when a host fails; never imply
  the URL is owned by Anilife.
- `provenance.source` names where a record came from. The **release** carries the snapshot time in
  `generatedAt` and `sources[].lastUpdated`; per-record `updatedAt` is omitted because the current
  sources do not expose a reliable per-record timestamp, and inventing one would be dishonest.
  Dynamic rankings are snapshot ranks.

## 5. Search

Search buckets contain normalised names: compatibility-normalised, case-folded, Latin diacritics
stripped, Japanese kana preserved, whitespace collapsed. Latin titles bucket by first letter, digit
titles by `num`, everything else by one of eight balanced `other-*` buckets.

Recommended client behaviour:

1. Map the query's first character to one bucket.
2. Fetch that bucket once and cache it per release.
3. Match prefix first, then substring within the bucket; rank exact title, romaji, English, native,
   then alias.
4. Apply the adult filter to `visibility`, including `unknown-conservative` when the viewer's
   setting requires it.

Do not download all buckets per keystroke. Do not call a provider API for a query that a local
bucket can answer.

## 6. Fallback and degradation

| State | Condition | Client behaviour |
| --- | --- | --- |
| `LIVE` | provider works and freshness accepted | normal path |
| `INDEX` | provider down/429/5xx; verified release fetched | serve the release with provenance |
| `LOCAL` | remote release unavailable | last verified on-device/browser snapshot |
| `UNAVAILABLE` | no valid data | actionable empty/error state |

Never bypass adult filters, permissions or availability rules when falling back. A metadata cache
is not an account-sync backend. A first-time browser has no offline data; do not pretend otherwise.

## 7. Validation and budgets

`python scripts/validate_release.py --root <out> --schemas` verifies manifests, every hash, counts,
the content hash and the pointer. Clients should implement the same checks, at minimum for the
files they consume.

Payload budgets are enforced by the catalogue design, not by trust. Measured on the 2026-11-17
staging release (20,900 titles, 7,197 episode lists, 159,624 episodes):

| File | Count | Largest | Average |
| --- | --- | --- | --- |
| `catalog/{shard}.json` | 64 | 210 KB | 190 KB |
| `search/universal/{bucket}.json` | 35 | 447 KB | 174 KB |
| `media/{bucket}/{key}.json` | 20,900 | 26.6 KB | 2.8 KB |
| `episodes/{bucket}/{key}.json` | 7,197 | 707 KB | 7.5 KB |
| `manifests/media/{bucket}.json` | 256 | 16 KB | 11.5 KB |
| release manifest | 1 | 104 KB | 104 KB |
| identity ledger | 1 | 1.5 MB | 1.5 MB |

The whole release is 28,922 files / ~131 MiB. Never fetch it on startup. Fetch the pointer, the
release manifest, the bucket manifest for the record you need, then the record. Cache releases by
`releaseId`; they never change.

A committed, self-consistent sample is in [`fixtures/v1/`](../fixtures/v1/README.md); CI validates
it with the same command.

## 8. Compatibility and migration

- Legacy paths stay available: `/data/index.json`, `/data/anime/{floor(id/1000)}/{id}/index.json`,
  `/data/anime/{floor(id/1000)}/{id}/episodes.json`, `/data/mappings/mal/...`, `/data/schedule/...`,
  `/data/recs/neighbours-v1.tsv.gz`. They are generated from the same snapshot and tested.
- During migration, resolve an existing numeric AniList id to `al-<id>`; do not rewrite user
  history, list ids, progress or deep links.
- Bump the schema **major** for a breaking change, publish a migration guide and keep the previous
  major readable until both clients have shipped. Never change the meaning of an existing field.
- Rollback: the previous release remains on disk (retention is two by default). `python
  scripts/rollback_release.py --root <out> --release previous` verifies it and swaps the pointer
  atomically; clients that already verified the newer release keep working from their cache.

## 9. Known omissions at this release

- No first-class manga catalogue, characters/staff or localized synopses beyond the Bangumi
  aliases present in anime detail. Trailers are carried as AniList references.
- Account login, watchlist mutations and progress sync are **not** mirrored. Keep local state and
  degrade explicitly when AniList is unreachable.
- Profile avatars are not mirrored; keep a bundled default set or persist the last successful list.
- TMDB and TVDB ids in v1 identify the series, not a season. Per-season TVDB numbering remains in
  the legacy `data/id-map.json` (`tvdb_season`) until it is added to a v1 minor version.
- Synonyms come only from source-stated AniList/Bangumi names; no translation or romanisation is
  invented.
- Episode raw source ordinals and season numbers are not exposed.
- No binary artwork mirror, no offline guarantee for third-party image hosts.
- The existing source scope is owner-approved (see `docs/SOURCE-POLICY.md`); expansion is blocked.
  `fixtures/v1/` is a truncated sample, not a production release.

## 10. Required attribution

Display the source attribution for any metadata or artwork shown: AniList, TMDB ("This product uses
the TMDB API but is not endorsed or certified by TMDB"), Bangumi and AniZip where their fields are
used. Keep the attribution text in the app's about/licenses screen and next to imagery where the
provider requires it.
