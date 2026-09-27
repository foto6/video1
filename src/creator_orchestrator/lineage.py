from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Artifact


class LineageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LineageReport:
    node_count: int
    edge_count: int
    root_ids: tuple[str, ...]
    leaf_ids: tuple[str, ...]
    topological_order: tuple[str, ...]


def validate_artifact_dag(artifacts: Iterable[Artifact]) -> LineageReport:
    nodes = list(artifacts)
    by_id: dict[str, Artifact] = {}
    for artifact in nodes:
        if artifact.id in by_id:
            raise LineageValidationError(f"duplicate artifact id: {artifact.id}")
        by_id[artifact.id] = artifact

    children: dict[str, list[str]] = {artifact.id: [] for artifact in nodes}
    indegree: dict[str, int] = {artifact.id: 0 for artifact in nodes}
    edge_count = 0
    for artifact in nodes:
        seen_parent_ids: set[str] = set()
        for parent in artifact.parents:
            if parent == artifact.id:
                raise LineageValidationError(f"artifact {artifact.id} cannot parent itself")
            if parent in seen_parent_ids:
                raise LineageValidationError(
                    f"artifact {artifact.id} has duplicate parent {parent}"
                )
            seen_parent_ids.add(parent)
            if parent not in by_id:
                raise LineageValidationError(
                    f"artifact {artifact.id} references unknown parent {parent}"
                )
            children[parent].append(artifact.id)
            indegree[artifact.id] += 1
            edge_count += 1

    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()

    if len(order) != len(nodes):
        cyclic = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
        raise LineageValidationError(
            "artifact lineage contains a cycle involving: " + ", ".join(cyclic)
        )

    roots = tuple(sorted(a.id for a in nodes if not a.parents))
    leaves = tuple(sorted(node_id for node_id, values in children.items() if not values))
    return LineageReport(
        node_count=len(nodes),
        edge_count=edge_count,
        root_ids=roots,
        leaf_ids=leaves,
        topological_order=tuple(order),
    )
