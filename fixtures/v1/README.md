# v1 consumer fixtures

A tiny, **self-consistent** release built from the committed tree with:

```bash
python scripts/build_release.py \
  --out build/fixtures \
  --limit 5 \
  --publish \
  --generated-at 2026-11-17T00:00:00Z \
  --published-at 2026-11-17T00:00:00Z
```

It contains the first five AniList ids (Cowboy Bebop and neighbours), four episode lists and the
same manifest/pointer/bucket-manifest layout as a full release:

```
manifest.json
releases/rel-1394a0a5048fe3f8/
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
- Records carry `provenance.source`; the release manifest carries `generatedAt` and per-source
  `lastUpdated`. There is deliberately no volatile per-record timestamp.
- Source rights are owner-approved for the existing scope. See `docs/SOURCE-POLICY.md`.
- Do not edit these files by hand. Rebuild them with the command above when the schema changes.
