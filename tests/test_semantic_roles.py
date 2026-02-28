# tests/test_semantic_roles.py
"""
Tests for semantic role preservation (abstract/keyword/reference/footer/list_item)
in formatter, spec loader, and all specialized template specs.
"""
from pathlib import Path
import sys

from docx import Document
from docx.shared import Pt

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.spec import load_spec
from core.formatter import apply_formatting


SPECS_DIR = Path(__file__).resolve().parents[1] / "specs"


def _make_doc_with_roles(role_texts: list) -> tuple:
    """Create a Document with one paragraph per (role, text) pair, return (doc, blocks, labels)."""
    from core.docx_utils import iter_all_paragraphs
    from core.parser import Block

    doc = Document()
    for _, text in role_texts:
        doc.add_paragraph(text)

    blocks = [
        Block(block_id=i + 1, kind="paragraph", text=p.text, paragraph_index=i)
        for i, p in enumerate(iter_all_paragraphs(doc))
    ]
    labels = {b.block_id: role for b, (role, _) in zip(blocks, role_texts)}
    labels["_source"] = "test"
    return doc, blocks, labels


def test_semantic_roles_formatted_not_as_unknown():
    """abstract/keyword/reference/footer/list_item must appear in formatted counts, not unknown_as_body."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))

    semantic_roles = ["abstract", "keyword", "reference", "footer", "list_item"]
    role_texts = [(role, f"这是{role}段落内容示例。") for role in semantic_roles]

    doc, blocks, labels = _make_doc_with_roles(role_texts)
    report = apply_formatting(doc, blocks, labels, spec)

    counts = report["formatted"]["counts"]
    for role in semantic_roles:
        assert counts.get(role, 0) >= 1, (
            f"Role '{role}' should appear in formatted counts but got: {counts}"
        )
    assert counts.get("unknown_as_body", 0) == 0, (
        f"No paragraph should fall through to unknown_as_body: {counts}"
    )


def test_all_spec_files_load_successfully():
    """All YAML spec files in specs/ should load without error."""
    for yaml_path in SPECS_DIR.glob("*.yaml"):
        spec = load_spec(str(yaml_path))
        assert spec is not None, f"Failed to load {yaml_path.name}"
        # Must have required top-level keys
        assert "body" in spec.raw
        assert "heading" in spec.raw
        # Must have semantic role defaults filled in
        for role in ("abstract", "keyword", "reference", "footer"):
            assert role in spec.raw, f"'{role}' key missing in {yaml_path.name}"
            assert "font_size_pt" in spec.raw[role], (
                f"font_size_pt missing in {role} section of {yaml_path.name}"
            )


def test_reference_has_hanging_indent_in_academic_spec():
    """Academic spec should configure reference with non-zero hanging indent."""
    spec = load_spec(str(SPECS_DIR / "academic.yaml"))
    ref = spec.raw["reference"]
    assert float(ref.get("hanging_indent_pt", 0)) > 0, (
        "Academic reference should have hanging_indent_pt > 0 (GB/T 7714 style)"
    )


def test_abstract_italic_in_default_spec():
    """Default spec abstract should be italic to visually distinguish it from body."""
    spec = load_spec(str(SPECS_DIR / "default.yaml"))
    assert spec.raw["abstract"]["italic"] is True
