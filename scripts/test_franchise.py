"""Offline regression cases using the captured IDs from both user reports."""

import copy
import argparse
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from franchise import continuation_graph, membership
import konoha_build

capture = json.loads((Path(__file__).resolve().parent.parent /
                     "fixtures/v2/franchise-capture.json").read_text(encoding="utf-8-sig"))
records = {record["id"]: record for record in capture["records"]}
graph = continuation_graph(records)

for first, second in ((190327, 210482), (16498, 146984), (146984, 162314)):
    left, right = membership(first, records, graph), membership(second, records, graph)
    assert left == right, (first, second, left, right)
    assert left["coverage"] == "complete"
    assert first in left["memberIds"] and second in left["memberIds"]
assert {146984, 162314} <= set(membership(16498, records, graph)["memberIds"])
assert records[146984]["format"] == records[162314]["format"] == "SPECIAL"
assert records[190327]["format"] == records[210482]["format"] == "ONA"

# A missing inverse edge must not split a franchise depending on the opened entry.
one_way = copy.deepcopy(records)
one_way[210482]["relations"]["edges"] = []
one_way_graph = continuation_graph(one_way)
assert membership(190327, one_way, one_way_graph) == membership(210482, one_way, one_way_graph)

# Membership survives missing hydration; this answer must not be cached as complete.
partial = {key: value for key, value in records.items() if key != 162314}
result = membership(16498, partial, continuation_graph(partial))
assert 162314 in result["memberIds"]
assert result["unresolvedIds"] == [162314] and result["coverage"] == "partial"
for kwargs in ({"max_entries": 2}, {"max_depth": 0}):
    result = membership(16498, records, graph, **kwargs)
    assert result["coverage"] == "partial" and result["truncated"]

unrelated = copy.deepcopy(records)
unrelated[16498]["relations"]["edges"].extend([
    {"relationType": "ALTERNATIVE", "node": {"id": 900001, "type": "ANIME"}},
    {"relationType": "ADAPTATION", "node": {"id": 900002, "type": "MANGA"}},
    {"relationType": "SIDE_STORY", "node": {"id": 900003, "type": "ANIME"}},
])
assert membership(16498, unrelated, continuation_graph(unrelated)) == membership(16498, records, graph)
assert membership(16498, dict(reversed(list(records.items()))), continuation_graph(records)) == membership(16498, records, graph)
assert membership(999999, records, graph)["coverage"] == "partial"
assert membership(1, {1: {}}, {1: set()})["coverage"] == "partial"
assert membership(1, {1: {"relations": {"edges": []}}}, {1: set()})["coverage"] == "complete"

with tempfile.TemporaryDirectory() as temporary:
    out = Path(temporary) / "data"
    with (patch.object(konoha_build, "load_catalog", return_value=list(records.values())),
          patch.object(konoha_build, "load_fribb", return_value={}),
          patch.object(konoha_build, "load_anizip", return_value={}),
          patch.object(konoha_build, "EPISODE_DIR", Path(temporary) / "episodes"),
          contextlib.redirect_stdout(io.StringIO())):
        assert konoha_build.cmd_emit(argparse.Namespace(out=out, clean=False, refresh_fribb=False)) == 0
    for root in capture["roots"]:
        detail = json.loads((out / "anime" / str(root // 1000) / str(root) / "index.json").read_text(encoding="utf-8"))
        assert detail["series"] == membership(root, records, graph)["memberIds"]
        assert detail["seriesCoverage"] == {"coverage": "complete", "unresolvedIds": [], "truncated": False}
print("all franchise checks passed")
