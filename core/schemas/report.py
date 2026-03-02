# core/schemas/report.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RunMeta(BaseModel):
    mode: str
    model: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    iter_count: int = 0


class ValidationResult(BaseModel):
    passed: bool
    failure_reasons: List[str] = []


class ReactTraceEntry(BaseModel):
    iteration: int
    thought: str = ""
    actions: List[Dict[str, Any]] = []
    observation: str = ""


class DiagnosticsReport(BaseModel):
    paragraphs_before: int = 0
    paragraphs_after: int = 0
    warnings: List[str] = []
    errors: List[str] = []
    extra: Dict[str, Any] = {}


class AgentReport(BaseModel):
    run_meta: RunMeta
    diagnostics: DiagnosticsReport
    react_trace: List[ReactTraceEntry] = []
    validation: ValidationResult
    # backward-compatible raw data
    raw: Dict[str, Any] = {}

    @classmethod
    def from_raw_report(
        cls,
        raw: dict,
        *,
        mode: str = "rule",
        iter_count: int = 0,
        passed: bool = True,
        failure_reasons: List[str] | None = None,
        react_trace: list | None = None,
    ) -> "AgentReport":
        meta_section = raw.get("meta", {})
        return cls(
            run_meta=RunMeta(
                mode=mode,
                iter_count=iter_count,
            ),
            diagnostics=DiagnosticsReport(
                paragraphs_before=meta_section.get("paragraphs_before", 0),
                paragraphs_after=meta_section.get("paragraphs_after", 0),
                warnings=raw.get("warnings", []),
                errors=raw.get("errors", []),
                extra={
                    k: v
                    for k, v in raw.items()
                    if k not in ("meta", "warnings", "errors")
                },
            ),
            react_trace=[ReactTraceEntry(**e) for e in (react_trace or [])],
            validation=ValidationResult(
                passed=passed,
                failure_reasons=failure_reasons or [],
            ),
            raw=raw,
        )
