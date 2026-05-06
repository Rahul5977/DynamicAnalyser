"""Static analysis pipeline package."""

from dataclasses import asdict, dataclass, field


@dataclass
class ChunkData:
    id: str
    code: str
    file_path: str
    start_line: int
    end_line: int
    cyclomatic_complexity: int
    halstead_volume: float
    smells: list[str]
    cfg: dict
    imports: list[str]
    resolved_deps: list[str]


@dataclass
class TriageResult:
    chunks: list[ChunkData] = field(default_factory=list)
    adjacency_list: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Finding:
    agent_id: str
    title: str
    severity: str
    confidence: str
    file_path: str
    start_line: int
    end_line: int
    description: str
    evidence: str
    recommendation: str
    critique_verdict: str | None = None
    critique_note: str | None = None


@dataclass
class FindingCard:
    finding: Finding
    fix_snippet: str
    explanation_technical: str
    explanation_manager: str
    explanation_executive: str
    critique_verdict: str
    critique_note: str


@dataclass
class CouncilReport:
    repo_id: str
    job_id: str
    finding_cards: list[FindingCard] = field(default_factory=list)
    architecture_report: dict = field(default_factory=dict)
    critique_log: list[dict] = field(default_factory=list)
    total_duration_ms: int = 0
    agent_errors: list[str] = field(default_factory=list)
    health_score: int = 100

    def to_dict(self) -> dict:
        return asdict(self)
