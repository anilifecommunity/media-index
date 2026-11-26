# Anilife 2.0 contract fixtures

`franchise-capture.json` is a bounded capture from the public AniList GraphQL endpoint, with the exact query and UTC capture time. It contains only metadata used to reproduce the two reported franchise issues. It is not a live availability guarantee. No artwork bytes or playback URLs are included.

The Steel Ball Run records are AniList 190327 (1st Stage) and 210482 (2nd–3rd Stage), both ONA. The two Attack on Titan final records are 146984 and 162314, both SPECIAL, reachable from first-season 16498 through explicit continuation edges. Their media IDs remain distinct; each final's episode 1 must retain its own media/unit identity.

`python scripts/test_franchise.py` checks symmetric continuation membership, missing inverse edges, cycles, incomplete hydration, bounds and exclusion of alternative/adaptation/side-story relations. These fixtures describe observed membership; publication and client selection/cache behavior have separate checks.

`identity-vectors.json` pins exact canonical/source keys and the legacy novel projection. `record-vectors.json` pins 36 labelled synthetic detail/catalogue/search/episode/chapter cases across all six kinds. They are shared Android/Web contract fixtures, not production catalogue records. See `docs/IDENTITY-V2.md` and `docs/CONTRACT-V2.md`.
