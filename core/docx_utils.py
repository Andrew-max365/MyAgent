# core/docx_utils.py
import string
from typing import Iterator, List, Tuple, Union

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


ASCII_CHARS = set(string.ascii_letters + string.digits)


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


def _is_en_char(ch: str) -> bool:
    # 英文、数字、ASCII 标点和空格都归入 EN 组，便于 Word 混排统一为 TNR
    return ch.isascii()


def split_text_by_script(text: str) -> List[Tuple[str, str]]:
    """Split text into [(segment, group)] where group in {en, zh}."""
    if not text:
        return []

    out: List[Tuple[str, str]] = []
    cur_group = "en" if _is_en_char(text[0]) else "zh"
    buf = [text[0]]

    for ch in text[1:]:
        g = "en" if _is_en_char(ch) else "zh"
        if g == cur_group:
            buf.append(ch)
            continue
        out.append(("".join(buf), cur_group))
        cur_group = g
        buf = [ch]

    out.append(("".join(buf), cur_group))
    return out


def copy_run_style(src_run, dst_run):
    """Copy visual character style without changing text content."""
    try:
        if src_run.style is not None:
            dst_run.style = src_run.style
    except Exception:
        pass

    sf = src_run.font
    df = dst_run.font

    df.size = sf.size
    df.bold = sf.bold
    df.italic = sf.italic
    df.underline = sf.underline
    df.strike = sf.strike
    df.double_strike = sf.double_strike
    df.subscript = sf.subscript
    df.superscript = sf.superscript
    df.small_caps = sf.small_caps
    df.all_caps = sf.all_caps
    df.shadow = sf.shadow
    df.outline = sf.outline
    df.hidden = sf.hidden
    df.highlight_color = sf.highlight_color

    # 保留颜色（RGB/主题色）
    try:
        if sf.color is not None:
            if sf.color.rgb is not None:
                df.color.rgb = sf.color.rgb
            if sf.color.theme_color is not None:
                df.color.theme_color = sf.color.theme_color
    except Exception:
        pass


def iter_paragraph_runs(paragraph: Paragraph):
    """
    Yield all Run objects in a paragraph, including those inside w:hyperlink elements.
    python-docx's paragraph.runs only returns direct-child w:r elements, missing
    runs wrapped in hyperlinks (URLs, etc.).
    """
    from docx.text.run import Run as _Run
    for child in paragraph._p:
        if child.tag.endswith('}r'):
            yield _Run(child, paragraph)
        elif child.tag.endswith('}hyperlink'):
            for sub in child:
                if sub.tag.endswith('}r'):
                    yield _Run(sub, paragraph)


def normalize_mixed_runs(paragraph: Paragraph):
    """
    将中英混合 run 拆分为单一脚本 run，避免同一 run 只能写一套 rFonts 导致字体不一致。
    保留原 run 的颜色、加粗、斜体等样式。
    同时处理超链接（w:hyperlink）内的 run，确保 URL 等特殊文本的字体也能被正确设置。
    """
    runs = list(iter_paragraph_runs(paragraph))
    for run in runs:
        text = run.text or ""
        parts = split_text_by_script(text)
        if len(parts) <= 1:
            continue

        parent = run._element.getparent()
        anchor = run._element
        insert_pos = parent.index(anchor)

        for seg_text, _ in parts:
            new_run = paragraph.add_run(seg_text)
            copy_run_style(run, new_run)
            parent.remove(new_run._element)
            parent.insert(insert_pos, new_run._element)
            insert_pos += 1

        parent.remove(anchor)


def set_run_fonts(run, zh_font: str, en_font: str):
    """
    Apply complete Word rFonts mapping at run level:
    - ascii/hAnsi/cs -> en_font
    - eastAsia -> zh_font

    run 本身会依据文本脚本选择显示字体名，保证英文数字=TNR，中文=宋体。
    """
    text = run.text or ""
    rFonts = _ensure_rpr_rfonts(run)

    run.font.name = en_font if is_mostly_ascii(text) else zh_font
    rFonts.set(qn("w:ascii"), en_font)
    rFonts.set(qn("w:hAnsi"), en_font)
    rFonts.set(qn("w:eastAsia"), zh_font)
    rFonts.set(qn("w:cs"), en_font)


def _iter_block_items(parent) -> Iterator[Union[Paragraph, Table]]:
    """按 XML 实际顺序遍历容器内 block（段落/表格）。"""
    if hasattr(parent, "element") and getattr(parent.element, "body", None) is not None:
        # Document
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        parent_elm = parent._element
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def iter_all_paragraphs(doc) -> List[Paragraph]:
    """返回文档所有段落（含表格与嵌套表格），并保持文档流顺序。"""
    out: List[Paragraph] = []

    def walk_container(container):
        for block in _iter_block_items(container):
            if isinstance(block, Paragraph):
                out.append(block)
                continue

            # block is Table: 避免合并单元格导致重复遍历同一 tc
            seen_tc = set()
            for row in block.rows:
                for cell in row.cells:
                    tc_id = id(cell._tc)
                    if tc_id in seen_tc:
                        continue
                    seen_tc.add(tc_id)
                    walk_container(cell)

    walk_container(doc)
    return out


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
