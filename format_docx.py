# format_docx.py
import sys
from core.spec import load_spec
from core.parser import parse_docx_to_blocks
from core.judge import rule_based_labels
from core.formatter import apply_formatting
from core.writer import save_docx

def main():
    if len(sys.argv) < 3:
        print("Usage: python format_docx.py input.docx output.docx [spec_path]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    spec_path = sys.argv[3] if len(sys.argv) >= 4 else "specs/default.yaml"

    spec = load_spec(spec_path)

    doc, blocks = parse_docx_to_blocks(input_path)

    # 先用规则判断段落类型（后续你接 LLM，就替换这一步）
    labels = rule_based_labels(blocks)

    # 真正执行排版（修改 doc 对象）
    apply_formatting(doc, blocks, labels, spec)

    save_docx(doc, output_path)
    print(f"✅ Done: {output_path}")

if __name__ == "__main__":
    main()