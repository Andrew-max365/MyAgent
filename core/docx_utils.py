# core/docx_utils.py
from typing import Optional
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ASCII_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

def is_mostly_ascii(s: str) -> bool:
    if not s:
        return False
    hits = sum(1 for ch in s if ch in ASCII_CHARS)
    return hits / max(1, len(s)) >= 0.4

def _ensure_rpr_rfonts(run):
    """确保 run._element 下存在 w:rPr 和 w:rFonts，避免 None 崩溃。"""
    r = run._element
    rPr = r.rPr
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        r.insert(0, rPr)
    rFonts = rPr.rFonts
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    return rFonts

def set_run_fonts(run, zh_font: str, en_font: str):
    """
    Apply fonts for mixed text at run granularity.
    If a run is mostly ASCII -> en_font else zh_font.
    Also sets eastAsia font for Chinese.

    注意：部分 run 没有 rPr/rFonts，需要先创建，否则会报 NoneType。
    """
    text = run.text or ""
    rFonts = _ensure_rpr_rfonts(run)

    if is_mostly_ascii(text):
        run.font.name = en_font
        # for Word: set ascii/hAnsi
        rFonts.set(qn("w:ascii"), en_font)
        rFonts.set(qn("w:hAnsi"), en_font)
        rFonts.set(qn("w:eastAsia"), zh_font)
    else:
        run.font.name = zh_font
        rFonts.set(qn("w:ascii"), en_font)
        rFonts.set(qn("w:hAnsi"), en_font)
        rFonts.set(qn("w:eastAsia"), zh_font)

def delete_paragraph(paragraph: Paragraph):
    """Remove paragraph from document (python-docx doesn't provide a public API)."""
    p = paragraph._element
    p.getparent().remove(p)
    paragraph._p = paragraph._element = None  # help GC

def is_effectively_blank_paragraph(p) -> bool:
    """
    更强的空段判断：把全角空格、NBSP、制表符等也视为“空”
    """
    def norm(s: str) -> str:
        return (s or "").replace("\u3000", "").replace("\xa0", "").replace("\t", "")

    text = norm(p.text)
    if text.strip():
        return False

    for r in p.runs:
        if norm(r.text).strip():
            return False
    return True
