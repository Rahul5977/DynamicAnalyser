from __future__ import annotations

import ast
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

try:
    import sqlparse  # type: ignore
except ImportError:  # pragma: no cover - optional until deps installed
    sqlparse = None  # type: ignore[misc, assignment]

from .models import (
    DBFinding,
    DBOperation,
    Layer1Result,
    stable_finding_id,
    stable_op_id,
)


_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b",
    re.IGNORECASE,
)
_DJANGO_MODEL_CLASS_RE = re.compile(r"^[A-Z][a-zA-Z0-9_]*$")


@dataclass
class _QuerysetBinding:
    """Per-scope binding for a variable that holds a queryset-like value."""

    var: str
    model_hint: str
    source_kind: str  # "all", "filter", "query", "execute", "other"
    has_select_related: bool
    has_prefetch_related: bool
    line: int
    op_id_hint: str


@dataclass
class _LoopFrame:
    iter_targets: list[str]
    over_var: str | None  # name of iterable variable (for `for x in users`)
    source_kind: str  # "all", "filter", "other"
    loop_var: str  # first target
    outer_has_select_related: bool = False
    outer_has_prefetch_related: bool = False


def _resolve_path(repo_root: str, target: str) -> str:
    if os.path.isabs(target):
        return target
    return os.path.normpath(os.path.join(repo_root, target))


def _looks_like_sql(text: str) -> bool:
    if not text or not _SQL_KEYWORD_RE.search(text):
        return False
    if sqlparse is not None:
        try:
            stmt = sqlparse.parse(text.strip())[0]
            return stmt.get_type() in ("SELECT", "INSERT", "UPDATE", "DELETE", "UNKNOWN") or bool(
                _SQL_KEYWORD_RE.search(text)
            )
        except Exception:
            return bool(_SQL_KEYWORD_RE.search(text))
    return bool(_SQL_KEYWORD_RE.search(text))


def _snippet(lines: list[str], lineno: int, end_lineno: int | None = None) -> str:
    end = end_lineno or lineno
    i0 = max(0, lineno - 1)
    i1 = min(len(lines), end)
    return "\n".join(lines[i0:i1])


def _detect_file_framework_py(source: str) -> tuple[str, set[str]]:
    detected: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unknown", detected

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith("django.db") or name == "django":
                    detected.add("django")
                if name.startswith("sqlalchemy"):
                    detected.add("sqlalchemy")
                if name in ("psycopg2", "psycopg", "sqlite3", "pymysql", "MySQLdb"):
                    detected.add("raw_sql")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("django.db") or mod == "django.db":
                detected.add("django")
            if mod.startswith("sqlalchemy") or mod == "sqlalchemy":
                detected.add("sqlalchemy")
            if mod.startswith("prisma") or mod == "prisma":
                detected.add("prisma")
            if "cursor" in mod and "db" in mod:
                pass

    if not detected:
        if re.search(r"\bcursor\.execute\b", source):
            detected.add("raw_sql")
        return "unknown", detected
    if len(detected) == 1:
        return next(iter(detected)), detected
    # prefer explicit ORM over raw when both fire (e.g. django + psycopg2 in tests)
    for prefer in ("django", "sqlalchemy", "prisma", "typeorm"):
        if prefer in detected:
            return prefer, detected
    return "raw_sql", detected


def _detect_file_framework_js(source: str) -> tuple[str, set[str]]:
    detected: set[str] = set()
    if re.search(r"@prisma/client|from\s+['\"]prisma['\"]|PrismaClient", source):
        detected.add("prisma")
    if re.search(r"typeorm|from\s+['\"]typeorm['\"]", source):
        detected.add("typeorm")
    if re.search(r"cursor\.execute|pg\.query|client\.query\(", source):
        detected.add("raw_sql")
    if not detected:
        return "unknown", detected
    return next(iter(detected)), detected


def _django_chain_parts(
    call: ast.Call,
) -> tuple[list[str], ast.Call]:
    """
    Flatten Attribute/Call chain for Django style: M.objects.filter().all()
    Returns (attrs_from outer call to root, innermost Call node)
    """
    parts: list[str] = []
    cur: ast.AST = call
    inner = call
    while isinstance(cur, ast.Call):
        inner = cur
        fn = cur.func
        if isinstance(fn, ast.Attribute):
            parts.append(fn.attr)
            cur = fn.value
        else:
            break
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = getattr(cur, "value", None)  # type: ignore[arg-type]
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return parts, inner


def _django_model_from_chain(parts: list[str]) -> str | None:
    if "objects" not in parts:
        return None
    oi = parts.index("objects")
    if oi == 0:
        return None
    model = parts[oi - 1]
    if _DJANGO_MODEL_CLASS_RE.match(model):
        return model
    return None


def _flatten_django_call(call: ast.Call) -> tuple[str | None, list[str], bool, bool]:
    """
    Inspect outermost Django queryset call; return model, method chain after `objects`,
    has_select_related, has_prefetch_related.
    """
    parts, _inner = _django_chain_parts(call)
    if not parts or "objects" not in parts:
        return None, [], False, False
    model = _django_model_from_chain(parts)
    oi = parts.index("objects")
    methods = parts[oi + 1 :]
    has_sr = "select_related" in methods
    has_pf = "prefetch_related" in methods
    return model, methods, has_sr, has_pf


class _FuncAnalyzer(ast.NodeVisitor):
    def __init__(
        self,
        file_path: str,
        source_lines: list[str],
        orm: str,
        module_fw: str,
    ) -> None:
        self.file_path = file_path
        self.lines = source_lines
        self.orm = orm
        self.module_fw = module_fw
        self.operations: list[DBOperation] = []
        self.findings: list[DBFinding] = []

        self.class_name = ""
        self.function_name = "<module>"
        self._func_args: set[str] = set()
        self._assignments: dict[str, _QuerysetBinding] = {}
        self._loop_stack: list[_LoopFrame] = []
        self._loop_depth = 0

        self._atomic_stack = 0
        self._write_ops: list[tuple[str, int, str, bool]] = []  # (table_hint, lineno, kind, protected)
        self._has_func_atomic_decorator = False
        self._pending_assign_names: list[str] = []

    # --- context managers ---
    @contextmanager
    def _scope_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[None]:
        prev_name = self.function_name
        prev_args = self._func_args
        prev_assign = self._assignments
        self.function_name = node.name
        args: set[str] = set()
        a = node.args
        for n in a.posonlyargs + a.args + a.kwonlyargs:
            args.add(n.arg)
        if a.vararg:
            args.add(a.vararg.arg)
        if a.kwarg:
            args.add(a.kwarg.arg)
        self._func_args = args
        self._assignments = {}
        self._check_atomic_decorator(node)
        try:
            yield
        finally:
            self.function_name = prev_name
            self._func_args = prev_args
            self._assignments = prev_assign

    def _check_atomic_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            if self._is_atomic_decorator(dec):
                self._has_func_atomic_decorator = True
                break

    def _is_atomic_decorator(self, dec: ast.AST) -> bool:
        # @transaction.atomic
        if isinstance(dec, ast.Attribute):
            if dec.attr == "atomic":
                base = dec.value
                if isinstance(base, ast.Name) and base.id == "transaction":
                    return True
                if isinstance(base, ast.Attribute) and base.attr == "transaction":
                    return True
        if isinstance(dec, ast.Call):
            return self._is_atomic_decorator(dec.func)
        return False

    @contextmanager
    def _scope_class(self, name: str) -> Iterator[None]:
        prev = self.class_name
        self.class_name = name
        try:
            yield
        finally:
            self.class_name = prev

    @contextmanager
    def _loop_context(self, frame: _LoopFrame) -> Iterator[None]:
        self._loop_stack.append(frame)
        self._loop_depth += 1
        try:
            yield
        finally:
            self._loop_stack.pop()
            self._loop_depth -= 1

    # --- helpers ---
    def _add_op(
        self,
        *,
        op_type: str,
        table_hint: str,
        lineno: int,
        end_lineno: int | None,
        raw_code: str,
        is_in_loop: bool,
        loop_source_op_id: str = "",
        filter_fields: list[str] | None = None,
        order_fields: list[str] | None = None,
        join_hints: list[str] | None = None,
        select_fields: list[str] | None = None,
        has_select_related: bool = False,
        has_prefetch_related: bool = False,
        is_lazy_load: bool = False,
        raw_sql_fragments: list[str] | None = None,
    ) -> str:
        end = end_lineno or lineno
        oid = stable_op_id(self.file_path, lineno, raw_code.strip())
        op = DBOperation(
            op_id=oid,
            op_type=op_type,
            orm_framework=self.orm,
            table_hint=table_hint,
            filter_fields=filter_fields or [],
            order_fields=order_fields or [],
            join_hints=join_hints or [],
            select_fields=select_fields or [],
            is_in_loop=is_in_loop,
            loop_var_source_op_id=loop_source_op_id,
            has_select_related=has_select_related,
            has_prefetch_related=has_prefetch_related,
            is_lazy_load=is_lazy_load,
            raw_sql_fragments=raw_sql_fragments or [],
            file_path=self.file_path,
            line_number=lineno,
            end_line_number=end,
            function_name=self.function_name,
            class_name=self.class_name,
            raw_code=raw_code.strip(),
        )
        self.operations.append(op)
        return oid

    def _add_finding(
        self,
        *,
        category: str,
        severity: str,
        confidence: str,
        lineno: int,
        end: int | None,
        title: str,
        description: str,
        evidence: str,
        fix_code: str,
        fix_description: str,
        estimated_impact: str,
        related_op_ids: list[str] | None = None,
        suffix: str = "",
    ) -> None:
        fid = stable_finding_id(category, self.file_path, lineno, suffix)
        self.findings.append(
            DBFinding(
                finding_id=fid,
                layer=1,
                category=category,
                severity=severity,
                confidence=confidence,
                file_path=self.file_path,
                line_number=lineno,
                end_line_number=end or lineno,
                function_name=self.function_name,
                title=title,
                description=description,
                evidence=evidence,
                fix_code=fix_code,
                fix_description=fix_description,
                estimated_impact=estimated_impact,
                related_op_ids=related_op_ids or [],
            )
        )

    def _write_protected(self) -> bool:
        return self._atomic_stack > 0 or self._has_func_atomic_decorator

    def _attach_op_to_pending_bindings(self, lineno: int, oid: str) -> None:
        for name in self._pending_assign_names:
            b = self._assignments.get(name)
            if b and b.line == lineno and not b.op_id_hint:
                b.op_id_hint = oid

    def _outer_loop_select_related_active(self) -> bool:
        if not self._loop_stack:
            return False
        frame = self._loop_stack[-1]
        if frame.outer_has_select_related:
            return True
        if frame.over_var and frame.over_var in self._assignments:
            return self._assignments[frame.over_var].has_select_related
        return False

    def _outer_loop_prefetch_active(self) -> bool:
        if not self._loop_stack:
            return False
        frame = self._loop_stack[-1]
        if frame.outer_has_prefetch_related:
            return True
        if frame.over_var and frame.over_var in self._assignments:
            return self._assignments[frame.over_var].has_prefetch_related
        return False

    def _maybe_lazy_fk_attribute(self, node: ast.Attribute) -> None:
        if not self._loop_stack or not self._loop_depth:
            return
        if not isinstance(node.value, ast.Name):
            return
        if node.value.id != self._loop_stack[-1].loop_var:
            return
        if node.attr in {"pk", "id", "save", "delete"}:
            return
        if self._outer_loop_select_related_active():
            return
        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
        self._add_finding(
            category="orm_missing_select_related",
            severity="HIGH",
            confidence="MEDIUM",
            lineno=node.lineno,
            end=getattr(node, "end_lineno", None),
            title="FK traversal in loop without select_related",
            description=(
                "Related object accessed on a loop variable; use `select_related` on the outer queryset."
            ),
            evidence=raw,
            fix_code=(
                "# BEFORE:\n"
                "for user in User.objects.all():\n"
                "    print(user.profile.bio)\n\n"
                "# AFTER (select_related):\n"
                "for user in User.objects.select_related('profile').all():\n"
                "    print(user.profile.bio)\n"
            ),
            fix_description="Add `.select_related(...)` for forward FK fields used in the loop.",
            estimated_impact="N+1 queries → 1–2 queries",
            suffix=f"selrel-{node.lineno}-{node.attr}",
        )
        self._add_finding(
            category="n_plus_one",
            severity="MEDIUM",
            confidence="MEDIUM",
            lineno=node.lineno,
            end=getattr(node, "end_lineno", None),
            title="Potential N+1 from lazy load",
            description="Attribute access on a model instance inside a loop may trigger extra queries.",
            evidence=raw,
            fix_code=(
                "# BEFORE:\n"
                "for user in User.objects.all():\n"
                "    print(user.profile.bio)\n\n"
                "# AFTER:\n"
                "for user in User.objects.select_related('profile').all():\n"
                "    print(user.profile.bio)\n"
            ),
            fix_description="Use select_related/prefetch_related as appropriate.",
            estimated_impact="Fewer round-trips to DB",
            suffix=f"n1-lazy-{node.lineno}",
        )

    # --- visit ---
    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        with self._scope_class(node.name):
            self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        with self._scope_function(node):
            self._analyze_function_body(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        with self._scope_function(node):
            self._analyze_function_body(node)
        return node

    def _analyze_function_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._has_func_atomic_decorator = False
        self._check_atomic_decorator(node)
        self._write_ops.clear()

        for child in node.body:
            self.visit(child)

        self._post_function_transaction_rules()

    def visit_Module(self, node: ast.Module) -> Any:
        self.function_name = "<module>"
        self.class_name = ""
        self._func_args = set()
        self._assignments = {}
        for child in node.body:
            self.visit(child)
        return node

    def visit_Assign(self, node: ast.Assign) -> Any:
        prev = self._pending_assign_names
        self._pending_assign_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        self._track_queryset_assign(node)
        self._maybe_all_python_filter_pattern(node)
        self.generic_visit(node)
        self._pending_assign_names = prev
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if node.value is not None:
            prev = self._pending_assign_names
            tgt = node.target
            self._pending_assign_names = [tgt.id] if isinstance(tgt, ast.Name) else []
            fake = ast.Assign(targets=[node.target], value=node.value)
            fake.lineno = node.lineno
            fake.end_lineno = getattr(node, "end_lineno", node.lineno)
            self._track_queryset_assign(fake)
            self.generic_visit(node)
            self._pending_assign_names = prev
            return node
        self.generic_visit(node)
        return node

    def _track_queryset_assign(self, node: ast.Assign) -> None:
        value = node.value
        if not isinstance(value, ast.Call):
            return
        model2, meths, has_sr2, has_pf2 = _flatten_django_call(value)
        if not model2:
            return
        outer_method = meths[-1] if meths else "query"
        sk = "all" if outer_method == "all" else ("filter" if outer_method == "filter" else "other")
        for t in node.targets:
            if isinstance(t, ast.Name):
                self._assignments[t.id] = _QuerysetBinding(
                    var=t.id,
                    model_hint=model2,
                    source_kind=sk,
                    has_select_related=has_sr2,
                    has_prefetch_related=has_pf2,
                    line=node.lineno,
                    op_id_hint="",
                )

    def _current_loop_source_op_id(self) -> str:
        if not self._loop_stack:
            return ""
        frame = self._loop_stack[-1]
        if frame.over_var and frame.over_var in self._assignments:
            return self._assignments[frame.over_var].op_id_hint
        return ""

    def _maybe_all_python_filter_pattern(self, node: ast.Assign) -> None:
        value = node.value
        if not isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return
        lc = value
        if len(lc.generators) != 1:
            return
        gen = lc.generators[0]
        if gen.ifs:
            iter_ = gen.iter
            if isinstance(iter_, ast.Call):
                _m, meths, _, _ = _flatten_django_call(iter_)
                if meths and meths[-1] == "all":
                    # binding from iter side — find model
                    model, _, _, _ = _flatten_django_call(iter_)
                    if model:
                        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
                        self._add_finding(
                            category="orm_all_no_filter",
                            severity="MEDIUM",
                            confidence="MEDIUM",
                            lineno=node.lineno,
                            end=getattr(node, "end_lineno", None),
                            title="Python-side filter after .all()",
                            description="Result of `.all()` is filtered in Python; prefer `.filter()` in the database.",
                            evidence=raw,
                            fix_code=(
                                "# BEFORE:\n"
                                "active_users = [u for u in User.objects.all() if u.is_active]\n\n"
                                "# AFTER:\n"
                                "active_users = list(User.objects.filter(is_active=True))\n"
                            ),
                            fix_description="Push predicates into the ORM query to reduce rows loaded.",
                            estimated_impact="Fewer rows deserialized; lower memory and latency",
                            suffix=f"all-filter-{node.lineno}",
                        )

    def visit_For(self, node: ast.For) -> Any:
        self._visit_loop(node)
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> Any:
        self._visit_loop(node)
        return node

    def visit_While(self, node: ast.While) -> Any:
        frame = _LoopFrame(
            iter_targets=[],
            over_var=None,
            source_kind="other",
            loop_var="",
            outer_has_select_related=False,
            outer_has_prefetch_related=False,
        )
        with self._loop_context(frame):
            self.generic_visit(node)
        return node

    def _visit_loop(self, node: ast.For | ast.AsyncFor) -> Any:
        over_name: str | None = None
        sk = "other"
        ohsr = False
        ohpf = False
        if isinstance(node.iter, ast.Name):
            over_name = node.iter.id
            b = self._assignments.get(over_name)
            if b:
                sk = b.source_kind
                ohsr = b.has_select_related
                ohpf = b.has_prefetch_related
        elif isinstance(node.iter, ast.Call):
            model_i, meths_i, sr_i, pf_i = _flatten_django_call(node.iter)
            if model_i and meths_i:
                last_i = meths_i[-1]
                sk = "all" if last_i == "all" else ("filter" if last_i == "filter" else "other")
                ohsr = sr_i
                ohpf = pf_i
        targets: list[str] = []
        if isinstance(node.target, ast.Name):
            targets = [node.target.id]
            lv = node.target.id
        elif isinstance(node.target, ast.Tuple):
            targets = [n.id for n in node.target.elts if isinstance(n, ast.Name)]
            lv = targets[0] if targets else ""
        else:
            lv = ""
        frame = _LoopFrame(
            iter_targets=targets,
            over_var=over_name,
            source_kind=sk,
            loop_var=lv,
            outer_has_select_related=ohsr,
            outer_has_prefetch_related=ohpf,
        )
        self.visit(node.iter)
        with self._loop_context(frame):
            for child in node.body:
                self.visit(child)
            for child in node.orelse:
                self.visit(child)
        return node

    def visit_Call(self, node: ast.Call) -> Any:
        self._inspect_call_db(node)
        self._inspect_transaction_commit_in_loop(node)
        self.generic_visit(node)
        return node

    def _inspect_call_db(self, node: ast.Call) -> None:
        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
        in_loop = self._loop_depth > 0

        model, meths, has_sr, has_pf = _flatten_django_call(node)
        if model and meths:
            last = meths[-1]
            if last in {"all", "filter", "get", "first", "count", "exists", "create", "update", "delete", "save"}:
                if last == "count":
                    op_type = "count"
                elif last == "exists":
                    op_type = "exists"
                elif last == "create":
                    op_type = "insert"
                elif last == "update":
                    op_type = "update"
                elif last == "delete":
                    op_type = "delete"
                else:
                    op_type = "query"

                oid = self._add_op(
                    op_type=op_type,
                    table_hint=model,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    raw_code=raw,
                    is_in_loop=in_loop,
                    loop_source_op_id=self._current_loop_source_op_id(),
                    has_select_related=has_sr,
                    has_prefetch_related=has_pf,
                )
                self._attach_op_to_pending_bindings(node.lineno, oid)

                if in_loop and last == "count":
                    self._add_finding(
                        category="orm_count_in_loop",
                        severity="HIGH",
                        confidence="HIGH",
                        lineno=node.lineno,
                        end=getattr(node, "end_lineno", None),
                        title=".count() inside a loop",
                        description="Calling `.count()` in a loop can explode query volume.",
                        evidence=raw,
                        fix_code=(
                            "# BEFORE:\n"
                            "for user in users:\n"
                            "    n = user.orders.count()\n\n"
                            "# AFTER (annotate on outer queryset):\n"
                            "from django.db.models import Count\n"
                            "users = User.objects.annotate(order_count=Count('orders'))\n"
                            "for user in users:\n"
                            "    n = user.order_count\n"
                        ),
                        fix_description="Pre-aggregate with annotate/subquery on the outer query.",
                        estimated_impact="O(n) extra COUNT queries → O(1) queries",
                        related_op_ids=[oid],
                        suffix=f"count-loop-{node.lineno}",
                    )

                if in_loop and op_type == "query" and last not in {"count", "exists"}:
                    self._maybe_n_plus_one(node, model, meths, has_sr, oid)

            if in_loop and meths and meths[-1] in {"all", "filter"}:
                _parts, inner = _django_chain_parts(node)
                fn = inner.func
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Attribute):
                    left = fn.value.value
                    base_attr = fn.value.attr
                    if isinstance(left, ast.Name) and self._loop_stack and left.id == self._loop_stack[-1].loop_var:
                        if base_attr.endswith("_set") or base_attr.endswith("s"):
                            if not self._outer_loop_prefetch_active():
                                self._add_finding(
                                    category="orm_missing_prefetch_related",
                                    severity="HIGH",
                                    confidence="MEDIUM",
                                    lineno=node.lineno,
                                    end=getattr(node, "end_lineno", None),
                                    title="Reverse relation accessed in loop without prefetch",
                                    description="Prefetch reverse relations to avoid N+1 on `related_set.all()`.",
                                    evidence=raw,
                                    fix_code=(
                                        "# BEFORE:\n"
                                        "for order in orders:\n"
                                        "    for li in order.lines.all():\n"
                                        "        ...\n\n"
                                        "# AFTER:\n"
                                        "for order in Order.objects.prefetch_related('lines').all():\n"
                                        "    for li in order.lines.all():\n"
                                        "        ...\n"
                                    ),
                                    fix_description="Add `.prefetch_related(...)` on the outer queryset.",
                                    estimated_impact="Many queries → 2 queries",
                                    suffix=f"prefetch-{node.lineno}",
                                )

        w = self._django_write_table(node)
        if w:
            self._write_ops.append((w, node.lineno, "django", self._write_protected()))

    def _maybe_n_plus_one(
        self,
        node: ast.Call,
        model: str,
        meths: list[str],
        has_sr: bool,
        inner_oid: str,
    ) -> None:
        if not self._loop_stack:
            return
        frame = self._loop_stack[-1]
        # Inner ORM call inside loop over queryset — classic N+1
        outer_sk = frame.source_kind
        severity = "CRITICAL" if outer_sk == "all" else "HIGH"
        if outer_sk == "other":
            severity = "HIGH"
        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
        self._add_finding(
            category="n_plus_one",
            severity=severity,
            confidence="HIGH" if severity == "CRITICAL" else "MEDIUM",
            lineno=node.lineno,
            end=getattr(node, "end_lineno", None),
            title="N+1 query pattern: DB access inside a loop",
            description="A database query runs inside a loop over another query's results.",
            evidence=raw,
            fix_code=(
                "# BEFORE:\n"
                "for user in User.objects.all():\n"
                "    Order.objects.filter(user=user).first()\n\n"
                "# AFTER (example: prefetch or join):\n"
                "users = User.objects.prefetch_related('orders')\n"
                "for user in users:\n"
                "    first_order = user.orders.first()\n"
            ),
            fix_description="Batch with prefetch_related/select_related or reshape with join/subqueries.",
            estimated_impact="~1 + N queries → O(1) queries",
            related_op_ids=[inner_oid, self._current_loop_source_op_id()],
            suffix=f"n1-{node.lineno}",
        )

    def _django_write_table(self, node: ast.Call) -> str | None:
        model, meths, _, _ = _flatten_django_call(node)
        if not model or not meths:
            return None
        last = meths[-1]
        if last in {"create", "bulk_create", "update", "delete"}:
            return model
        return None

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        self._maybe_lazy_fk_attribute(node)
        if isinstance(node.value, ast.Name) and node.attr == "save":
            self._write_ops.append(("", node.lineno, "save", self._write_protected()))
        self.generic_visit(node)
        return node

    def visit_Try(self, node: ast.Try) -> Any:
        commit_lines: list[int] = []
        for st in node.body:
            for sub in ast.walk(st):
                if isinstance(sub, ast.Call):
                    if self._is_commit_call(sub):
                        commit_lines.append(sub.lineno)
        has_rollback = False
        for handler in node.handlers:
            for sub in ast.walk(handler):
                if isinstance(sub, ast.Call) and self._is_rollback_call(sub):
                    has_rollback = True
        for ln in commit_lines:
            if not has_rollback:
                raw = _snippet(self.lines, ln, ln)
                self._add_finding(
                    category="transaction_no_rollback",
                    severity="MEDIUM",
                    confidence="LOW",
                    lineno=ln,
                    end=ln,
                    title="commit() without matching rollback() in except",
                    description="A try/except around commit should rollback on failure.",
                    evidence=raw,
                    fix_code=(
                        "# BEFORE:\n"
                        "try:\n"
                        "    session.commit()\n"
                        "except Exception:\n"
                        "    pass\n\n"
                        "# AFTER:\n"
                        "try:\n"
                        "    session.commit()\n"
                        "except Exception:\n"
                        "    session.rollback()\n"
                        "    raise\n"
                    ),
                    fix_description="Ensure rollback in except before swallowing or re-raising.",
                    estimated_impact="Safer transactional state",
                    suffix=f"rollback-{ln}",
                )
        self.generic_visit(node)
        return node

    def _is_commit_call(self, node: ast.Call) -> bool:
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "commit":
            return True
        return False

    def _is_rollback_call(self, node: ast.Call) -> bool:
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "rollback":
            return True
        return False

    def visit_With(self, node: ast.With) -> Any:
        is_atomic = False
        for item in node.items:
            if self._is_atomic_with(item.context_expr):
                is_atomic = True
        if is_atomic:
            self._atomic_stack += 1
            try:
                for child in node.body:
                    self.visit(child)
                for child in node.orelse:
                    self.visit(child)
            finally:
                self._atomic_stack -= 1
            return node
        self.generic_visit(node)
        return node

    def _is_atomic_with(self, expr: ast.AST) -> bool:
        # transaction.atomic():
        if isinstance(expr, ast.Call):
            fn = expr.func
            if isinstance(fn, ast.Attribute) and fn.attr == "atomic":
                v = fn.value
                if isinstance(v, ast.Name) and v.id == "transaction":
                    return True
        if isinstance(expr, ast.Attribute) and expr.attr == "atomic":
            return True
        # sqlalchemy begin
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Attribute) and expr.func.attr in {"begin", "atomic"}:
                return True
        return False

    def _inspect_transaction_commit_in_loop(self, node: ast.Call) -> None:
        if self._loop_depth == 0:
            return
        if self._is_commit_call(node):
            raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
            self._add_finding(
                category="transaction_commit_in_loop",
                severity="HIGH",
                confidence="MEDIUM",
                lineno=node.lineno,
                end=getattr(node, "end_lineno", None),
                title="commit() inside a loop",
                description="Committing inside a loop is slow and can fragment transactions.",
                evidence=raw,
                fix_code=(
                    "# BEFORE:\n"
                    "for row in rows:\n"
                    "    session.add(row)\n"
                    "    session.commit()\n\n"
                    "# AFTER:\n"
                    "for row in rows:\n"
                    "    session.add(row)\n"
                    "session.commit()\n"
                ),
                fix_description="Batch work and commit once after the loop.",
                estimated_impact="Fewer fsyncs; faster throughput",
                suffix=f"commit-loop-{node.lineno}",
            )

    def _post_function_transaction_rules(self) -> None:
        if self._has_func_atomic_decorator:
            return
        unprotected = [w for w in self._write_ops if not w[3]]
        tables = {t for t, _, _, _ in unprotected if t}
        if len(tables) > 1:
            sev = "HIGH" if len(tables) > 2 else "MEDIUM"
            lineno = unprotected[0][1] if unprotected else 1
            raw = _snippet(self.lines, lineno, lineno)
            self._add_finding(
                category="transaction_missing_atomic",
                severity=sev,
                confidence="MEDIUM",
                lineno=lineno,
                end=lineno,
                title="Multiple table writes without atomic transaction",
                description="Several tables are written in one flow without `transaction.atomic()` / session transaction.",
                evidence=raw,
                fix_code=(
                    "# BEFORE:\n"
                    "order = Order.objects.create(...)\n"
                    "inventory.quantity -= 1\n"
                    "inventory.save()\n\n"
                    "# AFTER:\n"
                    "from django.db import transaction\n"
                    "with transaction.atomic():\n"
                    "    order = Order.objects.create(...)\n"
                    "    inventory.quantity -= 1\n"
                    "    inventory.save()\n"
                ),
                fix_description="Group multi-table updates in a single atomic block.",
                estimated_impact="Consistent commits; fewer partial failure states",
                suffix=f"multi-{lineno}",
            )


class _RawSqlVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, lines: list[str], orm: str) -> None:
        self.file_path = file_path
        self.lines = lines
        self.orm = orm
        self.findings: list[DBFinding] = []
        self.function_name = "<module>"
        self.class_name = ""
        self._func_args: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        prev = self.class_name
        self.class_name = node.name
        self.generic_visit(node)
        self.class_name = prev
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        return self._fn(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        return self._fn(node)

    def _fn(self, node: ast.FunctionDef) -> Any:
        prev = self.function_name
        prev_args = self._func_args
        self.function_name = node.name
        args: set[str] = set()
        a = node.args
        for n in a.posonlyargs + a.args + a.kwonlyargs:
            args.add(n.arg)
        if a.vararg:
            args.add(a.vararg.arg)
        if a.kwarg:
            args.add(a.kwarg.arg)
        self._func_args = args
        self.generic_visit(node)
        self.function_name = prev
        self._func_args = prev_args
        return node

    def visit_JoinedStr(self, node: ast.JoinedStr) -> Any:
        # approximate f-string content
        chunks: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                chunks.append(v.value)
            else:
                chunks.append("X")
        text = "".join(chunks)
        if _looks_like_sql(text):
            raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
            requestish = "X" in chunks  # had interpolation
            sev = "CRITICAL" if requestish else "HIGH"
            self.findings.append(
                DBFinding(
                    finding_id=stable_finding_id("raw_sql_injection", self.file_path, node.lineno, "f"),
                    layer=1,
                    category="raw_sql_injection",
                    severity=sev,
                    confidence="HIGH" if requestish else "MEDIUM",
                    file_path=self.file_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    function_name=self.function_name,
                    title="SQL built with f-string",
                    description="Interpolating values into SQL invites injection; use parameterized queries.",
                    evidence=raw,
                    fix_code=(
                        "# BEFORE:\n"
                        'sql = f"SELECT * FROM users WHERE id = {uid}"\n'
                        "cursor.execute(sql)\n\n"
                        "# AFTER:\n"
                        'cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))\n'
                    ),
                    fix_description="Bind parameters instead of string interpolation.",
                    estimated_impact="Eliminates direct SQL injection from this pattern",
                )
            )
        self.generic_visit(node)
        return node

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        if isinstance(node.op, ast.Mod):
            left = node.left
            right = node.right
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                s = left.value
                if _looks_like_sql(s) and ("%s" in s or "%d" in s):
                    if not self._is_safe_rhs(right):
                        self._fmt_finding(node, "%-format SQL", "HIGH")
        if isinstance(node.op, ast.Add):
            parts = self._collect_str_add(node)
            if parts and _looks_like_sql("".join([p for p in parts if p != "__VAR__"])):
                if "__VAR__" in parts:
                    self._fmt_finding(node, "SQL string concatenation", "HIGH")
        self.generic_visit(node)
        return node

    def _collect_str_add(self, node: ast.BinOp) -> list[str] | None:
        if not isinstance(node.op, ast.Add):
            return None
        out: list[str] = []
        stack: list[ast.AST] = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Add):
                stack.append(cur.right)
                stack.append(cur.left)
            elif isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                out.append(cur.value)
            elif isinstance(cur, ast.Name):
                out.append("__VAR__")
            else:
                return None
        return out

    def _is_safe_rhs(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Tuple):
            return all(isinstance(elt, ast.Constant) for elt in node.elts)
        return isinstance(node, ast.Constant)

    def _fmt_finding(self, node: ast.BinOp, title: str, severity: str) -> None:
        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
        self.findings.append(
            DBFinding(
                finding_id=stable_finding_id("raw_sql_injection", self.file_path, node.lineno, title),
                layer=1,
                category="raw_sql_injection",
                severity=severity,
                confidence="MEDIUM",
                file_path=self.file_path,
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", node.lineno),
                function_name=self.function_name,
                title=title,
                description="User-controlled or dynamic SQL construction detected.",
                evidence=raw,
                fix_code=(
                    "# BEFORE:\n"
                    'query = "SELECT * FROM t WHERE id = %s" % user_id\n\n'
                    "# AFTER:\n"
                    'cursor.execute("SELECT * FROM t WHERE id = %s", (user_id,))\n'
                ),
                fix_description="Use DB-API parameter binding.",
                estimated_impact="Reduces injection risk",
            )
        )

    def visit_Call(self, node: ast.Call) -> Any:
        # .format on SQL str
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            val = node.func.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                s = val.value
                if _looks_like_sql(s) and ("{" in s):
                    if any(not isinstance(a, ast.Constant) for a in node.args) or any(
                        k.value is not None and not isinstance(k.value, ast.Constant) for k in node.keywords
                    ):
                        self._call_finding(node, "SQL .format() with variables", "HIGH")
        # sqlalchemy text()
        if isinstance(node.func, ast.Name) and node.func.id == "text":
            if node.args and isinstance(node.args[0], ast.BinOp):
                self._call_finding(node, "sqlalchemy.text() with string concatenation", "HIGH")
        # cursor.execute(sql) non-literal
        if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            if node.args:
                arg0 = node.args[0]
                if not (isinstance(arg0, ast.Constant) and isinstance(arg0.value, str)):
                    raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
                    self.findings.append(
                        DBFinding(
                            finding_id=stable_finding_id("raw_sql_injection", self.file_path, node.lineno, "exec"),
                            layer=1,
                            category="raw_sql_injection",
                            severity="HIGH",
                            confidence="LOW",
                            file_path=self.file_path,
                            line_number=node.lineno,
                            end_line_number=getattr(node, "end_lineno", node.lineno),
                            function_name=self.function_name,
                            title="cursor.execute() with non-literal SQL",
                            description="Dynamic SQL passed to execute; verify parameterization.",
                            evidence=raw,
                            fix_code=(
                                "# BEFORE:\n"
                                "cursor.execute(sql)\n\n"
                                "# AFTER:\n"
                                'cursor.execute("SELECT ... WHERE id = %s", (id,))\n'
                            ),
                            fix_description="Prefer literal SQL with bound parameters.",
                            estimated_impact="Safer query execution",
                        )
                    )
        self.generic_visit(node)
        return node

    def _call_finding(self, node: ast.Call, title: str, severity: str) -> None:
        raw = _snippet(self.lines, node.lineno, getattr(node, "end_lineno", None))
        self.findings.append(
            DBFinding(
                finding_id=stable_finding_id("raw_sql_injection", self.file_path, node.lineno, title),
                layer=1,
                category="raw_sql_injection",
                severity=severity,
                confidence="MEDIUM",
                file_path=self.file_path,
                line_number=node.lineno,
                end_line_number=getattr(node, "end_lineno", node.lineno),
                function_name=self.function_name,
                title=title,
                description="Dynamic SQL construction via format/text.",
                evidence=raw,
                fix_code="# FIX: use bind parameters\n",
                fix_description="Avoid building SQL from partially controlled strings.",
                estimated_impact="Injection risk reduction",
            )
        )


def _scan_python_file(file_path: str) -> tuple[int, int, list[DBOperation], list[DBFinding], set[str]]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    orm, fw_set = _detect_file_framework_py(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 1, 0, [], [], fw_set

    lines = source.splitlines()
    analyzer = _FuncAnalyzer(file_path, lines, orm if orm != "unknown" else "unknown", orm)
    analyzer.visit(tree)
    rawv = _RawSqlVisitor(file_path, lines, orm)
    rawv.visit(tree)

    fn_count = sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    ops = analyzer.operations
    finds = analyzer.findings + rawv.findings
    return 1, fn_count, ops, finds, fw_set


def _scan_js_file(file_path: str) -> tuple[int, int, list[DBOperation], list[DBFinding], set[str]]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    orm, fw_set = _detect_file_framework_js(source)
    # minimal: no deep AST
    return 1, 0, [], [], fw_set


class Layer1Scanner:
    def __init__(self, repo_root: str, target_files: list[str]) -> None:
        self.repo_root = repo_root
        self.target_files = target_files

    def scan(self) -> Layer1Result:
        operations: list[DBOperation] = []
        findings: list[DBFinding] = []
        frameworks: set[str] = set()
        file_count = 0
        functions_scanned = 0

        for tf in self.target_files:
            path = _resolve_path(self.repo_root, tf)
            if not os.path.isfile(path):
                continue
            file_count += 1
            ext = os.path.splitext(path)[1].lower()
            if ext == ".py":
                fc, fc_fn, ops, finds, fw = _scan_python_file(path)
                functions_scanned += fc_fn
                frameworks |= fw
            elif ext in {".js", ".jsx", ".mjs", ".ts", ".tsx"}:
                fc, fc_fn, ops, finds, fw = _scan_js_file(path)
                frameworks |= fw
            else:
                ops, finds = [], []
            operations.extend(ops)
            findings.extend(finds)

        orm_list = sorted(frameworks)
        return Layer1Result(
            operations=operations,
            findings=findings,
            file_count=file_count,
            functions_scanned=functions_scanned,
            orm_frameworks_detected=orm_list,
        )
