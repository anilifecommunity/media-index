# Source rights and collection policy

**Status: owner-approved for the existing daily scope (2026-11-17). Expansion remains blocked.**

The project owner approved the current fields and cadence on 2026-11-17 (PR #1). This is an owner
attestation recorded in `policy/source-rights.json`, not a provider licence: provider terms still
apply, and the owner accepted the existing scope. Anything outside it needs a new review.

The repository can serve the data it holds, generate schemas, build releases and run tests. It must
not expand automated collection, increase cadence or mirror artwork without a new recorded
decision.

## Current decision

| Source | What the tree stores | Rights status | Collection in CI |
| --- | --- | --- | --- |
| AniList | titles, ids, synopsis, format, dates, genres, tags, scores, popularity, studios, relation edges, recommendations, image **URLs** | verified (owner) | on |
| TMDB | episode titles, overviews, air dates, still **URLs**, logo and backdrop **URLs** | verified (owner) | on |
| AniZip | episode ratings, logo/backdrop **URLs** | verified (owner) | on |
| Bangumi | Chinese titles, aliases, subject ids | verified (owner) | on |
| Fribb | cross-provider ids | verified (owner) | on |
| User-supplied lili stream URLs | provider metadata used by the player | out of scope for this contract | unchanged |

Binary artwork is **not** mirrored. Every image in the dataset is a reference (`permission:
"reference-only"`) to a third-party host. A URL is a pointer, not a redistribution grant.

## Gate

Two independent switches must agree:

1. `policy/source-rights.json` - `status: "verified"` **and** `permitted: true` for every source
   whose data is in the release.
2. Repository variable `SOURCE_RIGHTS_APPROVED=true`.

Both were set on 2026-11-17 for the existing scope. The gate stays in code so a future expansion, a
provider request or a lost approval can stop collection in one audited place.

`scripts/build_release.py --publish` refuses to move the pointer while any source is unverified
unless `--allow-unverified-sources` is passed for a staging demonstration. The refresh workflow
skips collection entirely when the repository variable is absent and reports `blocked` instead of
failing.

## How to change the scope

For each provider, record all of the following before changing its status:

- the exact terms/API document URL and the date reviewed;
- the permission reference (ticket, email subject, contract id) - **never** the confidential
  correspondence or credentials themselves, and never a secret in this public repository;
- permitted fields and operations;
- storage/cache duration and deletion/takedown obligations;
- attribution and commercial-use constraints;
- rate limit and required backoff behaviour.

Then update `policy/source-rights.json`, renew the review date, run
`python scripts/test_release.py`, and only afterwards set `SOURCE_RIGHTS_APPROVED`.

## What remains blocked

- Any new source, new field or increased cadence beyond the approved existing scope.
- Bulk AniList walks beyond the existing daily scope, and any "mirror everything" backfill.
- MAL user lists, profiles, credentials or write proxying. MAL is used only to label its own
  provider ids in the alias ledger.
- TMDB artwork mirroring. TMDB attribution is required in both clients, but attribution does not
  grant ownership of the underlying images.
- Manga catalogue ingestion beyond the relation nodes already present in anime detail records.
- Character/staff ingestion, trailers, and voice-credit data.

## Freshness SLOs

| Data | SLO | Meaning |
| --- | --- | --- |
| catalogue / detail | 72 h | `data/sync-status.json.last_updated` |
| airing schedule | 24 h | `data/schedule/{YYYY-MM}.json` rewritten for the forward window |
| episode lists | 72 h for airing titles | finished titles are intentionally not re-fetched daily |
| recommendation graph | 7 days | published graph is a snapshot, not a live rank |

`scripts/publish_health.py` reports `stale` past the SLO and the refresh workflow alerts through a
GitHub issue on repeated failure. A successful no-op is distinct from a failed run: the commit step
sets `changed=false` and the health summary records it.

## Serving and takedown

Existing committed data is served under the approved scope. If a source requires removal or a new
provider request changes the terms:

1. remove the affected generator step or fields;
2. rebuild the compatibility tree and v1 release without them;
3. purge the changed jsDelivr paths (the workflow does this automatically on the next commit);
4. record the removal in the release notes and, where required, notify the provider.

Contact the repository owner through the GitHub issue tracker for attribution or takedown requests.
Do not open a public issue containing confidential correspondence.
