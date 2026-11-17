# v1 consumer fixtures

A tiny, **self-consistent** release built from the committed tree with:

```bash
python scripts/build_release.py \
  --out build/fixtures \
  --limit 5 \
  --publish \
  --allow-unverified-sources \
  --generated-at 2026-11-17T00:00:00Z \
  --published-at 2026-11-17T00:00:00Z
```

It contains the first five AniList ids (Cowboy Bebop and neighbours), four episode lists and the
same manifest/pointer/bucket-manifest layout as a full release:

```
manifest.json
releases/rel-10d0b9b9c84f4a0e/
  manifest.json
  catalog/{00..63}.json      # only non-empty shards
  search/universal/*.json
  media/{bucket}/al-*.json
  episodes/{bucket}/al-*.json
  ids/anilist/anime/*.json
  ids/mal/anime/*.json
  identity/ledger.json
  manifests/{media,episodes}/*.json
```

Verify it exactly as a client would:

```bash
python scripts/validate_release.py --root fixtures/v1 --schemas
```

Notes for consumers:

- This is a **fixture, not a production release**. It is truncated, so relation and recommendation
  edges outside the first five ids are `resolved: false`. Do not infer catalogue completeness from
  its counts.
- Media keys are `al-<anilistId>`; paths and hashes are real.
- Source rights are unverified. `--allow-unverified-sources` only allowed this staging build; it is
  not a publication approval. See `docs/SOURCE-POLICY.md`.
- Do not edit these files by hand. Rebuild them with the command above when the schema changes.
