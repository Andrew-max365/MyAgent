# tests/test_audit_fixes.py
"""
Tests for four bugs found in the code audit:
  1. core/judge.py fallback RE_CN_ENUM now includes 百千万 (consistent with formatter.py)
  2. core/docx_utils.py unused imports removed (deepcopy, Optional)
  3. core/formatter.py unknown branch resets hanging_indent to Pt(0)
  4. core/formatter.py detect_role docstring updated to list all return values
"""
from pathlib import Path
import sys

from docx import Document
from docx.shared import Pt

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.judge import rule_based_labels
from core.formatter import apply_formatting, detect_role
from core.spec import load_spec
from core.parser import Block
from core.docx_utils import iter_all_paragraphs

SPECS_DIR = Path(__file__).resolve().parents[1] / "specs"


# ---------------------------------------------------------------------------
# Fix 1: judge.py fallback RE_CN_ENUM includes 百千万
# ---------------------------------------------------------------------------

def test_judge_fallback_re_cn_enum_includes_bai_qian_wan():
    """Fallback rule_based_labels (no doc) must classify 百X/千X/万X enumerated
    headings as h2, consistent with formatter.py's detect_role."""
    from core.parser import Block

    blocks = [
        Block(block_id=1, kind="paragraph", text="百一、概论", paragraph_index=0),
        Block(block_id=2, kind="paragraph", text="千二、附则", paragraph_index=1),
        Block(block_id=3, kind="paragraph", text="万三、特别条款", paragraph_index=2),
    ]
    labels = rule_based_labels(blocks, doc=None)

    for b in blocks:
        assert labels[b.block_id] == "h2", (
            f"{b.text!r} should be 'h2' in fallback path, got {labels[b.block_id]!r}"
        )


def test_judge_fallback_re_cn_enum_still_covers_ten_and_below():
    """Ensure the original 一…十 range still works in the updated regex."""
    from core.parser import Block

    blocks = [
        Block(block_id=1, kind="paragraph", text="一、引言", paragraph_index=0),
        Block(block_id=2, kind="paragraph", text="十、总结", paragraph_index=1),
    ]
    labels = rule_based_labels(blocks, doc=None)

    assert labels[1] == "h2"
    assert labels[2] == "h2"


# ---------------------------------------------------------------------------
# Fix 2: docx_utils.py unused imports removed
# ---------------------------------------------------------------------------

def test_docx_utils_no_unused_deepcopy_import():
    """deepcopy should no longer be imported in core/docx_utils.py."""
    docx_utils_path = Path(__file__).resolve().parents[1] / "core" / "docx_utils.py"
    source = docx_utils_path.read_text(encoding="utf-8")
    assert "from copy import deepcopy" not in source
    assert "import deepcopy" not in source


def test_docx_utils_no_unused_optional_import():
    """Optional should no longer be imported in core/docx_utils.py."""
    docx_utils_path = Path(__file__).resolve().parents[1] / "core" / "docx_utils.py"
    source = docx_utils_path.read_text(encoding="utf-8")
    # Verify Optional is not in the typing import line
    for line in source.splitlines():
        if "from typing import" in line:
            assert "Optional" not in line, (
                f"'Optional' should have been removed from typing import: {line!r}"
            )


# ---------------------------------------------------------------------------
# Fix 3: apply_formatting unknown branch resets hanging_indent to Pt(0)
# ---------------------------------------------------------------------------

def _make_doc_blocks_labels(role_texts):
    """Helper: build (doc, blocks, labels) with one paragraph per (role, text)."""
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


def test_unknown_role_resets_hanging_indent():
    """A paragraph labelled 'unknown' must have left_indent reset to 0
    and first_line_indent set to a non-negative value (body-style indent)."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    doc, blocks, labels = _make_doc_blocks_labels([("unknown", "这是未知角色的段落。")])

    # Pre-set a real hanging indent (left_indent > 0, first_line_indent < 0)
    para = iter_all_paragraphs(doc)[0]
    para.paragraph_format.left_indent = Pt(36)
    para.paragraph_format.first_line_indent = Pt(-36)

    apply_formatting(doc, blocks, labels, spec)

    after_para = iter_all_paragraphs(doc)[0]
    pf = after_para.paragraph_format

    assert pf.left_indent == Pt(0), (
        f"unknown branch should reset left_indent to 0, got {pf.left_indent}"
    )
    # first_line_indent should be positive (body first-line indent), not negative
    if pf.first_line_indent is not None:
        assert pf.first_line_indent >= 0, (
            f"unknown branch should not leave negative first_line_indent, got {pf.first_line_indent}"
        )


def test_unknown_role_hanging_indent_consistent_with_body():
    """Formatting a paragraph as 'unknown' should yield same left_indent and
    first_line_indent as 'body'."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    # unknown paragraph
    doc_u, blocks_u, labels_u = _make_doc_blocks_labels([("unknown", "未知段落内容。")])
    apply_formatting(doc_u, blocks_u, labels_u, spec)
    u_pf = iter_all_paragraphs(doc_u)[0].paragraph_format

    # body paragraph
    doc_b, blocks_b, labels_b = _make_doc_blocks_labels([("body", "正文段落内容。")])
    apply_formatting(doc_b, blocks_b, labels_b, spec)
    b_pf = iter_all_paragraphs(doc_b)[0].paragraph_format

    assert u_pf.left_indent == b_pf.left_indent, (
        f"unknown left_indent {u_pf.left_indent} != body {b_pf.left_indent}"
    )
    assert u_pf.first_line_indent == b_pf.first_line_indent, (
        f"unknown first_line_indent {u_pf.first_line_indent} != body {b_pf.first_line_indent}"
    )


# ---------------------------------------------------------------------------
# Fix 4: detect_role docstring lists all actual return values
# ---------------------------------------------------------------------------

def test_detect_role_docstring_covers_all_return_values():
    """detect_role docstring should mention all actual return values."""
    import inspect
    doc_str = inspect.getdoc(detect_role) or ""
    expected_returns = {"blank", "h1", "h2", "h3", "caption", "abstract",
                        "keyword", "reference", "list_item", "footer", "body"}
    for role in expected_returns:
        assert role in doc_str, (
            f"detect_role docstring missing return value {role!r}"
        )
