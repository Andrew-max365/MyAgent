# core/formatter.py
import re
from typing import Dict, List
from docx.shared import Pt
from docx.enum.text import WD_LINE_SPACING
from .parser import Block
from .spec import Spec
from .docx_utils import delete_paragraph, set_run_fonts
from typing import Optional

RE_SUBTITLE_CN = re.compile(r"^\s*（[一二三四五六七八九十]+）")  # （一）（二）…

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

def _detect_role_by_existing_style(p) -> Optional[str]:
    # 优先尊重已有样式：Heading 1/2/3...
    try:
        name = (p.style.name or "").lower()
    except Exception:
        return None
    if "heading 1" in name:
        return "h1"
    if "heading 2" in name:
        return "h2"
    if "heading 3" in name:
        return "h3"
    return None

def _detect_role_by_text(p_text: str) -> str:
    t = p_text.strip()
    if t == "":
        return "blank"
    # 你的副标题：（一）（二）（三）
    if RE_SUBTITLE_CN.match(t):
        return "h3"

    # 你原本的简单规则（可按你文档继续加）
    if t.startswith("第") and "章" in t[:12]:
        return "h1"
    if t.startswith("第") and "节" in t[:12]:
        return "h2"
    if re.match(r"^\s*[一二三四五六七八九十]+、", t):
        return "h2"
    if re.match(r"^\s*\d+(\.\d+){0,3}\s+", t):
        depth = t.split()[0].count(".")
        return "h2" if depth <= 0 else "h3"

    return "body"

def _delete_blank_after_headings(doc, heading_roles: set[str]):
    """
    删除“标题后紧跟的空段”，避免出现你说的“副标题和正文之间隔了一个空行”
    """
    paras = list(doc.paragraphs)
    to_delete = []
    for i in range(len(paras) - 1):
        cur = paras[i]
        nxt = paras[i + 1]
        cur_role = _detect_role_by_existing_style(cur) or _detect_role_by_text(cur.text or "")
        if cur_role in heading_roles:
            if (nxt.text or "").strip() == "":
                to_delete.append(i + 1)

    # 从后往前删
    for idx in sorted(to_delete, reverse=True):
        delete_paragraph(doc.paragraphs[idx])

def _cleanup_consecutive_blanks(doc, max_keep: int):
    # 压缩连续空段：最多保留 max_keep 个
    paras = list(doc.paragraphs)
    blank_run = 0
    to_delete = []
    for i, p in enumerate(paras):
        if (p.text or "").strip() == "":
            blank_run += 1
            if blank_run > max_keep:
                to_delete.append(i)
        else:
            blank_run = 0
    for idx in sorted(to_delete, reverse=True):
        delete_paragraph(doc.paragraphs[idx])

def apply_formatting(doc, blocks: List[Block], labels: Dict[int, str], spec: Spec):
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
    cleanup_cfg = cfg.get("cleanup", {})
    max_blank_keep = int(cleanup_cfg.get("max_consecutive_blank_paragraphs", 1))

    # 1) 先压缩连续空段（保留最多1个）
    _cleanup_consecutive_blanks(doc, max_blank_keep)

    # 2) 再删：标题后紧跟的空段（你提到的“副标题和正文隔一行”）
    _delete_blank_after_headings(doc, heading_roles={"h1", "h2", "h3"})

    # 3) 逐段套格式
    for p in doc.paragraphs:
        text = p.text or ""
        if text.strip() == "":
            continue

        role = _detect_role_by_existing_style(p) or _detect_role_by_text(text)

        if role == "body":
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)  # ✅ 修复缩进
            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)

        elif role in ("h1", "h2", "h3"):
            hc = heading_cfg[role]
            size = float(hc["font_size_pt"])
            bold = bool(hc["bold"])
            before = float(hc["space_before_pt"])
            after = float(hc["space_after_pt"])

            _apply_paragraph_common(p, body_line_spacing, before, after)
            p.paragraph_format.first_line_indent = Pt(0)  # 标题一般不缩进
            _apply_runs_font(p, zh_font, en_font, size_pt=size, bold=bold)

        else:
            # 其他类型先按正文处理（后续可扩展 quote/caption/code）
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)
            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)