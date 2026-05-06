from __future__ import annotations

import asyncio
import time

from app.config import get_settings
from app.services.static_analyser import CouncilReport, FindingCard
from app.services.static_analyser.council.architecture_agent import run_architecture_agent
from app.services.static_analyser.council.critique_agent import run_critique_agent
from app.services.static_analyser.council.orchestrator_agent import run_orchestrator_plan
from app.services.static_analyser.council.performance_agent import run_performance_agent
from app.services.static_analyser.council.security_agent import run_security_agent
from app.services.static_analyser.council.synthesis_agent import run_synthesis_agent
from app.services.static_analyser.council.test_coverage_agent import run_test_coverage_agent


def compute_health_score(finding_cards: list) -> int:
    if not finding_cards:
        return 100
    confirmed = [fc for fc in finding_cards if fc.critique_verdict in ("CONFIRMED", "PLAUSIBLE")]
    deductions = sum(
        {
            "CRITICAL": 25,
            "HIGH": 15,
            "MEDIUM": 7,
            "LOW": 2,
            "INFO": 0,
        }.get(fc.finding.severity, 0)
        for fc in confirmed
    )
    return max(0, 100 - deductions)


class CouncilOrchestrator:
    async def run(self, repo_id: str, job_id: str, manifest: dict, triage_result, architecture_report: dict) -> CouncilReport:
        started = time.time()
        agent_errors: list[str] = []

        summary = {
            "chunk_count": len(triage_result.chunks),
            "smell_count": sum(len(c.smells) for c in triage_result.chunks),
            "top_files": sorted({c.file_path for c in triage_result.chunks})[:30],
        }
        plan = run_orchestrator_plan(manifest, summary)
        sec_ids = {x.get("chunk_id") for x in plan.get("security_targets", [])}
        perf_ids = {x.get("chunk_id") for x in plan.get("performance_targets", [])}
        sec_chunks = [c for c in triage_result.chunks if not sec_ids or c.id in sec_ids][:30]
        perf_chunks = [c for c in triage_result.chunks if not perf_ids or c.id in perf_ids][:30]

        async def _run(fn, *args):
            try:
                return await asyncio.to_thread(fn, *args)
            except Exception as e:  # pragma: no cover
                agent_errors.append(str(e))
                return []

        security_findings, perf_findings, arch_findings, test_findings = await asyncio.gather(
            _run(run_security_agent, sec_chunks),
            _run(run_performance_agent, perf_chunks),
            _run(run_architecture_agent, architecture_report),
            _run(run_test_coverage_agent, triage_result.chunks, manifest.get("target_files", [])),
        )

        all_findings = security_findings + perf_findings + arch_findings + test_findings
        serialized_findings = [f.__dict__ for f in all_findings]
        critique_log = run_critique_agent(serialized_findings)

        for row in critique_log:
            idx = row.get("finding_index", -1)
            if 0 <= idx < len(all_findings):
                all_findings[idx].critique_verdict = row.get("verdict", "PLAUSIBLE")
                all_findings[idx].critique_note = row.get("note", "")

        dispute_rate = 0.0
        if critique_log:
            dispute_rate = sum(1 for x in critique_log if x.get("verdict") == "DISPUTED") / len(critique_log)
        settings = get_settings()
        if dispute_rate > 0.6 and settings.STATIC_MAX_REINVESTIGATIONS > 0:
            all_findings.extend(run_security_agent(sec_chunks[:10]))

        synth_inputs = [f.__dict__ for f in all_findings if f.critique_verdict in ("CONFIRMED", "PLAUSIBLE", None)]
        synth_rows = run_synthesis_agent(synth_inputs)
        cards: list[FindingCard] = []
        for row in synth_rows:
            idx = row.get("finding_index", -1)
            if 0 <= idx < len(synth_inputs):
                origin = synth_inputs[idx]
                # find original object
                found = next((f for f in all_findings if f.file_path == origin.get("file_path") and f.title == origin.get("title")), None)
                if not found:
                    continue
                cards.append(
                    FindingCard(
                        finding=found,
                        fix_snippet=row.get("fix_snippet", ""),
                        explanation_technical=row.get("explanation_technical", ""),
                        explanation_manager=row.get("explanation_manager", ""),
                        explanation_executive=row.get("explanation_executive", ""),
                        critique_verdict=found.critique_verdict or "PLAUSIBLE",
                        critique_note=found.critique_note or "",
                    )
                )

        elapsed = int((time.time() - started) * 1000)
        health = compute_health_score(cards)
        return CouncilReport(
            repo_id=repo_id,
            job_id=job_id,
            finding_cards=cards,
            architecture_report=architecture_report,
            critique_log=critique_log,
            total_duration_ms=elapsed,
            agent_errors=agent_errors,
            health_score=health,
        )
