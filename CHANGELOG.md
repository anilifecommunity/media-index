# Changelog

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
