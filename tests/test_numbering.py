# tests/test_numbering.py
"""
Tests for core/numbering.py and the text-list-to-numPr conversion pipeline.

Coverage:
  1. detect_text_list_prefix correctly identifies all five formats
  2. create_list_num_id adds a fresh abstractNum + num to the document
  3. apply_numpr writes w:numPr onto the paragraph
  4. strip_list_text_prefix removes the text marker from runs
  5. convert_text_lists end-to-end: groups, min_run_len guard, numPr applied
  6. apply_formatting integrates numbering conversion (step 5)
  7. detect_role now classifies body list patterns as list_item
"""

from pathlib import Path
import sys

from docx import Document
from docx.oxml.ns import qn

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.numbering import (
    detect_text_list_prefix,
    create_list_num_id,
    apply_numpr,
    strip_list_text_prefix,
    convert_text_lists,
)
from core.formatter import apply_formatting, detect_role
from core.docx_utils import iter_all_paragraphs, is_effectively_blank_paragraph
from core.spec import load_spec
from core.parser import Block

SPECS_DIR = Path(__file__).resolve().parents[1] / "specs"


# ─── 1. detect_text_list_prefix ──────────────────────────────────────────────

def test_detect_paren_arabic():
    result = detect_text_list_prefix("（1）第一点")
    assert result is not None
    fmt, ordinal, prefix_len = result
    assert fmt == "paren_arabic"
    assert ordinal == 1
    assert prefix_len == 3  # "（" + "1" + "）" = 3 Unicode code points

def test_detect_paren_arabic_multi_digit():
    result = detect_text_list_prefix("（12）第十二点")
    assert result is not None
    fmt, ordinal, prefix_len = result
    assert fmt == "paren_arabic"
    assert ordinal == 12

def test_detect_rparen():
    result = detect_text_list_prefix("3) 第三点")
    assert result is not None
    fmt, ordinal, prefix_len = result
    assert fmt == "rparen"
    assert ordinal == 3

def test_detect_rparen_fullwidth():
    result = detect_text_list_prefix("2） 第二点")
    assert result is not None
    fmt, ordinal, _ = result
    assert fmt == "rparen"
    assert ordinal == 2

def test_detect_enclosed():
    for i, ch in enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1):
        result = detect_text_list_prefix(f"{ch}内容{i}")
        assert result is not None, f"Failed on {ch!r}"
        fmt, ordinal, _ = result
        assert fmt == "enclosed"
        assert ordinal == i

def test_detect_alpha_lower():
    result = detect_text_list_prefix("a. 选项A")
    assert result is not None
    fmt, ordinal, _ = result
    assert fmt == "alpha_lower"
    assert ordinal == 1

def test_detect_alpha_upper():
    result = detect_text_list_prefix("B. 选项B")
    assert result is not None
    fmt, ordinal, _ = result
    assert fmt == "alpha_upper"
    assert ordinal == 2

def test_detect_returns_none_for_body_text():
    for text in ["这是正文。", "第一条 总则", "一、概述", "1.1 引言", "摘要：xxx"]:
        assert detect_text_list_prefix(text) is None, f"Should be None for {text!r}"

def test_detect_returns_none_for_cn_paren_subtitle():
    # （一） is h3, not a body list item — confirm detect_text_list_prefix returns None
    assert detect_text_list_prefix("（一）子标题") is None


# ─── 2. create_list_num_id ────────────────────────────────────────────────────

def test_create_list_num_id_adds_to_numbering_part():
    doc = Document()
    nelem = doc.part.numbering_part._element
    ids_before = {c.get(qn("w:numId")) for c in nelem if c.tag == qn("w:num")}

    num_id = create_list_num_id(doc, "paren_arabic")
    assert isinstance(num_id, int)
    assert num_id > 0

    ids_after = {c.get(qn("w:numId")) for c in nelem if c.tag == qn("w:num")}
    assert str(num_id) in ids_after - ids_before


def test_create_list_num_id_adds_abstractNum():
    doc = Document()
    nelem = doc.part.numbering_part._element
    abs_ids_before = {c.get(qn("w:abstractNumId")) for c in nelem if c.tag == qn("w:abstractNum")}

    num_id = create_list_num_id(doc, "enclosed")

    abs_ids_after = {c.get(qn("w:abstractNumId")) for c in nelem if c.tag == qn("w:abstractNum")}
    assert len(abs_ids_after) == len(abs_ids_before) + 1


def test_create_two_lists_get_different_ids():
    doc = Document()
    id1 = create_list_num_id(doc, "paren_arabic")
    id2 = create_list_num_id(doc, "rparen")
    assert id1 != id2


# ─── 3. apply_numpr ──────────────────────────────────────────────────────────

def test_apply_numpr_writes_numpr():
    doc = Document()
    p = doc.add_paragraph("测试")
    num_id = create_list_num_id(doc, "paren_arabic")
    apply_numpr(p, num_id)

    pPr = p._p.pPr
    assert pPr is not None
    numPr = pPr.find(qn("w:numPr"))
    assert numPr is not None
    assert numPr.find(qn("w:numId")).get(qn("w:val")) == str(num_id)
    assert numPr.find(qn("w:ilvl")).get(qn("w:val")) == "0"


def test_apply_numpr_idempotent():
    """Calling apply_numpr twice should not create duplicate numPr elements."""
    doc = Document()
    p = doc.add_paragraph("测试")
    num_id = create_list_num_id(doc, "paren_arabic")
    apply_numpr(p, num_id)
    apply_numpr(p, num_id)

    pPr = p._p.pPr
    all_numpr = pPr.findall(qn("w:numPr"))
    assert len(all_numpr) == 1


# ─── 4. strip_list_text_prefix ───────────────────────────────────────────────

def test_strip_paren_arabic_prefix():
    doc = Document()
    p = doc.add_paragraph("（1）这是第一点内容")
    result = detect_text_list_prefix(p.text)
    assert result is not None
    _, _, prefix_len = result
    strip_list_text_prefix(p, prefix_len)
    assert p.text == "这是第一点内容"


def test_strip_enclosed_prefix():
    doc = Document()
    p = doc.add_paragraph("①这是第一点")
    result = detect_text_list_prefix(p.text)
    assert result is not None
    _, _, prefix_len = result
    strip_list_text_prefix(p, prefix_len)
    assert p.text == "这是第一点"


def test_strip_rparen_prefix():
    doc = Document()
    p = doc.add_paragraph("2) 第二点内容")
    result = detect_text_list_prefix(p.text)
    assert result is not None
    _, _, prefix_len = result
    strip_list_text_prefix(p, prefix_len)
    assert "2)" not in p.text
    assert "第二点内容" in p.text


# ─── 5. convert_text_lists ───────────────────────────────────────────────────

def _is_list_p(p):
    try:
        ppr = p._p.pPr
        return bool(ppr is not None and getattr(ppr, "numPr", None) is not None)
    except Exception:
        return False


def test_convert_text_lists_converts_group():
    doc = Document()
    texts = ["（1）第一项", "（2）第二项", "（3）第三项"]
    for t in texts:
        doc.add_paragraph(t)

    paras = iter_all_paragraphs(doc)
    converted = convert_text_lists(
        doc, paras,
        get_role=lambda _: "list_item",
        is_list_paragraph_fn=_is_list_p,
        is_blank_fn=is_effectively_blank_paragraph,
        min_run_len=2,
    )
    assert converted == 3

    for p in iter_all_paragraphs(doc):
        assert _is_list_p(p), f"Paragraph {p.text!r} should have numPr"
        # Text prefix should be stripped
        assert not p.text.startswith("（"), f"Prefix not stripped from {p.text!r}"


def test_convert_text_lists_respects_min_run_len():
    """A single-item group should NOT be converted when min_run_len=2."""
    doc = Document()
    doc.add_paragraph("（1）只有一项")
    doc.add_paragraph("这是正文段落。")

    paras = iter_all_paragraphs(doc)
    converted = convert_text_lists(
        doc, paras,
        get_role=lambda p: "list_item" if p.text.startswith("（") else "body",
        is_list_paragraph_fn=_is_list_p,
        is_blank_fn=is_effectively_blank_paragraph,
        min_run_len=2,
    )
    assert converted == 0

    # The paragraph should still have its text prefix intact
    p = iter_all_paragraphs(doc)[0]
    assert "（1）" in p.text


def test_convert_text_lists_skips_existing_numpr():
    """Paragraphs that already have numPr should be skipped."""
    doc = Document()
    p = doc.add_paragraph("（1）已有列表")
    # Manually apply numPr
    num_id = create_list_num_id(doc, "paren_arabic")
    apply_numpr(p, num_id)

    doc.add_paragraph("（2）第二项")

    paras = iter_all_paragraphs(doc)
    converted = convert_text_lists(
        doc, paras,
        get_role=lambda _: "list_item",
        is_list_paragraph_fn=_is_list_p,
        is_blank_fn=is_effectively_blank_paragraph,
        min_run_len=2,
    )
    # The first paragraph already had numPr, so the pair is broken — no group of 2 without numPr
    assert converted == 0


def test_convert_different_formats_form_separate_groups():
    doc = Document()
    doc.add_paragraph("（1）阿拉伯括号一")
    doc.add_paragraph("（2）阿拉伯括号二")
    doc.add_paragraph("①圈一")
    doc.add_paragraph("②圈二")

    paras = iter_all_paragraphs(doc)
    converted = convert_text_lists(
        doc, paras,
        get_role=lambda _: "list_item",
        is_list_paragraph_fn=_is_list_p,
        is_blank_fn=is_effectively_blank_paragraph,
        min_run_len=2,
    )
    assert converted == 4

    # Both groups should have numPr but with different numIds
    all_paras = iter_all_paragraphs(doc)
    num_ids = set()
    for p in all_paras:
        ppr = p._p.pPr
        if ppr is not None:
            numPr = ppr.find(qn("w:numPr"))
            if numPr is not None:
                num_ids.add(numPr.find(qn("w:numId")).get(qn("w:val")))
    assert len(num_ids) == 2, f"Expected 2 different numIds, got {num_ids}"


# ─── 6. apply_formatting integration ─────────────────────────────────────────

def _make_doc_blocks_labels(role_texts):
    doc = Document()
    for _, text in role_texts:
        doc.add_paragraph(text)
    paras = iter_all_paragraphs(doc)
    blocks = [
        Block(block_id=i + 1, kind="paragraph", text=p.text, paragraph_index=i)
        for i, p in enumerate(paras)
    ]
    labels = {b.block_id: role for b, (role, _) in zip(blocks, role_texts)}
    labels["_source"] = "test"
    return doc, blocks, labels


def test_apply_formatting_converts_text_lists():
    """apply_formatting step 4.5 must convert LLM-labeled list items to real numPr."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    doc, blocks, labels = _make_doc_blocks_labels([
        ("list_item", "（1）第一项内容"),
        ("list_item", "（2）第二项内容"),
        ("list_item", "（3）第三项内容"),
    ])

    report = apply_formatting(doc, blocks, labels, spec)

    # Report should record the conversion count (LLM-direct path)
    total_converted = (
        report["actions"]["llm_direct_list_converted"]
        + report["actions"]["text_list_converted_to_numpr"]
    )
    assert total_converted == 3

    # All three paragraphs should have real numPr
    for p in iter_all_paragraphs(doc):
        if not is_effectively_blank_paragraph(p):
            assert _is_list_p(p), f"Expected numPr on {p.text!r}"


def test_apply_formatting_text_list_prefix_stripped():
    """After conversion, the text-based prefix (（1）) must be removed from runs."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    doc, blocks, labels = _make_doc_blocks_labels([
        ("list_item", "（1）内容一"),
        ("list_item", "（2）内容二"),
    ])

    apply_formatting(doc, blocks, labels, spec)

    for p in iter_all_paragraphs(doc):
        if not is_effectively_blank_paragraph(p):
            assert "（" not in p.text, f"Prefix still present in {p.text!r}"


def test_apply_formatting_convert_text_numbers_disabled():
    """When convert_text_numbers=false, text lists are NOT converted."""
    import copy
    spec = load_spec(str(SPECS_DIR / "default.yaml"))
    # Mutate a copy to disable conversion
    raw = copy.deepcopy(spec.raw)
    raw["list_item"]["convert_text_numbers"] = False
    from core.spec import Spec
    spec_off = Spec(raw=raw)

    doc, blocks, labels = _make_doc_blocks_labels([
        ("list_item", "（1）第一项"),
        ("list_item", "（2）第二项"),
    ])

    report = apply_formatting(doc, blocks, labels, spec_off)

    assert report["actions"]["text_list_converted_to_numpr"] == 0
    # Text prefix should still be present
    paras = [p for p in iter_all_paragraphs(doc) if not is_effectively_blank_paragraph(p)]
    assert any("（1）" in p.text for p in paras)


def test_apply_formatting_report_includes_numpr_count():
    """report['actions']['text_list_converted_to_numpr'] key must always be present."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))
    doc, blocks, labels = _make_doc_blocks_labels([("body", "这是正文。")])
    report = apply_formatting(doc, blocks, labels, spec)
    assert "text_list_converted_to_numpr" in report["actions"]


# ─── 7. detect_role for body list patterns ───────────────────────────────────

def test_detect_role_body_list_paren_arabic():
    doc = Document()
    assert detect_role(doc.add_paragraph("（1）第一点")) == "list_item"
    assert detect_role(doc.add_paragraph("（10）第十点")) == "list_item"


def test_detect_role_body_list_rparen():
    doc = Document()
    assert detect_role(doc.add_paragraph("1) 第一点")) == "list_item"
    assert detect_role(doc.add_paragraph("3） 第三点")) == "list_item"


def test_detect_role_body_list_enclosed():
    doc = Document()
    assert detect_role(doc.add_paragraph("①第一点")) == "list_item"
    assert detect_role(doc.add_paragraph("⑩第十点")) == "list_item"


def test_detect_role_body_list_alpha():
    doc = Document()
    assert detect_role(doc.add_paragraph("a. 选项A")) == "list_item"
    assert detect_role(doc.add_paragraph("B. 选项B")) == "list_item"


def test_detect_role_cn_paren_subtitle_still_h3():
    """（一）style (Chinese numeral in parentheses) must stay h3, not list_item."""
    doc = Document()
    assert detect_role(doc.add_paragraph("（一）子标题内容")) == "h3"
    assert detect_role(doc.add_paragraph("（三）另一子节")) == "h3"


# ─── 8. num_dot format (1. text) ─────────────────────────────────────────────

def test_detect_text_list_prefix_num_dot():
    result = detect_text_list_prefix("1. 第一项内容")
    assert result is not None
    fmt, ordinal, prefix_len = result
    assert fmt == "num_dot"
    assert ordinal == 1
    assert prefix_len == 3  # "1" + "." + " " = 3 chars


def test_detect_text_list_prefix_num_dot_multi_digit():
    result = detect_text_list_prefix("10. 第十项内容")
    assert result is not None
    fmt, ordinal, prefix_len = result
    assert fmt == "num_dot"
    assert ordinal == 10
    assert prefix_len == 4  # "10" + "." + " " = 4 chars


def test_detect_text_list_prefix_num_dot_not_multilevel():
    """1.1 text (multi-level) must NOT match num_dot."""
    assert detect_text_list_prefix("1.1 多级标题") is None
    assert detect_text_list_prefix("2.3 另一节") is None


def test_detect_role_body_list_num_dot():
    """1. text style should be classified as list_item."""
    doc = Document()
    assert detect_role(doc.add_paragraph("1. 第一点内容")) == "list_item"
    assert detect_role(doc.add_paragraph("2. 第二点内容")) == "list_item"
    assert detect_role(doc.add_paragraph("10. 第十点内容")) == "list_item"


def test_detect_role_multilevel_not_list_item():
    """1.1 text (multi-level) must NOT be list_item (stays h3 via RE_NUM_DOT)."""
    doc = Document()
    assert detect_role(doc.add_paragraph("1.1 二级标题")) == "h3"


def test_convert_text_lists_num_dot():
    """num_dot format (1. text) should be converted to real Word list."""
    doc = Document()
    texts = ["1. 第一项", "2. 第二项", "3. 第三项"]
    for t in texts:
        doc.add_paragraph(t)

    def _is_list_p(p):
        try:
            ppr = p._p.pPr
            return bool(ppr is not None and getattr(ppr, "numPr", None) is not None)
        except Exception:
            return False

    paras = iter_all_paragraphs(doc)
    converted = convert_text_lists(
        doc, paras,
        get_role=lambda _: "list_item",
        is_list_paragraph_fn=_is_list_p,
        is_blank_fn=is_effectively_blank_paragraph,
        min_run_len=2,
    )
    assert converted == 3
    for p in iter_all_paragraphs(doc):
        assert _is_list_p(p), f"Paragraph {p.text!r} should have numPr"
        # No numeric prefix should remain (1., 2., 3.)
        import re as _re
        assert not _re.match(r"^\d+\. ", p.text), f"Prefix not stripped: {p.text!r}"


def test_apply_formatting_converts_num_dot_lists():
    """apply_formatting must convert 1. 2. 3. style lists to real numPr."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    doc, blocks, labels = _make_doc_blocks_labels([
        ("list_item", "1. 第一项内容"),
        ("list_item", "2. 第二项内容"),
        ("list_item", "3. 第三项内容"),
    ])

    report = apply_formatting(doc, blocks, labels, spec)
    total_converted = (
        report["actions"]["llm_direct_list_converted"]
        + report["actions"]["text_list_converted_to_numpr"]
    )
    assert total_converted == 3

    for p in iter_all_paragraphs(doc):
        if not is_effectively_blank_paragraph(p):
            ppr = p._p.pPr
            assert ppr is not None and ppr.find(qn("w:numPr")) is not None


# ─── 9. table cell formatting ────────────────────────────────────────────────

def test_table_cell_body_no_first_line_indent():
    """Body paragraphs inside table cells must not receive first-line indent."""
    from core.formatter import apply_formatting
    from core.parser import Block
    from docx.shared import Pt

    spec = load_spec(str(SPECS_DIR / "default.yaml"))
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    # Replace the default empty paragraph with body-like content
    p = cell.paragraphs[0]
    p.text = "这是表格内容"

    paras = iter_all_paragraphs(doc)
    blocks = [
        Block(block_id=i + 1, kind="paragraph", text=para.text, paragraph_index=i)
        for i, para in enumerate(paras)
    ]
    labels = {"_source": "test"}

    apply_formatting(doc, blocks, labels, spec)

    cell_p = table.cell(0, 0).paragraphs[0]
    fli = cell_p.paragraph_format.first_line_indent
    # Should be 0 (no indent) or None (not set), NOT Pt(24) or similar
    assert fli is None or fli == 0, f"Expected no first-line indent in cell, got {fli}"


def test_autofit_tables_action_in_report():
    """apply_formatting report must include tables_autofitted count."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))
    doc = Document()
    doc.add_table(rows=2, cols=2)
    paras = iter_all_paragraphs(doc)
    blocks = [
        Block(block_id=i + 1, kind="paragraph", text=p.text, paragraph_index=i)
        for i, p in enumerate(paras)
    ]
    labels = {"_source": "test"}
    report = apply_formatting(doc, blocks, labels, spec)
    assert "tables_autofitted" in report["actions"]
    assert report["actions"]["tables_autofitted"] == 1
