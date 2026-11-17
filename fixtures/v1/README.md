# v1 consumer fixtures

A small, **self-consistent** release built from the committed tree with:

```bash
python scripts/build_release.py \
  --out build/fixtures \
  --limit 5 \
  --publish \
  --generated-at 2026-11-17T00:00:00Z \
  --published-at 2026-11-17T00:00:00Z
```

It contains the first five AniList ids (Cowboy Bebop and neighbours), four episode lists and the
same manifest, pointer, bucket-manifest, home, browse and auxiliary layout as a full release:

```
manifest.json
releases/rel-e9f04317f3a88802/
  manifest.json
  catalog/{00..63}.json      # only non-empty shards
  catalog/home.json
  catalog/browse.json
  search/universal/*.json
  media/{bucket}/al-*.json
  episodes/{bucket}/al-*.json
  ids/anilist/anime/*.json
  ids/mal/anime/*.json
  identity/ledger.json
  manifests/{media,episodes}/*.json
  schedule/*.json
  dub/{index,episodes}.json
  filler/index.json
  backdrops.json
  airing.json
  facets.json
  recommendations/neighbours-v1.tsv.gz
  skip/{shard}/{id}.json
  sources/lili/{shard}/{id}.json
```

Verify it exactly as a client would:

```bash
python scripts/validate_release.py --root fixtures/v1 --schemas
```

Notes for consumers:

- This is a **fixture, not a production release**. It is truncated, so relation and recommendation
  edges outside the first five ids are `resolved: false`. Do not infer catalogue completeness from
  its counts.
- `media` records carry normalized fields, `seriesIds`, relation `node` cards and recommendation
  `card` records. The raw `anilist` object is optional (only with `--include-raw`) and is not part
  of the default release.
- Records carry `provenance.source`; the release manifest carries `generatedAt` and per-source
  `lastUpdated`. There is deliberately no volatile per-record timestamp.
- Source rights are owner-approved for the existing scope. See `docs/SOURCE-POLICY.md`.
- Do not edit these files by hand. Rebuild them with the command above when the schema changes.
