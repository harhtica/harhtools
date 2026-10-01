"""Per-gesture region ownership for Shape Builder.

Each group is one independently created fill. Adjacency alone never merges fills.
A continuous Add gesture joins only the fills and unfilled regions it hits.
Remove works on atomic regions even inside a previously joined fill.
The helpers are independent of Blender and never mutate their input collections.
"""
from collections.abc import Iterable


def copy_groups(groups: Iterable[Iterable[int]]) -> list[set[int]]:
    result=[]
    owned=set()
    for group in groups:
        region_ids=set(group)
        if not region_ids:continue
        if any(not isinstance(rid,int) or rid<0 for rid in region_ids):
            raise ValueError('Fill groups require non-negative region IDs.')
        if owned.intersection(region_ids):
            raise ValueError('A region cannot belong to more than one fill group.')
        owned.update(region_ids)
        result.append(region_ids)
    return result


def connected_pieces(region_ids, neighbors):
    if not region_ids:return []
    if neighbors is None:return [set(region_ids)]
    remaining=set(region_ids);result=[]
    while remaining:
        start=min(remaining);remaining.remove(start)
        component={start};pending=[start]
        while pending:
            adjacent=set(neighbors.get(pending.pop(),())) & remaining
            remaining.difference_update(adjacent)
            component.update(adjacent);pending.extend(adjacent)
        result.append(component)
    return result


def gesture_groups(groups: Iterable[Iterable[int]], hit_ids: Iterable[int], erase: bool=False,
                   *, neighbors=None) -> list[set[int]]:
    """Apply one completed or currently previewed gesture to its start snapshot.

    Call with ALL regions hit so far in this gesture, and the unchanged groups
    from mouse-down. Separate mouse-down/up gestures use the prior result as
    their next snapshot. -1 (outside the arrangement) is ignored.

    Add: merge hit regions and existing fills they touch, keeping prior explicit
    joins. Preserve untouched groups and their relative order. Put a merge in
    the earliest touched group's slot, or append a new fill. A click on an
    already filled region is a no-op, not an implicit unjoin.
    Erase: subtract only touched atomic regions; unfilled hits do nothing.
    With adjacency supplied, split a severed fill into its remaining connected
    pieces, so adding to one piece cannot silently merge another across the gap.
    """
    current=copy_groups(groups)
    hits={rid for rid in hit_ids if isinstance(rid,int) and rid>=0}
    if not hits:return current
    touched=[index for index,group in enumerate(current) if group.intersection(hits)]
    if erase:
        result=[]
        for group in current:
            remaining=group-hits
            if not remaining:continue
            if neighbors is None or remaining==group:
                result.append(remaining);continue
            result.extend(connected_pieces(remaining,neighbors))
        return result
    merged=set(hits)
    for index in touched:merged.update(current[index])
    if not touched:return current+[merged]
    first=touched[0];touched_set=set(touched)
    result=[]
    for index,group in enumerate(current):
        if index==first:result.append(merged)
        elif index not in touched_set:result.append(group)
    return result


def group_for_region(groups: Iterable[Iterable[int]], region_id: int, *, erase=False, atomic=False) -> set[int]:
    """Resolve an owner, or one region for atomic Add/Remove hover previews."""
    if region_id<0:return set()
    for group in groups:
        if region_id in group:return {region_id} if erase or atomic else set(group)
    return set() if erase else {region_id}


def region_neighbors(arrangement):
    """Cache shared-edge adjacency once for the immutable source arrangement."""
    if '_fill_neighbors' not in arrangement:
        neighbors={rid:set() for rid in range(len(arrangement['regions']))}
        for triangles in arrangement['edge_faces'].values():
            owners={arrangement['tri_region'][triangle] for triangle in triangles}-{ -1 }
            for owner in owners:neighbors[owner].update(owners-{owner})
        arrangement['_fill_neighbors']=neighbors
    return arrangement['_fill_neighbors']


def selected_regions(groups: Iterable[Iterable[int]]) -> set[int]:
    return {rid for group in groups for rid in group}


def snapshot_groups(groups: Iterable[Iterable[int]]) -> tuple[frozenset[int], ...]:
    """An immutable undo or mouse-down snapshot, safe from preview mutation."""
    return tuple(frozenset(group) for group in copy_groups(groups))


def restore_groups(snapshot: Iterable[Iterable[int]]) -> list[set[int]]:
    return copy_groups(snapshot)


def boundary_edges_for_groups(arrangement: dict, groups: Iterable[Iterable[int]]) -> list[list[tuple[int,int]]]:
    """Per-fill directed outlines: keep shared edges between separate fills.

    Interior seams disappear only within an intentionally merged group. Shared
    seams between adjacent independent fills appear once in each fill's outline
    with opposite directions; callers may deduplicate them for line drawing.
    """
    result=[]
    for group in copy_groups(groups):
        chosen={triangle for rid in group for triangle in arrangement['regions'][rid]['triangles']}
        outline=[]
        for index in sorted(chosen):
            tri=tuple(arrangement['triangles'][index])
            for a,b in zip(tri,tri[1:]+tri[:1]):
                adjacent=arrangement['edge_faces'][tuple(sorted((a,b)))]
                if sum(other in chosen for other in adjacent)==1:outline.append((a,b))
        result.append(outline)
    return result
