# Changelog

## v1 full client parity - 2026-11-17

### Added

- `catalog/home.json` (spotlight/trending/popular/topRated/season/newest/upcoming/movies) and
  `catalog/browse.json` (all titles, compact) so a cold client has a home and searchable catalogue.
- Full detail parity: raw `anilist` record, `seriesIds`, relation `node` cards, recommendation
  `card` records, `trailer`, `nextAiringEpisode`, `meanScore`, `favourites`.
- Auxiliary surfaces in the release: `schedule/`, `dub/`, `filler/`, `backdrops.json`,
  `airing.json`, `facets.json`, `recommendations/`, `skip/`, `sources/lili/`, each hashed in
  `manifest.aux.files`.
- `docs/CLIENT-COVERAGE.md` with the verified Android/Web consumption matrix.
- Per-repo migration packs written to each client's gitignored `.private` directory.

## v1 publication wiring - 2026-11-17

### Added

- The refresh workflow now builds the v1 release from the freshly emitted tree and commits
  `releases/rel-<content-hash>/` plus the atomic `manifest.json` alongside `data/`. Retention is
  two releases; only the pointer is purged on jsDelivr.
- `permissionReference` is recorded in the release manifest's source status.
- Freshly emitted records no longer carry a volatile per-record build timestamp. `provenance.source`
  stays; the release manifest carries `generatedAt` and per-source `lastUpdated`. This keeps an
  unchanged catalogue byte-identical so the content-addressed release is reused.

### Changed

- The project owner approved the existing AniList/TMDB/AniZip/Bangumi/Fribb fields and cadence on
  2026-11-17 (PR #1). `policy/source-rights.json` is `verified`/`permitted` for that scope and the
  repository variable `SOURCE_RIGHTS_APPROVED=true` is set. Expansion, artwork mirroring, MAL user
  data, manga catalogue, characters and trailers remain blocked.

## v1 contract - staging, 2026-11-17

No legacy `/data/` path changes. Existing Android/Web builds keep working.

### Added

- Versioned JSON Schemas under `schema/v1/` for media, catalogue shards, episodes, search,
  release manifests, bucket manifests, the pointer and source rights.
- Content-addressed v1 release pipeline:
  - `scripts/build_release.py` - builds `releases/rel-<content-hash>/` and an atomic `manifest.json`;
  - `scripts/validate_release.py` - verifies every hash, size, count and the pointer;
  - `scripts/rollback_release.py` - verifies and atomically points back to a retained release;
  - `scripts/release_lib.py` - deterministic keys, buckets, normalisation and record builders.
- Stable `mediaKey` (`al-<anilistId>`), alias ledger, typed anime/manga relation edges, explicit
  `visibility` including `unknown-conservative` for a missing adult flag.
- Parent-directed search buckets for English, romaji, native and source-stated aliases.
- `scripts/publish_health.py` and `scripts/audit_dataset.py` with reproducible baseline evidence in
  `docs/AUDIT-BASELINE.md`.
- Per-source freshness stamps in `data/sync-status.json` (additive `schema: 2` fields).
- `docs/INTEGRATION.md`, `docs/SOURCE-POLICY.md`, `docs/OPERATIONS.md`.

### Changed

- The refresh workflow is now policy-gated: it collects nothing until the repository variable
  `SOURCE_RIGHTS_APPROVED=true` and every source is `verified`/`permitted` in
  `policy/source-rights.json`.
- A failed or incomplete build cannot commit over the last known good tree; the pre-commit health
  check runs after emit.
- Scheduled failures open/update a GitHub issue. Issues were enabled on the repository for this.
- README now points at `anilifecommunity/media-index` instead of the stale owner name.

### Fixed

- Workflow registration: the repository was restored from a snapshot and GitHub had no workflow
  records. Pushing this change to the default branch re-indexes `.github/workflows/`; see
  `docs/OPERATIONS.md` if the list is empty again.

### Blocked

- Real publication: every source is `unverified`. The dataset remains served as-is. See
  `docs/SOURCE-POLICY.md` before setting the approval variable.
