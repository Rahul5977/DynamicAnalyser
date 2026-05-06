from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

_VALID_OP_TYPES = frozenset(
    {"query", "insert", "update", "delete", "count", "exists", "aggregate"}
)
_VALID_ORMS = frozenset(
    {"django", "sqlalchemy", "prisma", "typeorm", "raw_sql", "unknown"}
)
_VALID_SEVERITY = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})
_VALID_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})
_VALID_CRITIQUE = frozenset({"PENDING", "CONFIRMED", "PLAUSIBLE", "DISPUTED"})


@dataclass
class DBOperation:
    """A single database operation detected in the source code."""

    op_id: str  # SHA-256 of file+line+code
    op_type: str  # "query"|"insert"|"update"|"delete"|"count"|"exists"|"aggregate"
    orm_framework: str  # "django"|"sqlalchemy"|"prisma"|"typeorm"|"raw_sql"|"unknown"
    table_hint: str  # inferred table name (from Model class name, empty if unknown)
    filter_fields: list[str]  # columns used in .filter() / WHERE
    order_fields: list[str]  # columns used in .order_by() / ORDER BY
    join_hints: list[str]  # related models accessed via FK traversal
    select_fields: list[str]  # columns explicitly selected (empty = SELECT *)
    is_in_loop: bool  # True if this op is inside a for/while loop
    loop_var_source_op_id: str  # op_id of the query whose result is iterated
    has_select_related: bool  # True if .select_related() is present
    has_prefetch_related: bool  # True if .prefetch_related() is present
    is_lazy_load: bool  # True if FK traversal without select_related
    raw_sql_fragments: list[str]  # any raw SQL strings found
    file_path: str
    line_number: int
    end_line_number: int
    function_name: str
    class_name: str  # model/view class containing this op, empty if module-level
    raw_code: str  # the actual source lines

    def __post_init__(self) -> None:
        if self.op_type not in _VALID_OP_TYPES:
            raise ValueError(f"invalid op_type: {self.op_type!r}")
        if self.orm_framework not in _VALID_ORMS:
            raise ValueError(f"invalid orm_framework: {self.orm_framework!r}")
        if self.line_number < 1:
            raise ValueError("line_number must be >= 1")
        if self.end_line_number < self.line_number:
            raise ValueError("end_line_number must be >= line_number")


@dataclass
class DBFinding:
    """A database issue detected by any layer."""

    finding_id: str
    layer: int  # 1-5
    category: str  # see CATEGORIES below
    severity: str  # "CRITICAL"|"HIGH"|"MEDIUM"|"LOW"|"INFO"
    confidence: str  # "HIGH"|"MEDIUM"|"LOW"
    file_path: str
    line_number: int
    end_line_number: int
    function_name: str
    title: str
    description: str
    evidence: str  # the actual problematic code
    fix_code: str  # the suggested fix (before/after or replacement)
    fix_description: str  # human-readable explanation of the fix
    estimated_impact: str  # "47 queries → 2 queries" or "seq scan 1M rows → index scan ~50 rows"
    related_op_ids: list[str] = field(default_factory=list)
    related_tables: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)  # OWASP / Django docs URLs

    # Critique fields (filled by Council)
    critique_verdict: str = "PENDING"  # "CONFIRMED"|"PLAUSIBLE"|"DISPUTED"
    critique_note: str = ""

    def __post_init__(self) -> None:
        if self.layer not in (1, 2, 3, 4, 5):
            raise ValueError(f"layer must be 1-5, got {self.layer}")
        if self.category not in CATEGORIES:
            raise ValueError(f"invalid category: {self.category!r}")
        if self.severity not in _VALID_SEVERITY:
            raise ValueError(f"invalid severity: {self.severity!r}")
        if self.confidence not in _VALID_CONFIDENCE:
            raise ValueError(f"invalid confidence: {self.confidence!r}")
        if self.critique_verdict not in _VALID_CRITIQUE:
            raise ValueError(f"invalid critique_verdict: {self.critique_verdict!r}")
        if self.line_number < 1:
            raise ValueError("line_number must be >= 1")
        if self.end_line_number < self.line_number:
            raise ValueError("end_line_number must be >= line_number")


# Valid category values:
CATEGORIES = [
    "n_plus_one",  # N+1 query pattern
    "n_plus_one_cross_file",  # N+1 spanning multiple files (Layer 3)
    "raw_sql_injection",  # SQL injection via string formatting
    "orm_all_no_filter",  # .all() with no subsequent filter before iteration
    "orm_count_in_loop",  # .count() called in a loop
    "orm_missing_select_related",  # ForeignKey traversal without select_related
    "orm_missing_prefetch_related",  # Reverse relation without prefetch_related
    "orm_unnecessary_full_object",  # Loading full object when only one field needed
    "orm_queryset_in_serializer",  # DB query inside DRF serializer without prefetch
    "transaction_missing_atomic",  # Multi-table write without transaction
    "transaction_commit_in_loop",  # session.commit() inside a loop
    "transaction_no_rollback",  # commit without rollback in except
    "raw_sql_no_params",  # cursor.execute(sql) without params tuple
    "missing_index",  # filter/order field without index (from Layer 2)
    "missing_composite_index",  # multiple filter fields need composite index
    "fk_no_index",  # ForeignKey column without index
    "fk_no_on_delete",  # ForeignKey without ondelete clause
    "nullable_fk_should_cascade",  # nullable FK that should have CASCADE
    "varchar_on_indexed_col",  # TEXT/VARCHAR on indexed column
    "missing_not_null",  # required field nullable in schema
    "unique_in_code_not_db",  # uniqueness enforced in code not DB
    "migration_breaking_change",  # NOT NULL column without server_default
    "seq_scan_large_table",  # sequential scan on large table (Layer 4)
    "expensive_join",  # join without index on join column (Layer 4)
    "n_plus_one_cost_estimate",  # N+1 with quantified cost (Layer 4)
    "unused_index",  # index never used in production (Layer 5)
    "table_bloat",  # high dead tuple percentage (Layer 5)
    "slow_query_in_prod",  # matches pg_stat_statements (Layer 5)
    "sequence_exhaustion",  # sequence > 80% of max (Layer 5)
    "lock_contention",  # table with frequent lock conflicts (Layer 5)
]


@dataclass
class Layer1Result:
    operations: list[DBOperation]
    findings: list[DBFinding]
    file_count: int
    functions_scanned: int
    orm_frameworks_detected: list[str]

    def __post_init__(self) -> None:
        if self.file_count < 0:
            raise ValueError("file_count must be non-negative")
        if self.functions_scanned < 0:
            raise ValueError("functions_scanned must be non-negative")


def stable_op_id(file_path: str, line_number: int, raw_code: str) -> str:
    payload = f"{file_path}:{line_number}:{raw_code}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def stable_finding_id(category: str, file_path: str, line_number: int, suffix: str = "") -> str:
    payload = f"L1:{category}:{file_path}:{line_number}:{suffix}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()[:32]
