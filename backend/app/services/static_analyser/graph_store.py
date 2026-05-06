from __future__ import annotations


class InProcessGraphStore:
    def __init__(self):
        self.graph: dict[str, list[str]] = {}

    def build_graph(self, adjacency_list: dict[str, list[str]]) -> dict[str, list[str]]:
        self.graph = {k: list(v) for k, v in adjacency_list.items()}
        return self.graph

    def find_cycles(self) -> list[list[str]]:
        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: list[str] = []
        in_stack: set[str] = set()

        def dfs(node: str):
            visited.add(node)
            stack.append(node)
            in_stack.add(node)
            for nxt in self.graph.get(node, []):
                if nxt not in visited:
                    dfs(nxt)
                elif nxt in in_stack:
                    i = stack.index(nxt)
                    cycle = stack[i:] + [nxt]
                    if cycle not in cycles:
                        cycles.append(cycle)
            stack.pop()
            in_stack.discard(node)

        for node in self.graph:
            if node not in visited:
                dfs(node)
        return cycles

    def compute_coupling_scores(self) -> list[dict]:
        fan_out = {k: len(v) for k, v in self.graph.items()}
        fan_in: dict[str, int] = {k: 0 for k in self.graph}
        for src, dests in self.graph.items():
            fan_in.setdefault(src, 0)
            for d in dests:
                fan_in[d] = fan_in.get(d, 0) + 1
        rows = []
        for node in set(list(fan_in.keys()) + list(fan_out.keys())):
            rows.append(
                {
                    "file_path": node,
                    "fan_in": fan_in.get(node, 0),
                    "fan_out": fan_out.get(node, 0),
                    "coupling_score": fan_in.get(node, 0) * fan_out.get(node, 0),
                }
            )
        return sorted(rows, key=lambda x: x["coupling_score"], reverse=True)

    def find_god_classes(self, chunk_count_threshold: int = 15, edge_threshold: int = 10, chunk_counts: dict | None = None) -> list[dict]:
        chunk_counts = chunk_counts or {}
        scores = self.compute_coupling_scores()
        out = []
        for row in scores:
            ccount = chunk_counts.get(row["file_path"], 0)
            edges = row["fan_in"] + row["fan_out"]
            if ccount >= chunk_count_threshold or edges >= edge_threshold:
                out.append(
                    {
                        "file_path": row["file_path"],
                        "chunk_count": ccount,
                        "edge_count": edges,
                        "coupling_score": row["coupling_score"],
                    }
                )
        return out
