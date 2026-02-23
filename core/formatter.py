# core/formatter.py
import re
from typing import Dict, List, Set

from docx.shared import Pt
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from .parser import Block
from .spec import Spec
from .docx_utils import delete_paragraph, set_run_fonts, is_effectively_blank_paragraph


# =========================
# Regex rules
# =========================

RE_SUBTITLE_CN = re.compile(r"^\s*（[一二三四五六七八九十]+）")  # （一）
RE_CAPTION = re.compile(
    r"^\s*(图|表|Figure|Fig\.|Table)\s*[\d一二三四五六七八九十]+([\-–—]\d+)?",
    re.IGNORECASE
)

RE_CN_ENUM = re.compile(r"^\s*[一二三四五六七八九十]+、")
RE_NUM_DOT = re.compile(r"^\s*\d+(\.\d+){0,3}\s+")

# 段内多行结构（避免误判标题）
RE_MULTILINE_NUM = re.compile(r"\n\s*\d+(\.\d+)*\s+")
RE_MULTILINE_SUB = re.compile(r"\n\s*（[一二三四五六七八九十]+）")


# =========================
# Helpers
# =========================

def looks_like_multiline_numbered_block(text: str) -> bool:
    t = text or ""
    return bool(RE_MULTILINE_NUM.search(t)) or bool(RE_MULTILINE_SUB.search(t))


def _clear_paragraph_runs(p):
    """彻底清空 run（含 br），用于重建文本。"""
    for child in list(p._p):
        if child.tag.endswith("}r"):
            p._p.remove(child)


def _strip_trailing_newlines_in_paragraph(p):
    txt = p.text or ""
    new_txt = txt.rstrip("\r\n")
    if new_txt == txt:
        return
    _clear_paragraph_runs(p)
    p.add_run(new_txt)


def _insert_paragraph_after(p, text: str):
    """在段落 p 后插入新段落（稳定版），并写入 text。"""
    new_p = OxmlElement('w:p')
    p._p.addnext(new_p)
    new_para = Paragraph(new_p, p._parent)
    new_para.add_run(text)
    return new_para


# =========================
# Role detection
# =========================

def detect_role(paragraph) -> str:
    """
    blank / h1 / h2 / h3 / caption / body
    注意：我们不做真编号/列表结构，1.2.3. 一律当正文 body。
    """
    if is_effectively_blank_paragraph(paragraph):
        return "blank"

    text = paragraph.text or ""

    # 段内多行编号块强制当正文，避免误判标题
    if looks_like_multiline_numbered_block(text):
        return "body"

    # 优先尊重 Word 标题样式
    style_name = ""
    try:
        style_name = (paragraph.style.name or "").lower()
    except Exception:
        style_name = ""
    if "heading 1" in style_name:
        return "h1"
    if "heading 2" in style_name:
        return "h2"
    if "heading 3" in style_name:
        return "h3"

    t = text.strip()

    if RE_CAPTION.match(t):
        return "caption"
    if RE_SUBTITLE_CN.match(t):
        return "h3"

    if t.startswith("第") and "章" in t[:12]:
        return "h1"
    if t.startswith("第") and "节" in t[:12]:
        return "h2"
    if RE_CN_ENUM.match(t):
        return "h2"
    if RE_NUM_DOT.match(t):
        depth = t.split()[0].count(".")
        return "h2" if depth <= 0 else "h3"

    return "body"


# =========================
# Formatting helpers
# =========================

def _apply_paragraph_common(p, line_spacing: float, space_before_pt: float, space_after_pt: float):
    pf = p.paragraph_format
    pf.space_before = Pt(space_before_pt)
    pf.space_after = Pt(space_after_pt)
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = line_spacing


def _apply_runs_font(p, zh_font: str, en_font: str, size_pt: float, bold: bool):
    for run in p.runs:
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        set_run_fonts(run, zh_font=zh_font, en_font=en_font)


def _first_line_indent_pt(chars: int, font_size_pt: float) -> Pt:
    # 近似：1 个中文字符宽度 ≈ 1 个字号(pt)
    return Pt(chars * font_size_pt)


def _cleanup_consecutive_blanks(doc, max_keep: int):
    """压缩连续空段：最多保留 max_keep 个（0=全删）。"""
    paras = list(doc.paragraphs)
    blank_run = 0
    to_delete = []
    for i, p in enumerate(paras):
        if is_effectively_blank_paragraph(p):
            blank_run += 1
            if blank_run > max_keep:
                to_delete.append(i)
        else:
            blank_run = 0
    for idx in sorted(to_delete, reverse=True):
        delete_paragraph(doc.paragraphs[idx])


def _delete_blanks_after_roles(doc, roles: Set[str]):
    """删除“标题/题注后紧跟的所有空段”。"""
    i = 0
    while i < len(doc.paragraphs):
        cur = doc.paragraphs[i]
        cur_role = detect_role(cur)
        if cur_role in roles:
            while i + 1 < len(doc.paragraphs) and is_effectively_blank_paragraph(doc.paragraphs[i + 1]):
                delete_paragraph(doc.paragraphs[i + 1])
        i += 1


def _split_body_paragraphs_on_linebreaks(doc):
    """
    关键修复：
    把正文段落里的 '\\n'（通常是 Shift+Enter 软回车）拆成多个段落，
    这样每一条（比如 \\n1. \\n2.）都能获得“首行缩进”。
    """
    i = 0
    while i < len(doc.paragraphs):
        p = doc.paragraphs[i]
        if is_effectively_blank_paragraph(p):
            i += 1
            continue

        # 只拆正文；标题/题注不拆，避免破坏结构
        role = detect_role(p)
        if role != "body":
            i += 1
            continue

        text = p.text or ""
        if "\n" not in text:
            i += 1
            continue

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) <= 1:
            i += 1
            continue

        # 当前段落替换成第一行
        _clear_paragraph_runs(p)
        p.add_run(lines[0])

        # 后续行插入为新段落，复制样式
        prev = p
        for ln in lines[1:]:
            new_p = _insert_paragraph_after(prev, ln)
            try:
                new_p.style = p.style
            except Exception:
                pass
            prev = new_p

        # 跳过新插入的段落
        i += len(lines)


# =========================
# Main entry
# =========================

def apply_formatting(doc, blocks: List[Block], labels: Dict[int, str], spec: Spec):
    """
    MVP：不处理真编号/列表结构，只做视觉排版（首行缩进、字体、字号、行距、段距、空行清理）。
    且会把正文中的 '\\n' 拆成多个段落，保证每条都缩进。
    """
    cfg = spec.raw
    zh_font = cfg["fonts"]["zh"]
    en_font = cfg["fonts"]["en"]

    body_cfg = cfg["body"]
    body_size = float(body_cfg["font_size_pt"])
    body_line_spacing = float(body_cfg["line_spacing"])
    body_before = float(body_cfg["space_before_pt"])
    body_after = float(body_cfg["space_after_pt"])
    first_line_chars = int(body_cfg["first_line_chars"])

    heading_cfg = cfg["heading"]
    caption_cfg = cfg.get("caption", None)

    cleanup_cfg = cfg.get("cleanup", {})
    max_blank_keep = int(cleanup_cfg.get("max_consecutive_blank_paragraphs", 1))

    # 1) 空段压缩/清理
    _cleanup_consecutive_blanks(doc, max_blank_keep)

    # 2) 标题/题注后空段删光
    _delete_blanks_after_roles(doc, roles=set(["h1", "h2", "h3", "caption"]))

    # 3) 核心修复：拆正文段落里的软回车换行（\\n）
    _split_body_paragraphs_on_linebreaks(doc)

    # 4) 套格式
    for p in doc.paragraphs:
        if is_effectively_blank_paragraph(p):
            continue

        role = detect_role(p)

        # 标题/题注：去掉段尾多余换行
        if role in ("h1", "h2", "h3", "caption"):
            _strip_trailing_newlines_in_paragraph(p)

        if role == "body":
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)
            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)

        elif role in ("h1", "h2", "h3"):
            hc = heading_cfg[role]
            size = float(hc["font_size_pt"])
            bold = bool(hc["bold"])
            before = float(hc["space_before_pt"])
            after = float(hc["space_after_pt"])

            _apply_paragraph_common(p, body_line_spacing, before, after)
            p.paragraph_format.first_line_indent = Pt(0)
            _apply_runs_font(p, zh_font, en_font, size_pt=size, bold=bold)

        elif role == "caption":
            if caption_cfg:
                size = float(caption_cfg.get("font_size_pt", body_size))
                bold = bool(caption_cfg.get("bold", False))
                before = float(caption_cfg.get("space_before_pt", 0))
                after = float(caption_cfg.get("space_after_pt", 0))
                align_center = bool(caption_cfg.get("center", True))

                _apply_paragraph_common(p, body_line_spacing, before, after)
                p.paragraph_format.first_line_indent = Pt(0)

                if align_center:
                    try:
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    except Exception:
                        pass

                _apply_runs_font(p, zh_font, en_font, size_pt=size, bold=bold)
            else:
                _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
                p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)
                _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)

        else:
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)
            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)