"""Project the same verified v1 input into an independent immutable v2 namespace."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

import build_release
import franchise
import media_contract_v2 as contract
import publish_health
import release_v2
from validate_release import verify_release

ROOT = Path(__file__).resolve().parent.parent


def project_legacy(generation):
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(generation.glob("media/*/*.json"))]
    raw = {record["ids"]["anilist"]: record.get("anilist") or {} for record in records}
    graph = franchise.continuation_graph(raw)
    legacy_edges = set()
    for record in records:
        own = record["ids"]["anilist"]
        for other in record.get("seriesIds", []):
            if other != own and other not in graph.get(own, set()):
                legacy_edges.add(frozenset((own, other)))
                graph.setdefault(own, set()).add(other)
                graph.setdefault(other, set()).add(own)
    details, pages = [], []
    formats = {record["ids"]["anilist"]: record.get("format") for record in records}
    for record in records:
        own = record["ids"]["anilist"]
        detail = contract.adapt_v1_media(record)
        members = franchise.membership(own, raw, graph)
        ids = set(members["memberIds"])
        untyped = any(edge <= ids for edge in legacy_edges)
        detail["franchise"] = {
            "coverage": "partial" if untyped else members["coverage"],
            "truncated": members["truncated"],
            "unresolved": [contract.target(contract.anime_ref(i)) for i in members["unresolvedIds"]],
            "members": [{"ref": contract.target(contract.anime_ref(i)), "order": position,
                         "role": {"TV": "SEASON", "TV_SHORT": "SEASON", "ONA": "PART", "MOVIE": "FILM",
                                  "OVA": "SPECIAL", "SPECIAL": "SPECIAL"}.get(formats.get(i), "UNKNOWN"),
                         "sourceSeason": None, "absoluteOrdinal": None,
                         "provenance": {"source": "legacy-series+anilist" if untyped else "anilist"}}
                        for position, i in enumerate(members["memberIds"])],
        }
        details.append(detail)
    counts = {release_v2.identity(d["ref"]): d.get("declaredUnitCount") for d in details}
    for path in sorted(generation.glob("episodes/*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        key = release_v2.identity({"kind": "ANIME", "mediaKey": record["mediaKey"]})
        pages.extend(contract.adapt_v1_episodes(record, counts[key]))
    return details, pages


def build(data, out, policy, *, limit=0, generated_at=None, publish=False):
    out = Path(out).resolve()
    data = Path(data).resolve()
    if out.is_relative_to(data) or data.is_relative_to(out):
        raise ValueError("Output and legacy input directories must not overlap")
    if publish:
        if limit:
            raise ValueError("Limited staging builds cannot be published")
        if not policy.get("sources") or build_release.unpermitted_sources(policy):
            raise ValueError("Source policy does not permit production publication")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".v2-input-", dir=out.parent) as temporary:
        baseline = Path(temporary).resolve()
        if baseline.parent != out.parent:
            raise ValueError("Unexpected temporary input directory")
        summary = build_release.build(Path(data), baseline, policy, limit=limit, generated_at=generated_at, include_raw=True)
        verify_release(baseline, summary["releaseId"], schemas=True)
        details, pages = project_legacy(baseline / "releases" / summary["releaseId"])
        return release_v2.write_release(out, details, pages,
            generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), publish=publish)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=ROOT / "build/v2")
    parser.add_argument("--policy", type=Path, default=ROOT / "policy/source-rights.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--generated-at")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--rollback", metavar="RELEASE_ID")
    args = parser.parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if args.limit < 0 or args.rollback and args.publish:
            raise ValueError("Invalid build/publication options")
        if args.publish or args.rollback:
            if not policy.get("sources") or build_release.unpermitted_sources(policy):
                raise ValueError("Source policy does not permit production publication")
            if args.limit:
                raise ValueError("Limited staging builds cannot be published")
        if args.publish and publish_health.run(args.data, args.policy, require_permitted=True, deep=True)["state"] != "ok":
            raise ValueError("Production input failed freshness or publication health")
        result = release_v2.promote(args.out, args.rollback) if args.rollback else build(
            args.data, args.out, policy, limit=args.limit, generated_at=args.generated_at, publish=args.publish)
        print(json.dumps({"releaseId": result["manifest"]["releaseId"], "details": result["details"], "files": result["files"]}))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"v2 publication refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
