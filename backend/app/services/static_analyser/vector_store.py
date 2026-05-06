from __future__ import annotations

import math
import re
from collections import Counter

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


class InProcessVectorStore:
    def __init__(self):
        self._rows: dict[str, list[dict]] = {}

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_]\w+", (text or "").lower())

    def _embed(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        total = max(1, len(tokens))
        c = Counter(tokens)
        return {k: v / total for k, v in c.items()}

    def index(self, chunks: list, job_id: str) -> None:
        rows = []
        for c in chunks:
            rows.append({"chunk_id": c.id, "vector": self._embed(c.code), "chunk": c})
        self._rows[job_id] = rows

    def search(self, query_vector, job_id: str, top_k: int = 5) -> list[dict]:
        rows = self._rows.get(job_id, [])
        if not rows:
            return []
        if isinstance(query_vector, str):
            qvec = self._embed(query_vector)
        else:
            qvec = query_vector or {}

        def cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
            keys = set(a.keys()) & set(b.keys())
            dot = sum(a[k] * b[k] for k in keys)
            an = math.sqrt(sum(v * v for v in a.values()))
            bn = math.sqrt(sum(v * v for v in b.values()))
            if an == 0 or bn == 0:
                return 0.0
            return dot / (an * bn)

        scored = [{"score": cosine_sparse(qvec, row["vector"]), "chunk": row["chunk"]} for row in rows]
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:top_k]
