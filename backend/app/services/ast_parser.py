"""Multi-language AST parser using tree-sitter for code indexing."""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter

from app.config import get_settings
from app.core.exceptions import ASTParseError, IndexingError
from app.core.logging import logger


# ── Data Structures ──────────────────────────────────────────────

@dataclass
class FunctionInfo:
    name: str
    qualified_name: str | None
    file_path: str
    line_number: int
    end_line_number: int
    calls: list[str] = field(default_factory=list)
    language: str = ""


@dataclass
class LogCallInfo:
    log_string: str
    file_path: str
    line_number: int
    function_name: str | None = None
    log_level: str | None = None
    language: str = ""


@dataclass
class SourceLocation:
    file_path: str
    line_number: int
    function_name: str
    qualified_name: str | None = None


@dataclass
class CodeIndexData:
    """In-memory representation of a fully-built code index."""

    repo_full_name: str
    commit_sha: str
    functions: list[FunctionInfo] = field(default_factory=list)
    log_calls: list[LogCallInfo] = field(default_factory=list)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    reverse_call_graph: dict[str, list[str]] = field(default_factory=dict)
    log_line_map: dict[str, SourceLocation] = field(default_factory=dict)
    language_breakdown: dict[str, int] = field(default_factory=dict)

    def get_callers(self, function_name: str, max_depth: int = 5) -> list[SourceLocation]:
        """Walk reverse call graph upward to find the full call chain."""
        chain: list[SourceLocation] = []
        visited: set[str] = set()
        func_map = {f.name: f for f in self.functions}

        def _walk(name: str, depth: int):
            if depth <= 0 or name in visited:
                return
            visited.add(name)
            for caller in self.reverse_call_graph.get(name, []):
                if caller in func_map:
                    f = func_map[caller]
                    chain.append(SourceLocation(
                        file_path=f.file_path,
                        line_number=f.line_number,
                        function_name=f.name,
                        qualified_name=f.qualified_name,
                    ))
                    _walk(caller, depth - 1)

        _walk(function_name, max_depth)
        return chain


# ── Language Configuration ───────────────────────────────────────

def _get_language(module_name: str):
    """Dynamically import a tree-sitter language module."""
    try:
        mod = __import__(module_name)
        return tree_sitter.Language(mod.language())
    except (ImportError, AttributeError, OSError) as e:
        logger.warning("tree-sitter language %s not available: %s", module_name, e)
        return None


# Log call patterns per language: (object, method) pairs
# None as object means a standalone function call (e.g., print)
PYTHON_LOG_PATTERNS = [
    ("logger", "info"), ("logger", "warning"), ("logger", "error"),
    ("logger", "debug"), ("logger", "critical"), ("logger", "exception"),
    ("logging", "info"), ("logging", "warning"), ("logging", "error"),
    ("logging", "debug"), ("logging", "critical"),
    (None, "print"),
]

JS_LOG_PATTERNS = [
    ("console", "log"), ("console", "warn"), ("console", "error"),
    ("console", "info"), ("console", "debug"),
    ("logger", "info"), ("logger", "warn"), ("logger", "error"),
    ("logger", "debug"),
]

JAVA_LOG_PATTERNS = [
    ("logger", "info"), ("logger", "warn"), ("logger", "error"),
    ("logger", "debug"), ("logger", "trace"),
    ("log", "i"), ("log", "w"), ("log", "e"), ("log", "d"),
    ("System.out", "println"), ("System.err", "println"),
]

GO_LOG_PATTERNS = [
    ("log", "Println"), ("log", "Printf"), ("log", "Print"),
    ("log", "Fatal"), ("log", "Fatalf"),
    ("fmt", "Println"), ("fmt", "Printf"), ("fmt", "Print"),
    ("fmt", "Fprintf"), ("fmt", "Sprintf"),
]

C_LOG_PATTERNS = [
    r'g_debug\s*\(',
    r'g_warning\s*\(',
    r'g_message\s*\(',
    r'g_print\s*\(',
    r'ws_debug\s*\(',
    r'proto_tree_add_debug_text\s*\(',
]

LANGUAGE_CONFIG = {
    ".py": {
        "module": "tree_sitter_python",
        "log_patterns": PYTHON_LOG_PATTERNS,
        "func_node_types": ["function_definition"],
        "class_node_type": "class_definition",
        "call_node_type": "call",
    },
    ".js": {
        "module": "tree_sitter_javascript",
        "log_patterns": JS_LOG_PATTERNS,
        "func_node_types": ["function_declaration", "method_definition"],
        "arrow_func_value_types": ["arrow_function", "function_expression", "function"],
        "class_node_type": "class_declaration",
        "call_node_type": "call_expression",
    },
    ".jsx": {
        "module": "tree_sitter_javascript",
        "log_patterns": JS_LOG_PATTERNS,
        "func_node_types": ["function_declaration", "method_definition"],
        "arrow_func_value_types": ["arrow_function", "function_expression", "function"],
        "class_node_type": "class_declaration",
        "call_node_type": "call_expression",
    },
    ".ts": {
        "module": "tree_sitter_typescript",
        "ts_variant": "typescript",
        "log_patterns": JS_LOG_PATTERNS,
        "func_node_types": ["function_declaration", "method_definition"],
        "arrow_func_value_types": ["arrow_function", "function_expression", "function"],
        "class_node_type": "class_declaration",
        "call_node_type": "call_expression",
    },
    ".tsx": {
        "module": "tree_sitter_typescript",
        "ts_variant": "tsx",
        "log_patterns": JS_LOG_PATTERNS,
        "func_node_types": ["function_declaration", "method_definition"],
        "arrow_func_value_types": ["arrow_function", "function_expression", "function"],
        "class_node_type": "class_declaration",
        "call_node_type": "call_expression",
    },
    ".java": {
        "module": "tree_sitter_java",
        "log_patterns": JAVA_LOG_PATTERNS,
        "func_node_types": ["method_declaration"],
        "class_node_type": "class_declaration",
        "call_node_type": "method_invocation",
    },
    ".go": {
        "module": "tree_sitter_go",
        "log_patterns": GO_LOG_PATTERNS,
        "func_node_types": ["function_declaration", "method_declaration"],
        "class_node_type": None,
        "call_node_type": "call_expression",
    },
    ".c": {
        "module": "tree_sitter_c",
        "log_patterns": C_LOG_PATTERNS,
        "func_node_types": ["function_definition"],
        "class_node_type": None,
        "call_node_type": "call_expression",
    },
    ".h": {
        "module": "tree_sitter_c",
        "log_patterns": C_LOG_PATTERNS,
        "func_node_types": ["function_definition", "declaration"],
        "class_node_type": None,
        "call_node_type": "call_expression",
    },
}


# ── AST Parser ───────────────────────────────────────────────────

class ASTParser:
    """Multi-language AST parser using tree-sitter."""

    SUPPORTED_EXTENSIONS = set(LANGUAGE_CONFIG.keys())

    def __init__(self):
        self._parsers: dict[str, tree_sitter.Parser] = {}
        self._languages: dict[str, tree_sitter.Language] = {}

    def _get_parser(self, ext: str) -> tree_sitter.Parser | None:
        """Get or create a tree-sitter parser for the given file extension."""
        if ext in self._parsers:
            return self._parsers[ext]

        config = LANGUAGE_CONFIG.get(ext)
        if not config:
            return None

        module_name = config["module"]

        try:
            mod = __import__(module_name)
            # Handle TypeScript which has tsx/typescript variants
            if "ts_variant" in config:
                lang_func = getattr(mod, f"language_{config['ts_variant']}", None)
                if lang_func is None:
                    lang_func = mod.language
                language = tree_sitter.Language(lang_func())
            else:
                language = tree_sitter.Language(mod.language())
        except (ImportError, AttributeError, OSError) as e:
            logger.warning("tree-sitter language for %s not available: %s", ext, e)
            self._parsers[ext] = None
            return None

        parser = tree_sitter.Parser(language)
        self._parsers[ext] = parser
        self._languages[ext] = language
        return parser

    def parse_file(
        self, source_code: str, file_path: str
    ) -> tuple[list[FunctionInfo], list[LogCallInfo]]:
        """Parse a single source file and extract functions + log calls."""
        ext = os.path.splitext(file_path)[1]
        if ext not in LANGUAGE_CONFIG:
            return [], []

        parser = self._get_parser(ext)
        if parser is None:
            return [], []

        config = LANGUAGE_CONFIG[ext]
        source_bytes = source_code.encode("utf-8")

        try:
            tree = parser.parse(source_bytes)
        except Exception as e:
            raise ASTParseError(
                f"Failed to parse {file_path}", detail=str(e)
            ) from e

        functions = self._extract_functions(
            tree.root_node, source_bytes, file_path, config
        )
        log_calls = self._extract_log_calls(
            tree.root_node, source_bytes, file_path, config, functions
        )
        return functions, log_calls

    def _extract_functions(
        self, root, source_bytes: bytes, file_path: str, config: dict
    ) -> list[FunctionInfo]:
        """Extract all function definitions from the AST."""
        functions: list[FunctionInfo] = []
        ext = os.path.splitext(file_path)[1]
        lang = ext.lstrip(".")

        arrow_value_types = config.get("arrow_func_value_types", [])

        def _walk(node, class_name: str | None = None):
            # Check for class definitions to build qualified names
            if config.get("class_node_type") and node.type == config["class_node_type"]:
                cname = self._get_node_name(node, source_bytes)
                for child in node.children:
                    _walk(child, cname)
                return

            if node.type in config["func_node_types"]:
                name = self._get_node_name(node, source_bytes)
                if name:
                    qualified = f"{class_name}.{name}" if class_name else name
                    calls = self._extract_calls_in_body(
                        node, source_bytes, config["call_node_type"]
                    )
                    functions.append(FunctionInfo(
                        name=name,
                        qualified_name=qualified,
                        file_path=file_path,
                        line_number=node.start_point.row + 1,
                        end_line_number=node.end_point.row + 1,
                        calls=calls,
                        language=lang,
                    ))

            # Capture arrow functions / function expressions assigned to variables:
            # const foo = () => {}  |  const bar = function() {}
            elif arrow_value_types and node.type == "variable_declarator":
                name_node = next(
                    (c for c in node.children if c.type == "identifier"), None
                )
                value_node = next(
                    (c for c in reversed(node.children) if c.type in arrow_value_types),
                    None,
                )
                if name_node and value_node:
                    name = name_node.text.decode("utf-8")
                    qualified = f"{class_name}.{name}" if class_name else name
                    calls = self._extract_calls_in_body(
                        value_node, source_bytes, config["call_node_type"]
                    )
                    functions.append(FunctionInfo(
                        name=name,
                        qualified_name=qualified,
                        file_path=file_path,
                        line_number=node.start_point.row + 1,
                        end_line_number=node.end_point.row + 1,
                        calls=calls,
                        language=lang,
                    ))

            for child in node.children:
                _walk(child, class_name)

        _walk(root)
        return functions

    def _extract_calls_in_body(
        self, func_node, source_bytes: bytes, call_type: str
    ) -> list[str]:
        """Find all function/method calls within a function body."""
        calls: list[str] = []

        def _walk(node):
            if node.type == call_type:
                call_name = self._get_call_name(node, source_bytes)
                if call_name:
                    calls.append(call_name)
            for child in node.children:
                _walk(child)

        _walk(func_node)
        return calls

    def _extract_log_calls(
        self,
        root,
        source_bytes: bytes,
        file_path: str,
        config: dict,
        functions: list[FunctionInfo],
    ) -> list[LogCallInfo]:
        """Find all log/print calls and extract string arguments."""
        log_calls: list[LogCallInfo] = []
        ext = os.path.splitext(file_path)[1]
        lang = ext.lstrip(".")
        patterns = config["log_patterns"]
        c_regex_mode = bool(patterns and isinstance(patterns[0], str))

        def _is_log_call(node) -> tuple[bool, str | None]:
            """Check if a call node matches a log pattern. Returns (is_match, level)."""
            if c_regex_mode:
                snippet = node.text.decode("utf-8", errors="replace")
                for pat in patterns:
                    if isinstance(pat, str) and re.search(pat, snippet):
                        return True, None
                return False, None

            call_name = self._get_call_name(node, source_bytes)
            if not call_name:
                return False, None

            for obj, method in patterns:
                if obj is None:
                    if call_name == method:
                        return True, None
                else:
                    expected = f"{obj}.{method}"
                    if call_name == expected:
                        return True, method
            return False, None

        def _find_enclosing_function(line: int) -> str | None:
            for func in functions:
                if func.line_number <= line <= func.end_line_number:
                    return func.name
            return None

        def _walk(node):
            if node.type in (config["call_node_type"], "call"):
                is_log, level = _is_log_call(node)
                if is_log:
                    log_str = self._extract_first_string_arg(node, source_bytes)
                    if log_str:
                        line = node.start_point.row + 1
                        log_calls.append(LogCallInfo(
                            log_string=log_str,
                            file_path=file_path,
                            line_number=line,
                            function_name=_find_enclosing_function(line),
                            log_level=level,
                            language=lang,
                        ))
            for child in node.children:
                _walk(child)

        _walk(root)
        return log_calls

    @staticmethod
    def _get_node_name(node, source_bytes: bytes) -> str | None:
        """Extract the name identifier from a function/class node."""
        # Fast path for direct children (works for most languages).
        for child in node.children:
            if child.type in ("identifier", "property_identifier", "name"):
                return child.text.decode("utf-8")

        # C/C-header function nodes often nest the function identifier under
        # function_declarator / pointer_declarator / declarator.
        if node.type in ("function_definition", "declaration"):
            stack = list(node.children)
            while stack:
                cur = stack.pop(0)
                if cur.type in ("identifier", "property_identifier", "name"):
                    return cur.text.decode("utf-8")
                stack.extend(list(cur.children))

        # Generic fallback: nested identifier search for any remaining grammar.
        stack = list(node.children)
        while stack:
            cur = stack.pop(0)
            if cur.type in ("identifier", "property_identifier", "name"):
                return cur.text.decode("utf-8")
            stack.extend(list(cur.children))
        return None

    @staticmethod
    def _get_call_name(node, source_bytes: bytes) -> str | None:
        """Extract the full name from a call expression (e.g., 'console.log')."""
        # The function/callee is typically the first child
        func_node = node.children[0] if node.children else None
        if func_node is None:
            return None

        if func_node.type == "identifier":
            return func_node.text.decode("utf-8")
        elif func_node.type in ("member_expression", "attribute"):
            # obj.method
            return func_node.text.decode("utf-8")
        elif func_node.type == "field_expression":
            # Go: pkg.Func
            return func_node.text.decode("utf-8")
        return None

    @staticmethod
    def _extract_first_string_arg(call_node, source_bytes: bytes) -> str | None:
        """Extract the first string literal from a call's arguments."""
        # Find the arguments node
        args_node = None
        for child in call_node.children:
            if child.type in (
                "argument_list", "arguments", "template_string",
                "call_expression",
            ):
                args_node = child
                break

        if args_node is None:
            # Some languages have arguments as direct children
            args_node = call_node

        def _find_string(node) -> str | None:
            # String literals
            if node.type in ("string", "string_literal", "interpreted_string_literal"):
                text = node.text.decode("utf-8")
                # Strip quotes
                if len(text) >= 2 and text[0] in ('"', "'", '`'):
                    return text[1:-1]
                return text

            # Python f-strings: extract the static prefix
            if node.type == "string" and node.children:
                parts = []
                for child in node.children:
                    if child.type == "string_content":
                        parts.append(child.text.decode("utf-8"))
                    elif child.type in ("string_start", "string_end"):
                        continue
                    else:
                        break
                if parts:
                    return "".join(parts)

            # Concatenated strings: take the first part
            if node.type in ("binary_expression", "concatenated_string"):
                for child in node.children:
                    result = _find_string(child)
                    if result:
                        return result

            return None

        # Search through argument children for a string
        for child in args_node.children:
            result = _find_string(child)
            if result:
                return result

        return None


# ── Code Indexer (Orchestrator) ──────────────────────────────────

class CodeIndexer:
    """Orchestrates fetching files, parsing, and building the CodeIndex."""

    def __init__(self, github_client=None, parser: ASTParser | None = None):
        self.github = github_client
        self.parser = parser or ASTParser()
        self._settings = get_settings()

    def _list_local_source_files(self, local_root: str) -> list[dict]:
        """Paths relative to repo root (posix-style), with size in bytes."""
        max_bytes = self._settings.AST_INDEX_MAX_FILE_SIZE_KB * 1024
        base = Path(local_root).resolve()
        out: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(local_root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                ext = os.path.splitext(fn)[1]
                if ext not in ASTParser.SUPPORTED_EXTENSIONS:
                    continue
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                except OSError:
                    continue
                if st.st_size > max_bytes:
                    continue
                try:
                    rel = full.resolve().relative_to(base)
                except ValueError:
                    continue
                out.append({"path": rel.as_posix(), "size": st.st_size})
        out.sort(key=lambda x: x["path"])
        return out

    def build_index(
        self,
        repo_full_name: str,
        commit_sha: str,
        *,
        local_root: str | None = None,
    ) -> CodeIndexData:
        """Build a complete code index from GitHub blobs or a local clone."""
        sha_short = commit_sha[:8] if commit_sha else "?"
        if local_root:
            logger.info(
                "Building code index from local tree %s for %s @ %s",
                local_root, repo_full_name, sha_short,
            )
            source_files = self._list_local_source_files(local_root)
        else:
            if not self.github:
                raise IndexingError(
                    "GitHub client is required when not using local_root",
                    detail=None,
                )
            logger.info("Building code index for %s @ %s", repo_full_name, sha_short)
            try:
                tree = self.github.list_tree(repo_full_name, commit_sha)
            except Exception as e:
                raise IndexingError(
                    f"Failed to fetch file tree for {repo_full_name}",
                    detail=str(e),
                ) from e
            source_files = [
                f for f in tree
                if os.path.splitext(f["path"])[1] in ASTParser.SUPPORTED_EXTENSIONS
                and (f.get("size") or 0)
                <= self._settings.AST_INDEX_MAX_FILE_SIZE_KB * 1024
            ]

        if len(source_files) > self._settings.AST_INDEX_MAX_FILES:
            logger.warning(
                "Repo %s has %d source files, capping at %d",
                repo_full_name, len(source_files), self._settings.AST_INDEX_MAX_FILES,
            )
            source_files = source_files[: self._settings.AST_INDEX_MAX_FILES]

        all_functions: list[FunctionInfo] = []
        all_log_calls: list[LogCallInfo] = []
        language_counts: dict[str, int] = {}
        errors = 0
        base_path = Path(local_root).resolve() if local_root else None

        _prev_recursion = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(max(_prev_recursion, 25_000))
            for file_info in source_files:
                path = file_info["path"]
                ext = os.path.splitext(path)[1]
                lang = ext.lstrip(".")

                try:
                    if local_root and base_path is not None:
                        full_file = (base_path / path).resolve()
                        try:
                            full_file.relative_to(base_path)
                        except ValueError:
                            logger.warning("Skipping path outside clone root: %s", path)
                            errors += 1
                            continue
                        with open(
                            full_file, "r", encoding="utf-8", errors="replace"
                        ) as fh:
                            content = fh.read()
                    else:
                        content = self.github.get_file_contents(
                            repo_full_name, path, ref=commit_sha
                        )
                except Exception as e:
                    logger.warning("Failed to read %s: %s", path, e)
                    errors += 1
                    continue

                try:
                    functions, log_calls = self.parser.parse_file(content, path)
                    all_functions.extend(functions)
                    all_log_calls.extend(log_calls)
                    language_counts[lang] = language_counts.get(lang, 0) + 1
                except RecursionError:
                    logger.warning(
                        "Recursion depth exceeded parsing %s — skipping file", path
                    )
                    errors += 1
                    continue
                except ASTParseError as e:
                    logger.warning("Failed to parse %s: %s", path, e.message)
                    errors += 1
                    continue
        finally:
            sys.setrecursionlimit(_prev_recursion)

        call_graph = self._build_call_graph(all_functions)
        reverse_graph = self._build_reverse_graph(call_graph)
        log_line_map = self._build_log_line_map(all_log_calls, all_functions)

        index = CodeIndexData(
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            functions=all_functions,
            log_calls=all_log_calls,
            call_graph=call_graph,
            reverse_call_graph=reverse_graph,
            log_line_map=log_line_map,
            language_breakdown=language_counts,
        )

        logger.info(
            "Code index built: %d functions, %d log calls, %d files parsed, %d errors",
            len(all_functions), len(all_log_calls),
            sum(language_counts.values()), errors,
        )
        return index

    @staticmethod
    def _build_call_graph(functions: list[FunctionInfo]) -> dict[str, list[str]]:
        """Build forward call graph: func → [functions it calls]."""
        known = {f.name for f in functions}
        graph: dict[str, list[str]] = {}
        for func in functions:
            # Only include edges to known functions
            graph[func.name] = [c for c in func.calls if c in known]
        return graph

    @staticmethod
    def _build_reverse_graph(call_graph: dict[str, list[str]]) -> dict[str, list[str]]:
        """Build reverse call graph: func → [functions that call it]."""
        reverse: dict[str, list[str]] = {}
        for caller, callees in call_graph.items():
            for callee in callees:
                if callee not in reverse:
                    reverse[callee] = []
                if caller not in reverse[callee]:
                    reverse[callee].append(caller)
        return reverse

    @staticmethod
    def _build_log_line_map(
        log_calls: list[LogCallInfo], functions: list[FunctionInfo]
    ) -> dict[str, SourceLocation]:
        """Build mapping from log string → source location."""
        func_map = {}
        for f in functions:
            func_map[f.name] = f

        log_map: dict[str, SourceLocation] = {}
        for lc in log_calls:
            if lc.log_string and lc.log_string not in log_map:
                log_map[lc.log_string] = SourceLocation(
                    file_path=lc.file_path,
                    line_number=lc.line_number,
                    function_name=lc.function_name or "",
                    qualified_name=(
                        func_map[lc.function_name].qualified_name
                        if lc.function_name and lc.function_name in func_map
                        else None
                    ),
                )
        return log_map
