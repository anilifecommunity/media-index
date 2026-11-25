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

Never store different kinds under one unqualified key/path. Storage, caches, sync and progress must include kind; unit progress additionally includes the stable unit ID. Layout and local library visibility settings do not become cloud-portable merely because these identities exist.

Run `python scripts/test_media_identity_v2.py`. It validates schemas offline, exact hashes/keys, namespace collisions, source isolation, unknown novel format, malformed IDs, unverified bindings and ledger reassignment. Typed detail/unit/snapshot schemas and publication are subsequent M01 tasks; their absence is not a deployed compatibility claim.
