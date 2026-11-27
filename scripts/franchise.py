"""Bounded continuation membership from explicit anime relations, never title matching."""

from collections import deque

MAX_ENTRIES = 16
MAX_DEPTH = 8


def continuation_graph(records: dict[int, dict]) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {media_id: set() for media_id in records}
    for media_id, record in records.items():
        for edge in (record.get("relations") or {}).get("edges") or []:
            node = edge.get("node") or {}
            other = node.get("id")
            if (edge.get("relationType") not in ("PREQUEL", "SEQUEL")
                    or type(other) is not int or other < 1 or other == media_id
                    or node.get("type") not in (None, "ANIME")):
                continue
            graph.setdefault(media_id, set()).add(other)
            graph.setdefault(other, set()).add(media_id)
    return graph


def membership(root: int, records: dict[int, dict], graph: dict[int, set[int]],
               max_entries: int = MAX_ENTRIES, max_depth: int = MAX_DEPTH) -> dict:
    if type(root) is not int or root < 1 or max_entries < 1 or max_depth < 0:
        raise ValueError("Invalid franchise root or bounds")
    found = {root}
    queue = deque([(root, 0)])
    unresolved: set[int] = set()
    truncated = False
    while queue:
        media_id, depth = queue.popleft()
        record = records.get(media_id)
        if record is None or not isinstance((record.get("relations") or {}).get("edges"), list):
            unresolved.add(media_id)
        for other in sorted(graph.get(media_id, ())):
            if other in found:
                continue
            if depth >= max_depth or len(found) >= max_entries:
                truncated = True
                continue
            found.add(other)
            queue.append((other, depth + 1))

    def airing_order(media_id: int) -> tuple:
        record = records.get(media_id) or {}
        start = record.get("startDate") or {}
        return (start.get("year") or record.get("seasonYear") or 9999,
                start.get("month") or 99, start.get("day") or 99, media_id)

    return {
        "memberIds": sorted(found, key=airing_order),
        "coverage": "partial" if unresolved or truncated else "complete",
        "unresolvedIds": sorted(unresolved),
        "truncated": truncated,
    }
