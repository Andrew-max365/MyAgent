# format_docx.py

import argparse
from service.format_service import format_docx_file


def main():
    parser = argparse.ArgumentParser(description="Format DOCX with report output")
    parser.add_argument("input", help="input docx")
    parser.add_argument("output", help="output docx")
    parser.add_argument("--spec", default="specs/default.yaml", help="spec yaml path")
    parser.add_argument("--report", default=None, help="report json output path")
    parser.add_argument("--no-report", action="store_true", help="disable report file writing")
    parser.add_argument(
        "--label-mode",
        default="rule",
        choices=["rule", "llm", "hybrid"],
        help="label mode: rule / llm / hybrid",
    )
    args = parser.parse_args()

    result = format_docx_file(
        args.input,
        args.output,
        spec_path=args.spec,
        report_path=args.report,
        write_report=not args.no_report,
        label_mode=args.label_mode,
    )

    print(f"✅ Done: {result.output_path}")
    if result.report_path:
        print(f"🧾 Report: {result.report_path}")


if __name__ == "__main__":
    main()
