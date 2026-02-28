from docx import Document

from agent.doc_analyzer import DocAnalyzer
from agent.mode_router import _structure_to_labels
from agent.schema import DocumentStructure


def test_llm_schema_roles_are_mapped_to_formatter_roles():
    structure = DocumentStructure(
        total_paragraphs=4,
        paragraphs=[
            {
                "index": 0,
                "text_preview": "标题",
                "paragraph_type": "title_1",
                "confidence": 0.95,
            },
            {
                "index": 1,
                "text_preview": "图1",
                "paragraph_type": "figure_caption",
                "confidence": 0.95,
            },
            {
                "index": 2,
                "text_preview": "未知",
                "paragraph_type": "unknown",
                "confidence": 0.50,
            },
            {
                "index": 3,
                "text_preview": "关键词",
                "paragraph_type": "keyword",
                "confidence": 0.90,
            },
        ],
    )

    labels = _structure_to_labels(structure)

    assert labels == {0: "h1", 1: "caption", 2: "unknown", 3: "body"}


def test_doc_analyzer_extract_paragraphs_includes_table_paragraphs_in_flow_order():
    doc = Document()
    doc.add_paragraph("文档首段")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].text = "表格段落"
    doc.add_paragraph("文档尾段")

    paragraphs = DocAnalyzer.extract_paragraphs(doc)

    assert paragraphs == ["文档首段", "表格段落", "文档尾段"]
