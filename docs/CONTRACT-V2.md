# Anilife metadata and unit contract v2

The development schemas are `schema/v2/media-ref.schema.json`, `alias-ledger.schema.json` and `contract.schema.json`. The last file defines detail, catalogue, search, episode pages, chapter pages, franchise placement, bucket inventory, release manifest and pointer records. `recordType` selects the wire shape. Identity rules and exact cross-client hashes are in [IDENTITY-V2.md](IDENTITY-V2.md).

`fixtures/v2/record-vectors.json` provides 36 synthetic records across all six kinds, labelled as contract data. It does not claim production titles, counts or availability. Its two real finale media references demonstrate that episode 1 under AniList 146984 and episode 1 under 162314 have distinct progress identities. Android and Web use the fixtures from one pinned contract revision.

## Metadata and relation meaning

Detail records carry a full `ref`, multilingual/source-attributed titles, explicit status and adult classification, metadata/image references, typed relations, franchise placement and unit-page descriptors. Compact catalogue/search records carry a qualified `(kind, mediaKey)` target, not enough evidence to authorize a tracker write. Fetch the full identity/verified alias first.

Keep `isAdult` and `visibility` consistent: true/adult, false/general, null/unknown-conservative. Unknown fields remain null or explicitly unresolved. Image references retain their original source/attribution/permission; this contract contains no artwork bytes or playback URLs.

Relation identity confidence and snapshot hydration are separate. `confidence: verified` means the external identity/kind is source-backed; `resolved` says its detail is included in this snapshot. A verified reference may remain unresolved here. Missing AniList reading format cannot guess MANGA versus NOVEL. An unresolved identity has no media key and cannot claim resolved/verified status.

Franchise members preserve their canonical targets, display order, source season (including zero), optional absolute ordinal, role and provenance. Do not derive a progress key from display order. Membership is bounded to 16 entries; depth/size truncation or missing relation hydration stays partial. The requested detail remains a member. A legacy series list without explicit coverage stays unresolved; an adapter cannot promote it to complete.

## Units and paging

Episode/feature pages apply to ANIME/MOVIE/TV; chapter pages apply to MANGA/COMIC/NOVEL. Every unit has a stable `unitId` scoped by its qualified media target. Display ordinal is a decimal string (or null), independently of raw source ordinal, source season and absolute ordinal. Fractional chapter numbers do not identify a chapter. Keep provider-issued stable unit IDs or verified canonical IDs; never use an expiring media URL or a position that changes when a chapter is inserted.

The v1 projection retains its existing normalized `episode-N` convention within each anime identity, and leaves unavailable raw/source/absolute numbering null. It preserves titles, air dates, still references, runtime, synopsis and rating fields. V1's AVAILABLE flag means a metadata match, not a playable stream: coverage is only complete when the known declared count also matches; unit playback availability remains unknown.

Each unit page contains at most 500 units and a source offset. Catalogue/search shards contain at most 1,000 entries. Unit IDs and media targets must be unique within each page/shard. Detail metadata and unit-page coverage are independent; a failed metadata match cannot erase known franchise membership or existing local progress.

## Snapshot layout and bounds

The v2 pointer belongs at `v2/manifest.json`, independently of the root v1 pointer. It references an immutable `v2/releases/{releaseId}/manifest.json` by exact bytes/SHA256. Main manifests describe all six kinds' actual coverage, bootstrap catalogue/search/identity files and up to 256 hashed bucket inventories. Each bucket lists up to 2,048 payload file descriptors. Clients fetch inventories and payloads on demand; they do not preload the entire catalogue at launch.

All paths are canonical relative POSIX paths. Absolute paths, dot segments, backslashes, URLs and duplicate/noncanonical inventory paths are rejected. File descriptors carry exact byte counts and lowercase SHA256. Receivers must verify bytes/hash before parsing and promote a generation atomically only after its required bootstrap files verify. Retain the previous verified generation on transport/schema/integrity failure.

Hard uncompressed canonical-JSON limits are 4 KiB for pointers, 256 KiB for main manifests/detail records and 2 MiB for each payload/bucket/identity shard. A release writer must shard identity bindings rather than make one unbounded ledger. Record count and byte bounds both apply. Schema validation alone does not check digest values, cross-field identities, adult classification or binding reassignment; `media_contract_v2.validate_record` enforces those record-level semantics. Release-level traversal/hash/atomic-promotion checks belong to the publisher/reader.

`adapt_v1_media` and `adapt_v1_episodes` are pure projections. They never edit the root pointer, existing immutable releases or `/data/` paths. New production source acquisition remains governed by the existing source-rights policy; a new kind in the schema does not grant collection/redistribution permission.

Run `python scripts/test_media_contract_v2.py`, `test_media_identity_v2.py`, `test_release.py` and `test_compat.py`. The tests validate existing v1 fixture projections, exact ID scopes, source preservation, null/adult handling, fractional chapters, byte limits, duplicate/path rejection and immutable old inputs. The schemas/fixtures are development artifacts until an immutable contract publication is recorded.
