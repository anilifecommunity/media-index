# Client consumption and v1 coverage

Audited 2026-11-17 against the actual client sources:

- Android: `C:\Users\User\Documents\ChatGPT\anilili-android-and-tv`
- Web: `C:\Users\User\Documents\OpenCode\AnilifeWeb\web`

Every claim below points at the file that makes the request. This is a read-only audit; no client
code was changed.

Per-repo migration packs (gitignored, not committed):

- `C:\Users\User\Documents\ChatGPT\anilili-android-and-tv\.private\media-index-v1-handoff-2026-11-17.zip`
- `C:\Users\User\Documents\OpenCode\AnilifeWeb\web\.private\media-index-v1-handoff-2026-11-17.zip`

## Android

| Surface | Source | Fields / behaviour | Fallback |
| --- | --- | --- | --- |
| Catalogue | `data/index.json` (bundled asset + `MetadataRefresh`) | id, title, poster, colour, year, status, format, episodes, score, popularity, genres | `LocalCatalog` bundled snapshot |
| Id map | `data/id-map.json` | MAL, TMDB (+type), TVDB (+season), Kitsu, AniDB, Simkl, confidence | bundled asset |
| Detail | `data/anime/{shard}/{id}/index.json` | `KonohaDetail`: ids, titles, format, status, season/year, episodes, duration, description, genres, score, popularity, images, bangumi aliases, **full raw `anilist` Media**, `series`, `recommendations` | live AniList → settled raw record → thin detail → bundled row → error |
| Episodes | `data/anime/{shard}/{id}/episodes.json` | number, title, overview, air date, still, runtime, rating | empty list / AniList episode count |
| Schedule | `data/schedule/{YYYY-MM}.json` | id, episode, airingAt, three titles, cover, format, year, adult | live AniList |
| Dub | `data/dub-index.json`, `data/dub-episodes.json` | dubbed ids, latest dubbed episode | last persisted copy |
| Filler | `data/filler-index.json` | id → filler episode numbers | MAL |
| Skip | `data/skip/{shard}/{id}.json` | per-episode AniSkip candidates | AniSkip live |
| Backdrops | `data/backdrops.json` | id → landscape URL | AniZip/TMDB live |
| Recommendations | `data/recs/neighbours-v1.tsv.gz` + detail `recommendations` | graph + cards | live AniList |
| MAL mapping | `data/mappings/mal/{shard}/{malId}.json` | MAL → AniList | live/search |
| Provider URLs | `data/anime/{shard}/{id}/lili.json` | per-episode XFDM URLs | resolve live |
| Profile avatars | live AniList `popularCharacters()` | name + portrait | last persisted list; empty on a fresh install with AniList down |

The Android fallback chain is explicit in `MiruroRepository.liveAnimeInfo`: live AniList →
`konoha.details(id)?.anilist` (full record) → `konoha.details(id)?.toMedia` (thin) →
`localCatalog.media(id)` → throw. Home/search/discover have `LocalCatalog` fallbacks
(`offlineHomeCollections`, `localCatalog.discover`, `titleSuggestions`).

## Web

| Surface | Source | Fields / behaviour | Fallback |
| --- | --- | --- | --- |
| Home rows | live AniList (`fetchTrendingAnime`, `fetchPopularSeasonAnime`, `fetchTopRatedAnime`, `fetchPopularAllTimeAnime`) | title, cover, banner, description, score, popularity, format, episodes, status, season, genres, duration, studio, next airing | `localStorage` live-catalog cache; **empty on a cold browser** |
| Browse / filters | `liveCatalog` (the four AniList pages + cached rows) | client-side format/year/score/genre filters | same cache |
| Search | live AniList `searchAniList` | anime + manga merge, synonyms | falls back to filtering `liveCatalog`; empty on a cold browser |
| Detail | selected `Anime` (from the live catalogue) + `fetchAniListMediaById` for related manga | titles, synonyms, adult, poster/banner, score, format, year, status, next episode, duration, genres, synopsis, studio, start date, season, popularity | cached catalogue row only |
| Related manga | live AniList detail relations | title variants, description, poster, format, adult | none |
| Episodes | **media-index** `anime/{shard}/{id}/episodes.json` | number, title, image/still, air date, overview, runtime, rating | AniList-synthesised episode rows |
| Schedule | live AniList `fetchAiringSchedule` | media + airingAt | **none** (shows an empty state) |
| Dub flag | **media-index** `dub-index.json` | dubbed AniList ids | unknown |
| Skip | **media-index** `skip/{shard}/{id}.json` | op/ed/recap intervals | AniSkip live |
| Backdrops | **media-index** `backdrops.json` | id → URL | none |
| Account | live AniList OAuth/list mutations | login, lists, progress | local watchlist only |

Web's only media-index reads are in `src/utils/mediaIndexApi.ts`. Everything else is
`src/utils/anilistApi.ts`, so an AniList outage currently means a blank home, dead search, an
AniList-only schedule, and no related manga for a first-time browser.

## v1 coverage after the 2026-11-17 expansion

| Surface | v1 path | Status |
| --- | --- | --- |
| Home rows | `catalog/home.json` | added (snapshot ranks) |
| Browse rows | `catalog/browse.json` (compact, all titles) | added |
| Search | `search/universal/*.json` | present |
| Detail | `media/{bucket}/{key}.json` (normalized, `seriesIds`, relation/recommendation cards; raw `anilist` optional) | expanded |
| Relation cards | `media...relations[].node` (title, poster, format, country, description, adult, episodes) | expanded |
| Recommendation cards | `media...recommendations[].card` | expanded |
| Episodes | `episodes/{bucket}/{key}.json` | present |
| Schedule | `schedule/{YYYY-MM}.json` | added (copied, hashed) |
| Dub | `dub/index.json`, `dub/episodes.json` | added |
| Filler | `filler/index.json` | added |
| Skip | `skip/{shard}/{id}.json` | added (copied, hashed) |
| Backdrops | `backdrops.json` | added |
| Airing | `airing.json` | added |
| Facets | `facets.json` | added |
| Recommendations graph | `recommendations/neighbours-v1.tsv.gz` | added |
| Provider URLs | `sources/lili/{shard}/{id}.json` | added (copied, hashed) |
| MAL mapping | `ids/mal/anime/{shard}.json` | present |
| Adult | explicit `isAdult` + `visibility` | present |
| Account features | **not mirrored** | login/watchlist writes remain live-only and must degrade explicitly |
| Profile avatars | **not mirrored** | app should keep a bundled default set or persist the last list |

## Remaining gaps to "function normally" on a first-time device

1. **Account features** cannot be mirrored (no credentials, no write proxy). The clients must keep
   local watchlist/progress and show an honest "account sync unavailable" state.
2. **Profile avatars** are cosmetic; bundle a default set or persist the last successful list.
3. **MAL metadata** (scores, rank, synopsis) is not mirrored. Only MAL IDs are. The current clients
   do not display MAL fields, so this is not a blocker unless a MAL screen is added.
4. **Characters/staff** are not in either client model today. Add a data source before adding a UI.
5. **Live ranks**: home rows and `airing.json` are snapshots. Labels must not claim live trending.
6. **Images** remain third-party references; if the image hosts are also down, clients need local
   placeholders. No binary mirror is built.

## Migration shape

1. **Web first**: replace the four AniList home fetches, search, detail and schedule with v1 reads;
   keep AniList only for OAuth and list mutations. On a cold outage the home and search then work.
2. **Android second**: keep the bundled snapshot as the last resort, but make the legacy tree
   optional by reading v1 detail (including the raw `anilist` record), episodes, schedule, dub,
   filler, skip, backdrops, recs and provider URLs from the release. The fallback chain becomes
   live AniList → v1 release → bundled snapshot.
3. **Compatibility**: the legacy `/data/` paths remain generated and readable through at least one
   full client release. Remove them only after both apps stop reading them and a rollback window has
   passed.
