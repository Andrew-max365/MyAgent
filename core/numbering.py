# core/numbering.py
"""
Word document list/numbering utilities.

Converts text-based list markers (e.g. "（1）", "1)", "①") into real
Word numbered list paragraphs (numPr + abstractNum/num definitions).
"""

import re
from typing import Dict, List, Optional, Tuple

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


# ─── List pattern detection ───────────────────────────────────────────────────

_RE_PAREN_ARABIC = re.compile(r"^(\s*（)(\d+)(）)")           # （1）
_RE_RPAREN       = re.compile(r"^(\s*)(\d+)([)）])(\s)")      # 1) or 1）<space>
_RE_NUM_DOT      = re.compile(r"^(\s*)(\d+)(\. )")             # 1. text
_RE_ENCLOSED     = re.compile(
    r"^\s*([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])"
)
_RE_ALPHA_LOWER  = re.compile(r"^\s*([a-z])[.)]\s", re.ASCII)
_RE_ALPHA_UPPER  = re.compile(r"^\s*([A-Z])[.)]\s", re.ASCII)

_ENCLOSED_ORD: Dict[str, int] = {
    '①': 1,  '②': 2,  '③': 3,  '④': 4,  '⑤': 5,
    '⑥': 6,  '⑦': 7,  '⑧': 8,  '⑨': 9,  '⑩': 10,
    '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
    '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20,
}

# Supported format keys
LIST_FMTS = ("paren_arabic", "rparen", "num_dot", "enclosed", "alpha_lower", "alpha_upper")

# Map format key → (w:numFmt value, w:lvlText value)
_FMT_TO_WORD: Dict[str, Tuple[str, str]] = {
    "paren_arabic": ("decimal",                "（%1）"),  # full-width parentheses
    "rparen":       ("decimal",                "%1)"),
    "num_dot":      ("decimal",                "%1."),    # 1. 2. 3.
    "enclosed":     ("decimalEnclosedCircle",   "%1"),
    "alpha_lower":  ("lowerLetter",             "%1."),
    "alpha_upper":  ("upperLetter",             "%1."),
}


def detect_text_list_prefix(text: str) -> Optional[Tuple[str, int, int]]:
    """
    Detect a text-based list marker at the start of *text*.

    Returns ``(fmt, ordinal, prefix_char_count)`` or ``None``.

    - ``fmt``               – one of :data:`LIST_FMTS`
    - ``ordinal``           – 1-based ordinal of this marker (e.g. 2 for "（2）")
    - ``prefix_char_count`` – number of Unicode codepoints to strip from the
                              paragraph text to remove the marker (includes
                              any leading whitespace in the match)
    """
    t = text or ""
    m = _RE_PAREN_ARABIC.match(t)
    if m:
        return ("paren_arabic", int(m.group(2)), m.end())
    m = _RE_RPAREN.match(t)
    if m:
        return ("rparen", int(m.group(2)), m.end())
    m = _RE_NUM_DOT.match(t)
    if m:
        return ("num_dot", int(m.group(2)), m.end())
    m = _RE_ENCLOSED.match(t)
    if m:
        ch = m.group(1)
        return ("enclosed", _ENCLOSED_ORD.get(ch, 1), m.end())
    m = _RE_ALPHA_LOWER.match(t)
    if m:
        return ("alpha_lower", ord(m.group(1)) - ord('a') + 1, m.end())
    m = _RE_ALPHA_UPPER.match(t)
    if m:
        return ("alpha_upper", ord(m.group(1)) - ord('A') + 1, m.end())
    return None


# ─── Numbering XML helpers ────────────────────────────────────────────────────

def _numbering_element(doc):
    """Return the ``w:numbering`` XML element from the document's numbering part."""
    return doc.part.numbering_part._element


def _next_free_id(nelem) -> int:
    """
    Return the next unused integer ID that can be used for both
    ``w:abstractNumId`` and ``w:numId``.  We take max of all existing IDs + 1.
    """
    used = set()
    for child in nelem:
        for attr in (qn("w:abstractNumId"), qn("w:numId")):
            val = child.get(attr)
            if val is not None:
                try:
                    used.add(int(val))
                except ValueError:
                    pass
    return max(used, default=0) + 1


def _build_abstractNum(abs_id: int, fmt: str, left_twips: int, hanging_twips: int):
    """Build a ``w:abstractNum`` XML element for a single-level list."""
    num_fmt_val, lvl_text_val = _FMT_TO_WORD[fmt]

    abstractNum = OxmlElement("w:abstractNum")
    abstractNum.set(qn("w:abstractNumId"), str(abs_id))

    mlt = OxmlElement("w:multiLevelType")
    mlt.set(qn("w:val"), "singleLevel")
    abstractNum.append(mlt)

    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")

    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    lvl.append(start)

    numFmt = OxmlElement("w:numFmt")
    numFmt.set(qn("w:val"), num_fmt_val)
    lvl.append(numFmt)

    lvlText = OxmlElement("w:lvlText")
    lvlText.set(qn("w:val"), lvl_text_val)
    lvl.append(lvlText)

    lvlJc = OxmlElement("w:lvlJc")
    lvlJc.set(qn("w:val"), "left")
    lvl.append(lvlJc)

    pPr = OxmlElement("w:pPr")
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), str(left_twips))
    ind.set(qn("w:hanging"), str(hanging_twips))
    pPr.append(ind)
    lvl.append(pPr)

    abstractNum.append(lvl)
    return abstractNum


def _build_num(num_id: int, abs_id: int):
    """Build a ``w:num`` element that references an ``w:abstractNum``."""
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstractNumId = OxmlElement("w:abstractNumId")
    abstractNumId.set(qn("w:val"), str(abs_id))
    num.append(abstractNumId)
    return num


def _insert_before_first_num(nelem, new_abstractNum):
    """Insert abstractNum before the first w:num child (required by schema order)."""
    first_num = None
    for child in nelem:
        if child.tag == qn("w:num"):
            first_num = child
            break
    if first_num is not None:
        nelem.insert(list(nelem).index(first_num), new_abstractNum)
    else:
        nelem.append(new_abstractNum)


def create_list_num_id(doc, fmt: str, left_twips: int = 720, hanging_twips: int = 360) -> int:
    """
    Add a new single-level numbered list definition to the document's numbering
    part for the given ``fmt`` (one of :data:`LIST_FMTS`).

    Returns the ``w:numId`` value that should be used in ``w:numPr``.
    """
    nelem = _numbering_element(doc)
    new_id = _next_free_id(nelem)

    abs_num = _build_abstractNum(new_id, fmt, left_twips, hanging_twips)
    _insert_before_first_num(nelem, abs_num)

    num = _build_num(new_id, new_id)
    nelem.append(num)

    return new_id


def apply_numpr(paragraph: Paragraph, num_id: int, ilvl: int = 0):
    """Write ``w:numPr`` onto *paragraph*, giving it real Word list numbering."""
    pPr = paragraph._p.get_or_add_pPr()

    # Remove any existing numPr to avoid duplicates
    existing = pPr.find(qn("w:numPr"))
    if existing is not None:
        pPr.remove(existing)

    numPr = OxmlElement("w:numPr")
    ilvl_elem = OxmlElement("w:ilvl")
    ilvl_elem.set(qn("w:val"), str(ilvl))
    numId_elem = OxmlElement("w:numId")
    numId_elem.set(qn("w:val"), str(num_id))
    numPr.append(ilvl_elem)
    numPr.append(numId_elem)
    pPr.append(numPr)


def strip_list_text_prefix(paragraph: Paragraph, prefix_char_count: int):
    """
    Strip the first *prefix_char_count* Unicode codepoints from the paragraph
    text (distributed across runs), removing the text-based list marker that
    was already converted to a real ``w:numPr`` list.

    After stripping, any remaining leading whitespace on the first run is also
    removed so the list text starts cleanly.
    """
    runs = list(paragraph.runs)
    remaining = prefix_char_count
    for run in runs:
        text = run.text or ""
        if remaining <= 0:
            break
        if len(text) <= remaining:
            run.text = ""
            remaining -= len(text)
        else:
            run.text = text[remaining:]
            remaining = 0

    # Strip any leading whitespace left on the first non-empty run
    for run in paragraph.runs:
        if run.text:
            run.text = run.text.lstrip()
            break


# ─── High-level group conversion ─────────────────────────────────────────────

def convert_text_lists(
    doc,
    paragraphs: List[Paragraph],
    get_role,
    is_list_paragraph_fn,
    is_blank_fn,
    min_run_len: int = 1,
    left_twips: int = 720,
    hanging_twips: int = 360,
) -> int:
    """
    Scan *paragraphs* for runs of consecutive text-based ``list_item``
    paragraphs (i.e. those whose text starts with a recognised list marker
    but that do **not** already carry ``w:numPr``).

    For each run that is at least *min_run_len* items long and uses the same
    list format, this function:

    1. Creates a Word numbering definition (abstractNum + num).
    2. Applies ``w:numPr`` to every paragraph in the run.
    3. Strips the text prefix from each paragraph.

    *min_run_len* controls the minimum consecutive run length required before
    conversion.  The default is 1, meaning even a single isolated list item
    will be converted.  Set to 2 or higher to require at least that many
    consecutive items before converting.

    Returns the total number of paragraphs converted.
    """
    # Group consecutive text-based list_item paragraphs by format.
    # A group resets whenever: blank para, non-list_item role, already-real
    # numPr, or a format change.
    groups: List[List[Tuple[Paragraph, str, int, int]]] = []
    current: List[Tuple[Paragraph, str, int, int]] = []
    current_fmt: Optional[str] = None

    for p in paragraphs:
        if is_blank_fn(p):
            if current:
                groups.append(current)
                current = []
                current_fmt = None
            continue

        role = get_role(p)
        if role != "list_item" or is_list_paragraph_fn(p):
            # Either not a list item, or already has real numPr
            if current:
                groups.append(current)
                current = []
                current_fmt = None
            continue

        text = p.text or ""
        result = detect_text_list_prefix(text)
        if result is None:
            if current:
                groups.append(current)
                current = []
                current_fmt = None
            continue

        fmt, ordinal, prefix_len = result
        if fmt != current_fmt:
            if current:
                groups.append(current)
            current = [(p, fmt, ordinal, prefix_len)]
            current_fmt = fmt
        else:
            current.append((p, fmt, ordinal, prefix_len))

    if current:
        groups.append(current)

    # Convert qualifying groups
    converted = 0
    for group in groups:
        if len(group) < min_run_len:
            continue
        fmt = group[0][1]
        num_id = create_list_num_id(doc, fmt, left_twips, hanging_twips)
        for p, _fmt, _ord, prefix_len in group:
            apply_numpr(p, num_id)
            strip_list_text_prefix(p, prefix_len)
            converted += 1

    return converted
