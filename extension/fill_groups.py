"""Per-gesture region ownership for Shape Builder.

Each group is one independently created fill. Adjacency alone never merges fills.
A single continuous gesture merges only the groups and unfilled regions it hits.
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


def gesture_groups(groups: Iterable[Iterable[int]], hit_ids: Iterable[int], erase: bool=False) -> list[set[int]]:
    """Apply one completed or currently previewed gesture to its start snapshot.

    Call with ALL regions hit so far in this gesture, and the unchanged groups
    from mouse-down. Separate mouse-down/up gestures use the prior result as
    their next snapshot. -1 (outside the arrangement) is ignored.

    Add: merge hit regions and whole existing groups they touch. Preserve every
    untouched group and its relative order. Put a merge in the earliest touched
    group's slot, or append a new fill if no existing group was touched.
    Erase: remove touched existing groups; unfilled hits do nothing.
    """
    current=copy_groups(groups)
    hits={rid for rid in hit_ids if isinstance(rid,int) and rid>=0}
    if not hits:return current
    touched=[index for index,group in enumerate(current) if group.intersection(hits)]
    if erase:
        touched_set=set(touched)
        return [group for index,group in enumerate(current) if index not in touched_set]
    merged=set(hits)
    for index in touched:merged.update(current[index])
    if not touched:return current+[merged]
    first=touched[0];touched_set=set(touched)
    result=[]
    for index,group in enumerate(current):
        if index==first:result.append(merged)
        elif index not in touched_set:result.append(group)
    return result


def group_for_region(groups: Iterable[Iterable[int]], region_id: int) -> set[int]:
    """Whole owned fill under the pointer, or the single unfilled region."""
    if region_id<0:return set()
    for group in groups:
        if region_id in group:return set(group)
    return {region_id}


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
