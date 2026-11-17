# Publisher operations

## What runs

`.github/workflows/refresh.yml` (schedule 05:00 UTC, manual dispatch) and
`.github/workflows/ci.yml` (push/PR checks) are the only automated paths.

Publication order and failure containment:

```
policy gate
  → checkout
  → generator tests
  → emit → recommendations → schedule → Bangumi → lili
  → build v1 release + full validation
  → audit_dataset --strict + publish_health
  → commit only if all of the above succeeded (data, releases, manifest.json)
  → purge jsDelivr paths and the v1 pointer
```

A failure at any step before **Commit** leaves the previous commit as the published tree. The
commit step is a no-op when nothing changed (`changed=false`). The health step reads the freshly
emitted tree, so a failed or incomplete build cannot overwrite the last known good data.

## Policy gate

The `policy` job checks the repository variable `SOURCE_RIGHTS_APPROVED`. Both the policy file and
the variable were approved on 2026-11-17 for the existing scope. When either is unset the `refresh`
job is skipped, the `blocked` job records the reason in the run summary, and the data stays as-is.
See `docs/SOURCE-POLICY.md` for what a new approval must record.

## Manual run

Actions → **Refresh metadata** → *Run workflow*.

- `full=true` re-fetches every title's TMDB episodes. It is expensive; use it after a matcher
  change, not routinely.
- `ids=1,20,154587` re-fetches only those AniList ids. Passed through an environment variable,
  never spliced into a shell command.

Locally:

```bash
python scripts/test_konoha_build.py
python scripts/test_recs_build.py
python scripts/test_release.py
python scripts/test_health.py
python scripts/publish_health.py --deep --markdown
```

## Health states

`scripts/publish_health.py` exits `0` ok, `1` stale, `2` failed, `3` blocked.

- **failed** - a required file is missing/invalid, catalogue counts disagree, a detail file is
  missing, or `--require-permitted` was passed while rights are unverified. Do not publish.
- **stale** - data is readable but older than the SLO. Check the run history before assuming the
  schedule is broken; a successful no-op is not a failure.
- **blocked** - collection is intentionally off because source rights are unverified.
- **ok** - fresh and internally consistent.

Repeated scheduled failures open or comment on the issue **Scheduled metadata refresh failed**
(label-free, looked up by title). Resolve the run, then close the issue; a later failure reopens
the thread. Issues must be enabled on the repository for the alert job to work.

If Actions shows **no workflows at all**, the workflow registry is stale (this repository was
restored from a snapshot after its remote was lost). Push a commit that touches
`.github/workflows/` to the default branch and confirm the workflow appears in
`gh workflow list`; a schedule-only workflow cannot be dispatched until GitHub has indexed it.

## Release build and rollback

The workflow builds the v1 release from the freshly emitted legacy tree and commits it with the
data:

```bash
python scripts/build_release.py --out . --prune-keep 2
python scripts/validate_release.py --root .
```

`manifest.json` is the only mutable file; `releases/rel-<content-hash>/` is immutable. A release
whose content hash is unchanged is reused, so an idle day adds no files and no new directory.
Retention 2 keeps the current and previous release; older directories are removed from the working
tree (their Git objects may remain in history).

Manual staging, safe and gitignored:

```bash
python scripts/build_release.py --out build/v1 --publish --allow-unverified-sources
python scripts/validate_release.py --root build/v1 --schemas
python scripts/rollback_release.py --root build/v1 --list
python scripts/rollback_release.py --root build/v1 --release previous
```

`--publish` writes the pointer atomically. Rollback fully verifies the target release before
writing the pointer, so a corrupt or partial release cannot become current.

### Repository size

Measured 2026-11-17: 28,922 files / ~131 MiB per release (20,900 media, 7,197 episode lists). With
retention 2 the working tree is legacy data plus two releases (~108k files). Git deduplicates
unchanged blobs, so daily growth is changed files plus tree entries; monitor `git count-objects
-vH` and checkout time. If the repository budget is exceeded, move `releases/` to Cloudflare R2 or
an orphan data branch and keep only `manifest.json` in `main`.

Do not silently move 50k per-title files between layouts without that measurement.

## Change checklist

- [ ] generator tests and release contract tests pass;
- [ ] `audit_dataset.py --strict` passes;
- [ ] `publish_health.py --deep` is `ok` in the emitted tree;
- [ ] a staging release builds and fully verifies, including schema validation;
- [ ] rollback to the previous release was rehearsed;
- [ ] legacy `/data/` paths still parse and are unchanged in shape;
- [ ] source-rights status is unchanged or explicitly reviewed;
- [ ] integration notes updated for the app teams.

## Known gaps (tracked, not silently skipped)

| Gap | Reason / next step |
| --- | --- |
| Real publication is blocked | all sources are `unverified`; owner must record permission (P0 policy gate) |
| No per-provider 429/failure counters in the committed status | generator prints and backs off, but does not persist counters; add a run report if publication resumes |
| Manga catalogue is relation-only | the published tree contains manga nodes, not full manga records |
| Character/staff, trailers, localized synopsis | not licensed/verified; out of scope until rights are recorded |
| Artwork is reference-only | mirroring requires affirmative rights; no binary mirror is built |
| Episode raw source ordinal | not present in the published tree; positions are consumer-visible numbering only |
| GitHub large-tree budget unmeasured at release scale | see the cost guardrail above |
