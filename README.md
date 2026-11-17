# media-index

Static anime metadata — title details, episode lists, and cross-database id mapping — aggregated
from [AniList](https://anilist.co) and [TMDB](https://www.themoviedb.org), served over the jsDelivr
CDN with no server-side logic.

Rebuilt daily by a GitHub Action under the owner-approved source scope (see
[`docs/SOURCE-POLICY.md`](docs/SOURCE-POLICY.md)). 20,925 titles and 159,808 episode records.

## Data access

```
https://cdn.jsdelivr.net/gh/anilifecommunity/media-index@main/data
```

Renamed from `anilili-metadata` on 2026-09-21. The old URL still resolves - GitHub redirects a
renamed repository and jsDelivr follows the redirect - so anything already pointing at it keeps
working, but new consumers should use the name above.

The `data/` paths below are the **legacy compatibility contract**. They stay readable while the
Android and Web apps migrate to the versioned v1 contract in [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

| File | Contents |
| --- | --- |
| `index.json` | Flat catalogue of every title — id, title, poster, year, status, format, episode count, score, popularity, genres |
| `id-map.json` | AniList id → TMDB / MAL / Kitsu / AniDB / Simkl |
| `airing.json` | Titles with a scheduled next episode |
| `genres.json`, `years.json` | Distinct values, for building filters |
| `stats.json` | Totals by format and status, plus `last_updated` |
| `sync-status.json` | What generated the tree and when |
| `anime/{shard}/{id}/index.json` | Full detail for one title |
| `anime/{shard}/{id}/episodes.json` | Episode titles, overviews, air dates, stills, runtimes |
| `mappings/mal/{shard}/{malId}.json` | MyAnimeList id → AniList id |

`shard` is `Math.floor(id / 1000)` — for per-title files it shards on the AniList id, for the MAL
mappings on the MyAnimeList id.

```javascript
const BASE = "https://cdn.jsdelivr.net/gh/anilifecommunity/media-index@main/data";

const catalog = await fetch(`${BASE}/index.json`).then(r => r.json());

const detailUrl = id => `${BASE}/anime/${Math.floor(id / 1000)}/${id}/index.json`;
const episodeUrl = id => `${BASE}/anime/${Math.floor(id / 1000)}/${id}/episodes.json`;

const episodes = await fetch(episodeUrl(171018)).then(r => r.json()); // DAN DA DAN
```

## Versioned contract (v1)

Schema v1 is generated **alongside** the legacy tree, from the same committed data, so no existing
consumer breaks while the apps migrate:

| Path | Purpose |
| --- | --- |
| `schema/v1/*.schema.json` | JSON Schema for media, catalogue, episodes, search, manifests and source rights |
| `releases/{releaseId}/manifest.json` | immutable release description: counts, sources, per-file hashes, bucket manifests |
| `releases/{releaseId}/media/{bucket}/{mediaKey}.json` | canonical detail record, typed relations, provenance |
| `releases/{releaseId}/episodes/{bucket}/{mediaKey}.json` | position-numbered episodes or an explicit missing-match state |
| `releases/{releaseId}/catalog/{shard}.json` | bounded discovery rows (64 stable hash shards) |
| `releases/{releaseId}/catalog/home.json` | precomputed home rows (snapshot ranks) |
| `releases/{releaseId}/catalog/browse.json` | every title, compact, for client-side search/filter |
| `releases/{releaseId}/search/universal/{bucket}.json` | normalised English/romaji/native/alias search buckets |
| `releases/{releaseId}/schedule/`, `dub/`, `filler/`, `skip/`, `sources/lili/` | the auxiliary surfaces the apps already read, copied and hashed |
| `manifest.json` | the only mutable file: an atomic pointer to the current release |

`mediaKey` is `al-<anilistId>` for AniList-origin records. It is derived from the provider id, never
reassigned, and the alias ledger (`releases/{releaseId}/identity/ledger.json`) is the authority for
any future non-AniList key. A release id is `rel-<first 16 hex of the content hash>`, so an unchanged
catalogue reuses the same release instead of rewriting files.

The refresh workflow builds this tree with the data and commits `releases/` plus `manifest.json`.
Only the pointer is mutable; release directories are immutable and safe to cache forever. The
previous release is retained for rollback.

Build and verify a staging release (safe; does not publish):

```bash
python scripts/build_release.py --out build/v1 --publish --allow-unverified-sources
python scripts/validate_release.py --root build/v1 --schemas
python scripts/rollback_release.py --root build/v1 --release previous
```

`--publish` refuses to swap the pointer while any source in `policy/source-rights.json` is
unverified. `--allow-unverified-sources` is for staging demonstrations only. See
[`docs/INTEGRATION.md`](docs/INTEGRATION.md) for consumer rules and
[`docs/SOURCE-POLICY.md`](docs/SOURCE-POLICY.md) for the rights gate.

## Two things worth knowing before you rely on it

**Episodes are numbered by position, not by TMDB's `episode_number`.** TMDB keeps some multi-season
runs as one long season — Dandadan's two seasons as a single season of 24, Re:Zero's four as one of
85 — and numbers the second season 13..24 where AniList, the streaming providers and viewers all
call them 1..12. Each title's `episodes.json` is renumbered from 1 so it lines up with everything
else.

**A missing `episodes.json` is an answer, not a gap.** It means no TMDB record could be matched to
that AniList entry with enough confidence to publish. That is deliberate: a wrong match does not
show up as a missing thumbnail, it shows up as another show's episodes illustrating this one. An
unaired sequel gets no episode list rather than its predecessor's.

Where an episode count is known, it is binding — every title with an AniList episode count has
exactly that many episodes here.

## Rebuilding

```bash
pip install -r scripts/requirements.txt
python scripts/konoha_build.py catalog          # walk AniList, ~25 min
python scripts/konoha_build.py episodes         # TMDB episode lists, ~20 min
python scripts/konoha_build.py emit --out data
```

`episodes` needs a TMDB v4 read token in `TMDB_READ_TOKEN`. Run the checks before committing:

```bash
python scripts/test_konoha_build.py
python scripts/test_recs_build.py
python scripts/test_release.py
python scripts/test_health.py
python scripts/audit_dataset.py --strict
python scripts/publish_health.py --deep
```

The daily workflow only re-asks TMDB about titles that can still change. Use the **full** input on
a manual run to rebuild everything.

The workflow will not collect anything until the repository variable `SOURCE_RIGHTS_APPROVED` is
`true`. Without it the publish job is skipped, the last known good tree stays current, and the run
reports `blocked` in its summary. That is deliberate: see `docs/SOURCE-POLICY.md`.

## Notes

Not affiliated with AniList or TMDB. This product uses the TMDB API but is not endorsed or
certified by TMDB. Metadata belongs to its respective sources; this repository is a cache.

The MIT-0 licence covers this repository's code and its own contributions. It does not relicense
AniList, MAL, TMDB, Bangumi or AniZip data, nor any studio artwork. Sources are unverified until
permission is recorded in `policy/source-rights.json`; an unverified status is not permission.
