# service/format_service.py
from __future__ import annotations

import io
import os
import json
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

from core.spec import load_spec
from core.parser import parse_docx_to_blocks
from core.judge import rule_based_labels
from core.formatter import apply_formatting
from core.writer import save_docx


def ensure_docx_path(path: str) -> str:
    """若用户传入不带扩展名，则默认补 .docx（兼容你目前 CLI 行为）"""
    root, ext = os.path.splitext(path)
    if ext == "":
        return path + ".docx"
    return path


def default_report_path(output_path: str) -> str:
    root, _ = os.path.splitext(output_path)
    return root + ".report.json"


@dataclass
class FormatResult:
    output_path: str
    report_path: Optional[str]
    report: Dict[str, Any]


def format_docx_file(
    input_path: str,
    output_path: str,
    spec_path: str = "specs/default.yaml",
    report_path: Optional[str] = None,
    write_report: bool = True,
) -> FormatResult:
    """
    文件路径版：适合 CLI 或服务端落盘场景。

    - input_path: 输入 docx
    - output_path: 输出 docx（允许不写扩展名，会自动补 .docx）
    - spec_path: YAML 规范文件
    - report_path: 诊断报告路径；None 则默认与 output 同名 .report.json
    - write_report: 是否写 report.json 到磁盘

    返回：FormatResult(output_path, report_path, report_dict)
    """
    input_path = ensure_docx_path(input_path)
    output_path = ensure_docx_path(output_path)
    if report_path is None and write_report:
        report_path = default_report_path(output_path)

    spec = load_spec(spec_path)

    doc, blocks = parse_docx_to_blocks(input_path)

    # 规则标注（你现在已支持 doc=doc 以复用 detect_role 口径）
    labels = rule_based_labels(blocks, doc=doc)
    labels["_source"] = "rule_based"

    report = apply_formatting(doc, blocks, labels, spec)

    save_docx(doc, output_path)

    if write_report and report_path:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    return FormatResult(output_path=output_path, report_path=report_path, report=report)


def format_docx_bytes(
    input_bytes: bytes,
    spec_path: str = "specs/default.yaml",
    *,
    filename_hint: str = "input.docx",
    keep_temp_files: bool = False,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    bytes 版：适合 UI/API（上传文件）场景。
    返回：(output_docx_bytes, report_dict)

    - filename_hint: 仅用于生成更可读的临时文件名
    - keep_temp_files: 调试用；True 则不删除临时目录
    """
    # 用 TemporaryDirectory 方便自动清理
    tmpdir_obj = tempfile.TemporaryDirectory(prefix="docx_agent_")
    tmpdir = tmpdir_obj.name

    try:
        safe_name = os.path.basename(filename_hint) or "input.docx"
        if not safe_name.lower().endswith(".docx"):
            safe_name += ".docx"

        in_path = os.path.join(tmpdir, safe_name)
        out_path = os.path.join(tmpdir, "output.docx")
        report_path = os.path.join(tmpdir, "output.report.json")

        with open(in_path, "wb") as f:
            f.write(input_bytes)

        res = format_docx_file(
            input_path=in_path,
            output_path=out_path,
            spec_path=spec_path,
            report_path=report_path,
            write_report=True,
        )

        with open(res.output_path, "rb") as f:
            output_bytes = f.read()

        return output_bytes, res.report

    finally:
        if keep_temp_files:
            # 调试时你可以把 tmpdir 打印出来自己去看
            print(f"[debug] temp files kept at: {tmpdir}")
        else:
            tmpdir_obj.cleanup()