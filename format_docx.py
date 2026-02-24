# format_docx.py
import sys
import json
import os

from core.spec import load_spec
from core.parser import parse_docx_to_blocks
from core.judge import rule_based_labels
from core.formatter import apply_formatting
from core.writer import save_docx

def _default_report_path(output_path: str) -> str:
    root, ext = os.path.splitext(output_path)
    return root + ".report.json"

def main():
    if len(sys.argv) < 3:
        print("Usage: python format_docx.py input.docx output.docx [spec_path] [report_path]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    spec_path = sys.argv[3] if len(sys.argv) >= 4 else "specs/default.yaml"
    report_path = sys.argv[4] if len(sys.argv) >= 5 else _default_report_path(output_path)

    spec = load_spec(spec_path)

    doc, blocks = parse_docx_to_blocks(input_path)

    # 先用规则判断段落类型（后续你接 LLM，就替换这一步）
    labels = rule_based_labels(blocks)
    labels["_source"] = "rule_based"

    # 真正执行排版（修改 doc 对象），并返回可解释的 report(dict)
    report = apply_formatting(doc, blocks, labels, spec)

    save_docx(doc, output_path)

    # 写诊断/修复报告
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ Done: {output_path}")
    print(f"🧾 Report: {report_path}")

if __name__ == "__main__":
    main()