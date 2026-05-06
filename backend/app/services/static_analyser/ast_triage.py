from __future__ import annotations

import ast
import hashlib
import math
import re
from pathlib import Path

from app.services.static_analyser import ChunkData, TriageResult

IMPORT_RE = re.compile(r'^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))')
JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)|"
    r"^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)
SMELL_SECRET_RE = re.compile(r"(api[_-]?key|password|secret)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE)


def _sha(path: str, start: int, code: str) -> str:
    return hashlib.sha256(f"{path}:{start}:{code}".encode("utf-8")).hexdigest()


def _cyclomatic_complexity(code: str) -> int:
    decision_tokens = [" if ", " elif ", " for ", " while ", " and ", " or ", " except ", " case "]
    text = f" {code} "
    return 1 + sum(text.count(tok) for tok in decision_tokens)


def _halstead_volume(code: str) -> float:
    tokens = re.findall(r"[A-Za-z_]\w+|==|!=|<=|>=|&&|\|\||[+\-*/%=<>]", code)
    if not tokens:
        return 0.0
    operators = {t for t in tokens if re.fullmatch(r"==|!=|<=|>=|&&|\|\||[+\-*/%=<>]", t)}
    operands = {t for t in tokens if t not in operators}
    n = max(1, len(operators | operands))
    n_total = len(tokens)
    return round(float(n_total * math.log2(n)), 2)


def _smells(code: str, line_count: int, param_count: int) -> list[str]:
    smells: list[str] = []
    if line_count > 50:
        smells.append("LongFunction")
    if param_count > 5:
        smells.append("TooManyParams")
    if SMELL_SECRET_RE.search(code):
        smells.append("HardcodedSecret")
    if "console.log(" in code:
        smells.append("ConsoleLog")
    if "print(" in code:
        smells.append("print_debug")
    return smells


def _parse_python(path: Path, source: str) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunks

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        lines = source.splitlines()
        code = "\n".join(lines[start - 1 : end])
        params = len(getattr(node.args, "args", []))
        imports = _extract_imports(source)
        chunks.append(
            ChunkData(
                id=_sha(str(path), start, code),
                code=code,
                file_path=str(path),
                start_line=start,
                end_line=end,
                cyclomatic_complexity=_cyclomatic_complexity(code),
                halstead_volume=_halstead_volume(code),
                smells=_smells(code, end - start + 1, params),
                cfg={
                    "nodes": max(1, end - start + 1),
                    "edges": max(0, _cyclomatic_complexity(code) - 1),
                    "unreachable_code_detected": "return\n" in code and code.strip().splitlines()[-1] != "return",
                },
                imports=imports,
                resolved_deps=[],
            )
        )
    return chunks


def _parse_js_like(path: Path, source: str) -> list[ChunkData]:
    lines = source.splitlines()
    chunks: list[ChunkData] = []
    for idx, line in enumerate(lines, start=1):
        m = JS_FUNC_RE.search(line)
        if not m:
            continue
        name = m.group(1) or m.group(3) or "anonymous"
        params_raw = m.group(2) or m.group(4) or ""
        params = [p.strip() for p in params_raw.split(",") if p.strip()]
        end = min(len(lines), idx + 80)
        code = "\n".join(lines[idx - 1 : end])
        chunks.append(
            ChunkData(
                id=_sha(str(path), idx, code),
                code=code,
                file_path=str(path),
                start_line=idx,
                end_line=end,
                cyclomatic_complexity=_cyclomatic_complexity(code),
                halstead_volume=_halstead_volume(code),
                smells=_smells(code, end - idx + 1, len(params)),
                cfg={
                    "nodes": max(1, end - idx + 1),
                    "edges": max(0, _cyclomatic_complexity(code) - 1),
                    "unreachable_code_detected": False,
                },
                imports=_extract_imports(source),
                resolved_deps=[],
            )
        )
    return chunks


def _extract_imports(source: str) -> list[str]:
    imports: list[str] = []
    for line in source.splitlines():
        m = IMPORT_RE.match(line)
        if m:
            imports.append(m.group(1) or m.group(2) or "")
        elif line.strip().startswith("import ") and " from " in line:
            try:
                imports.append(line.split(" from ", 1)[1].strip().strip(";").strip("'\""))
            except Exception:
                pass
    return sorted(set([x for x in imports if x]))


def run_ast_triage(local_path: str, target_files: list[str]) -> TriageResult:
    root = Path(local_path)
    all_chunks: list[ChunkData] = []
    adjacency: dict[str, list[str]] = {}
    existing = {str(Path(p)) for p in target_files}

    for rel in target_files:
        full = root / rel
        if not full.exists():
            continue
        source = full.read_text(encoding="utf-8", errors="ignore")
        ext = full.suffix.lower()
        if ext == ".py":
            chunks = _parse_python(Path(rel), source)
        else:
            chunks = _parse_js_like(Path(rel), source)
        imports = _extract_imports(source)
        resolved: list[str] = []
        for imp in imports:
            maybe = str(Path(imp.replace(".", "/"))).rstrip("/")
            for extn in (".py", ".js", ".ts", ".tsx", ".jsx"):
                guess = f"{maybe}{extn}"
                if guess in existing:
                    resolved.append(guess)
        adjacency[str(Path(rel))] = sorted(set(resolved))
        for c in chunks:
            c.resolved_deps = adjacency[str(Path(rel))]
        all_chunks.extend(chunks)

    return TriageResult(chunks=all_chunks, adjacency_list=adjacency)
