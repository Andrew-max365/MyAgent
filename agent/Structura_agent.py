# agent/doc_agent.py
"""
DocAgent: 文档质量检查 + 自动修复（排版）智能体

定位（比赛讲法）：
- 感知：读取 docx、抽取段落与结构（通过 service -> core）
- 推理：识别标题/正文/异常（labels & detect_role 收敛）
- 执行：拆段、清理、套格式、导出 docx
- 解释：输出 report（可解释、可视化友好）

用法：
  python -m agent.doc_agent tests/samples/sample.docx tests/samples/output.docx
  python agent/doc_agent.py tests/samples/sample.docx tests/samples/output.docx
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from service.format_service import format_docx_file, format_docx_bytes


# ----------------------------
# Agent 结果协议（对 UI/API 友好）
# ----------------------------

@dataclass
class AgentArtifacts:
    output_docx_path: Optional[str] = None
    report_json_path: Optional[str] = None


@dataclass
class AgentResult:
    status: str
    task: str
    goal: str
    steps: list[str]
    summary: str
    report: Dict[str, Any]
    artifacts: AgentArtifacts


# ----------------------------
# Agent 核心逻辑
# ----------------------------

def _safe_get(d: Dict[str, Any], *keys: str, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def build_summary(report: Dict[str, Any]) -> str:
    """
    从 report 提炼一条“评委/用户一眼看懂”的总结。
    """
    before = _safe_get(report, "meta", "paragraphs_before", default="?")
    after = _safe_get(report, "meta", "paragraphs_after", default="?")

    created = _safe_get(report, "actions", "split_body_new_paragraphs_created", default=0)
    affected = _safe_get(report, "actions", "split_body_original_paragraphs_affected", default=0)
    max_lines = _safe_get(report, "actions", "split_body_max_lines_in_one_paragraph", default=0)

    cov = _safe_get(report, "labels", "coverage", "coverage_rate", default=None)
    mismatch = _safe_get(report, "labels", "consistency", "mismatched", default=None)

    warnings = report.get("warnings") or []
    warn_n = len(warnings)

    parts = []
    parts.append(f"段落：{before} → {after}")
    if created:
        parts.append(f"软回车拆分：新增 {created} 段（影响 {affected} 段，单段最多 {max_lines} 行）")
    if cov is not None:
        parts.append(f"标签覆盖率：{cov:.0%}")
    if mismatch is not None:
        parts.append(f"标签一致性冲突：{mismatch} 条")
    if warn_n:
        parts.append(f"告警：{warn_n} 条")

    return "；".join(parts) + "。"


def run_doc_agent_file(
    input_path: str,
    output_path: str,
    *,
    spec_path: str = "specs/default.yaml",
    report_path: Optional[str] = None,
    write_report: bool = True,
) -> AgentResult:
    """
    路径模式：适合 CLI/本地批处理/服务器落盘。
    """
    steps = [
        "感知：加载 DOCX 并解析段落结构",
        "推理：识别标题/正文/列表与异常（统一口径 detect_role）",
        "执行：清理空行、拆分软回车段落、应用排版规范",
        "解释：生成可解释 report 并导出排版后的 DOCX",
    ]

    res = format_docx_file(
        input_path=input_path,
        output_path=output_path,
        spec_path=spec_path,
        report_path=report_path,
        write_report=write_report,
    )

    summary = build_summary(res.report)

    return AgentResult(
        status="ok",
        task="docx_format_and_audit",
        goal="对输入 Word 文档进行结构诊断与自动排版修复，并输出可解释报告与排版后文档。",
        steps=steps,
        summary=summary,
        report=res.report,
        artifacts=AgentArtifacts(
            output_docx_path=res.output_path,
            report_json_path=res.report_path,
        ),
    )


def run_doc_agent_bytes(
    input_bytes: bytes,
    *,
    spec_path: str = "specs/default.yaml",
    filename_hint: str = "input.docx",
) -> Tuple[bytes, AgentResult]:
    """
    bytes 模式：适合 UI/API（上传文件）场景。
    返回：(output_bytes, agent_result)
    """
    steps = [
        "感知：读取上传的 DOCX（二进制）",
        "推理：识别标题/正文/列表与异常（统一口径 detect_role）",
        "执行：清理空行、拆分软回车段落、应用排版规范",
        "解释：生成可解释 report 并返回排版后 DOCX（二进制）",
    ]

    out_bytes, report = format_docx_bytes(
        input_bytes=input_bytes,
        spec_path=spec_path,
        filename_hint=filename_hint,
        keep_temp_files=False,
    )
    summary = build_summary(report)

    agent_res = AgentResult(
        status="ok",
        task="docx_format_and_audit",
        goal="对输入 Word 文档进行结构诊断与自动排版修复，并输出可解释报告与排版后文档。",
        steps=steps,
        summary=summary,
        report=report,
        artifacts=AgentArtifacts(output_docx_path=None, report_json_path=None),
    )

    return out_bytes, agent_res


# ----------------------------
# CLI 入口（比赛演示友好）
# ----------------------------

def _default_output_path(input_path: str) -> str:
    """
    若用户只给 input，不给 output：
    - 默认输出到同目录：<name>.formatted.docx
    """
    base = os.path.basename(input_path)
    root, ext = os.path.splitext(base)
    if ext.lower() != ".docx":
        ext = ".docx"
    out_name = f"{root}.formatted{ext}"
    return os.path.join(os.path.dirname(input_path) or ".", out_name)


def main():
    parser = argparse.ArgumentParser(description="DocAgent: DOCX 质量检查 + 自动排版修复")
    parser.add_argument("input", help="输入 .docx 路径")
    parser.add_argument("output", nargs="?", default=None, help="输出 .docx 路径（可选）")
    parser.add_argument("--spec", default="specs/default.yaml", help="排版规范 YAML 路径")
    parser.add_argument("--report", default=None, help="report.json 输出路径（可选）")
    parser.add_argument("--no-report", action="store_true", help="不写 report.json 文件")
    parser.add_argument("--agent-json", default=None, help="额外输出 agent_result 的 json（便于调试/展示）")

    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or _default_output_path(input_path)

    agent_res = run_doc_agent_file(
        input_path=input_path,
        output_path=output_path,
        spec_path=args.spec,
        report_path=args.report,
        write_report=not args.no_report,
    )

    # 保留你喜欢的输出风格 + 增加 Agent 摘要
    print(f"✅ Done: {agent_res.artifacts.output_docx_path}")
    if agent_res.artifacts.report_json_path:
        print(f"🧾 Report: {agent_res.artifacts.report_json_path}")
    print(f"🧠 Agent Summary: {agent_res.summary}")

    if args.agent_json:
        os.makedirs(os.path.dirname(args.agent_json) or ".", exist_ok=True)
        payload = {
            "status": agent_res.status,
            "task": agent_res.task,
            "goal": agent_res.goal,
            "steps": agent_res.steps,
            "summary": agent_res.summary,
            "artifacts": {
                "output_docx_path": agent_res.artifacts.output_docx_path,
                "report_json_path": agent_res.artifacts.report_json_path,
            },
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        with open(args.agent_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"📦 Agent JSON: {args.agent_json}")


if __name__ == "__main__":
    main()