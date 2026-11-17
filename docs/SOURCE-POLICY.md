# Source rights and collection policy

**Status: implementation-blocking. All current sources are `unverified`.**

This repository can serve the data it already holds, generate schemas, build releases and run
tests. It must not expand automated collection, increase cadence or mirror artwork until the
project owner records permission for each source. `unverified` is not permission.

## Current decision

| Source | What the tree stores | Rights status | Collection in CI |
| --- | --- | --- | --- |
| AniList | titles, ids, synopsis, format, dates, genres, tags, scores, popularity, studios, relation edges, recommendations, image **URLs** | unverified | off |
| TMDB | episode titles, overviews, air dates, still **URLs**, logo and backdrop **URLs** | unverified | off |
| AniZip | episode ratings, logo/backdrop **URLs** | unverified | off |
| Bangumi | Chinese titles, aliases, subject ids | unverified | off |
| Fribb | cross-provider ids | unverified | off |
| User-supplied lili stream URLs | provider metadata used by the player | out of scope for this contract | unchanged |

Binary artwork is **not** mirrored. Every image in the dataset is a reference (`permission:
"reference-only"`) to a third-party host. A URL is a pointer, not a redistribution grant.

## Gate

Two independent switches must agree:

1. `policy/source-rights.json` - `status: "verified"` **and** `permitted: true` for every source
   whose data is in the release.
2. Repository variable `SOURCE_RIGHTS_APPROVED=true` - set only after step 1 is reviewed.

`scripts/build_release.py --publish` refuses to move the pointer while any source is unverified
unless `--allow-unverified-sources` is passed for a staging demonstration. The refresh workflow
skips collection entirely when the repository variable is absent and reports `blocked` instead of
failing.

Turning the gate on is intentionally a one-line, audited action. It is not a place to hide an
accidental collector.

## How to verify a source

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

- Bulk AniList walks beyond the existing daily scope, and any "mirror everything" backfill.
- MAL user lists, profiles, credentials or write proxying. MAL is used only to label its own
  provider ids in the alias ledger.
- TMDB artwork mirroring. TMDB attribution is required in both clients, but attribution does not
  grant ownership of the underlying images.
- Manga catalogue ingestion beyond the relation nodes already present in anime detail records.
- Character/staff ingestion, trailers, and voice-credit data.
- Increasing refresh cadence. A permitted future schedule should follow source change rate and
  rate-limit budgets, not run everything every few minutes.

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

Existing committed data may be served while rights are re-reviewed; that is a continuity decision,
not a new grant. If a source requires removal:

1. remove the affected generator step or fields;
2. rebuild the compatibility tree and v1 release without them;
3. purge the changed jsDelivr paths (the workflow does this automatically on the next commit);
4. record the removal in the release notes and, where required, notify the provider.

Contact the repository owner through the GitHub issue tracker for attribution or takedown requests.
Do not open a public issue containing confidential correspondence.
