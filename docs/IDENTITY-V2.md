# Typed media identity for Anilife 2.0.0

This is the development identity contract. It does not publish a v2 dataset or change the root v1 manifest. Consumers use the committed schema and shared golden fixture bytes from the same revision.

Identity is the pair `(kind, mediaKey)`. Kinds are ANIME, MOVIE, TV, MANGA, COMIC and NOVEL. An anime film stays ANIME with format MOVIE. AniList-origin anime/reading keeps `al-ID`; TMDB general video uses `tmdb-movie-ID` or `tmdb-tv-ID`. Numeric 42 in another namespace or kind does not identify the same media. Numeric aliases stay positive JSON-safe integers; IMDb aliases stay `tt...` strings.

External aliases are scoped to `anilist:anime`, `anilist:manga`, `mal:anime`, `mal:manga`, `tmdb:movie`, `tmdb:tv` or `imdb`. Each has explicit verification and source provenance. An unverified title match may be displayed as unresolved but cannot bind the alias ledger or authorize a tracker write. Canonical keys require their exact verified origin alias. Preserve additional verified old/merged aliases without reassigning the existing key.

For source-only media, `sourceRef` contains engine, repositoryId, providerId, stableItemId and provenance. The item identity is a stable nonsecret provider ID/path. Extract stable paths from source detail URLs before constructing it; HTTP URLs, query/fragment/userinfo, whitespace and control characters are rejected. Never use a playback URL, request token, cookie or secret query as identity.

The exact source key algorithm is:

1. Construct `[engine, repositoryId, providerId, kind, stableItemId]` in that order.
2. Serialize the array as compact JSON, UTF-8, with literal Unicode and no whitespace/BOM/newline. Do not trim, case-fold, normalize Unicode or escape non-ASCII characters. JSON string escaping remains standard.
3. SHA-256 the bytes; use all 64 lowercase hex digits after `src-`.

`fixtures/v2/identity-vectors.json` contains all six kinds, overlapping numeric IDs, source-only comics/novels, non-ASCII bytes and same-provider movie/TV collision cases. Android and Web must run these exact vectors. `scripts/media_identity_v2.py` implements the semantic checks; `schema/v2/media-ref.schema.json` checks structure. Apply both checks at ingestion; a schema alone cannot verify that a hash or canonical key matches its fields.

Known AniList format NOVEL projects legacy `(MANGA, al-ID)` to `(NOVEL, al-ID)` using the same `anilist:manga` alias. The fixture declares that projection explicitly. Apply it once during the client's transactional legacy migration before populating its new alias ledger; move the existing reading state to that identity instead of creating another book. A missing/unknown AniList reading format remains unresolved, rather than guessing MANGA or NOVEL.

`alias-ledger.schema.json` describes append-only verified external and source bindings. `append_alias_ledger` rejects reassignment of an existing binding and keeps the first evidence. A verified source-to-canonical binding points to the canonical `(kind, mediaKey)` without renaming/removing the original source key; consumers retain that source identity as an alias so old local state stays reachable. Unknown/ambiguous mappings stay unbound. Changing a verified binding requires a separate explicit correction/migration contract, never silent overwrite.

The ledger's optional `unresolvedAliases` array quarantines conflicting current claims. Each entry contains an unverified alias with provenance, a reason (`ambiguous`, `changed` or `unverified`) and 1–32 distinct qualified candidates. A historical binding remains in `bindings` even when new evidence contests it; its target must also remain among the candidates. **Unresolved entries override historical bindings for lookup, progress merges and tracker writes.** An absent `unresolvedAliases` array means none are quarantined.

`reconcile_alias_ledger(previous, refs)` combines a complete current set of reference claims with the previous verified ledger. It never chooses a first or highest-scoring winner. Multiple targets are ambiguous, a sole new target different from the historical binding is changed, and unverified claims cannot bind. Missing records do not clear old unresolved evidence. A unique verified claim can clear quarantine only when it agrees with any historical target. Source-to-canonical grants remain explicit inputs to `append_alias_ledger`; source identity alone does not prove that mapping.

Before publishing records, `apply_alias_ledger(refs, ledger)` downgrades contested external aliases to `verified: false`, preserving every media key and leaving source-only content usable. A dispute about a canonical origin itself fails validation and publication; it cannot manufacture a valid canonical record by dropping its required verified origin. Consumers check both the current reference's verification and the ledger quarantine before joining or writing. `fixtures/v2/alias-conflict-vectors.json` is the shared Android/Web regression for two legacy-map claims to MAL 17295; those competing claims are inputs, not a verified unique mapping.

The v1 adapter does not treat an integer in `ids.mal` as direct AniList evidence. It retains that alias as unverified with `legacy-v1-cross-reference` provenance unless the optional raw AniList object contains the same typed AniList ID and MAL ID. A source-rights approval or a uniqueness check alone does not verify an individual cross-reference. The publisher can use eligible raw source evidence, then must still reconcile collisions before materializing records.

Never store different kinds under one unqualified key/path. Storage, caches, sync and progress must include kind; unit progress additionally includes the stable unit ID. Layout and local library visibility settings do not become cloud-portable merely because these identities exist.

Run `python scripts/test_media_identity_v2.py` and `python scripts/test_media_contract_v2.py`. They validate schemas offline, exact hashes/keys, namespace collisions, source isolation, unknown novel format, malformed IDs, unverified bindings, ledger reassignment, quarantine and lossless projection. The typed wire schemas exist in this development branch; immutable contract and dataset publication remain separate gates.
