# format_docx.py

import sys
from service.format_service import format_docx_file


def main():
    if len(sys.argv) < 3:
        print("Usage: python format_docx.py input.docx output.docx")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    result = format_docx_file(input_path, output_path)

    print(f"✅ Done: {result.output_path}")
    if result.report_path:
        print(f"🧾 Report: {result.report_path}")


if __name__ == "__main__":
    main()