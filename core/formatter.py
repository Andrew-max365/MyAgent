# core/formatter.py
import re
from typing import Dict, List, Set
from collections import Counter

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

def is_list_paragraph(p: Paragraph) -> bool:
    """True if paragraph is a Word numbered/bulleted list (numPr)."""
    try:
        ppr = p._p.pPr
        return bool(ppr is not None and getattr(ppr, 'numPr', None) is not None)
    except Exception:
        return False

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


def _cleanup_consecutive_blanks(doc, max_keep: int) -> int:
    """压缩连续空段：最多保留 max_keep 个（0=全删）。返回删除的空段数量。"""
    blank_run = 0
    to_delete = []
    for p in list(doc.paragraphs):
        if is_effectively_blank_paragraph(p):
            blank_run += 1
            if blank_run > max_keep:
                to_delete.append(p)
        else:
            blank_run = 0

    deleted = 0
    # 倒序删除，避免重排带来的错删
    for p in reversed(to_delete):
        delete_paragraph(p)
        deleted += 1
    return deleted


def _delete_blanks_after_roles(doc, roles: Set[str], role_getter=None) -> int:
    """删除“标题/题注后紧跟的所有空段”。返回删除数量。"""
    if role_getter is None:
        role_getter = detect_role

    deleted = 0
    i = 0
    while i < len(doc.paragraphs):
        cur = doc.paragraphs[i]
        cur_role = role_getter(cur)
        if cur_role in roles:
            while i + 1 < len(doc.paragraphs) and is_effectively_blank_paragraph(doc.paragraphs[i + 1]):
                delete_paragraph(doc.paragraphs[i + 1])
                deleted += 1
        i += 1
    return deleted


def _split_body_paragraphs_on_linebreaks(doc, role_getter=None, on_new_paragraph=None) -> int:
    """
    关键修复：
    把正文段落里的 '\n'（通常是 Shift+Enter 软回车）拆成多个段落，
    这样每一条（比如 \n1. \n2.）都能获得“首行缩进”。

    - role_getter: 用于判断某段是否为 body（默认 detect_role）。
    - on_new_paragraph(parent, child): 可选回调；当从 parent 拆出 child 时调用。
      用于“继承标签/元数据”等（例如：child 的 role 继承 parent）。

    返回：新增段落数量（插入了多少个新段落）。
    """
    if role_getter is None:
        role_getter = detect_role

    created = 0
    i = 0
    while i < len(doc.paragraphs):
        p = doc.paragraphs[i]
        if is_effectively_blank_paragraph(p):
            i += 1
            continue

        # 只拆正文；标题/题注不拆，避免破坏结构
        role = role_getter(p)
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
            created += 1
            try:
                new_p.style = p.style
            except Exception:
                pass

            if on_new_paragraph is not None:
                try:
                    on_new_paragraph(p, new_p)
                except Exception:
                    # 回调失败不应影响主流程
                    pass

            prev = new_p

        # 跳过新插入的段落
        i += len(lines)
    return created


def apply_formatting(doc, blocks: List[Block], labels: Dict[int, str], spec: Spec):
    """
    MVP：不处理真编号/列表结构，只做视觉排版（首行缩进、字体、字号、行距、段距、空行清理）。
    且会把正文中的 '\\n' 拆成多个段落，保证每条都缩进。

    返回：report(dict) —— 可直接 dump 为 JSON，用于“诊断/修复报告”。
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

    # ====== 角色映射：优先 labels，缺失才 fallback detect_role ======
    # 关键点：用 Paragraph 对象做 key，避免后续删除/插入导致“索引错位”
    orig_paras = list(doc.paragraphs)
    para_by_index = {i: p for i, p in enumerate(orig_paras)}
    label_by_para: Dict[Paragraph, str] = {}

    for b in blocks:
        role = labels.get(b.block_id)
        if not role or role == "blank":
            continue
        p = para_by_index.get(b.paragraph_index)
        if p is not None:
            label_by_para[p] = role

    def get_role(p: Paragraph) -> str:
        return label_by_para.get(p) or detect_role(p)

    # ====== Report（诊断/动作统计/可解释输出）======
    label_source = labels.get("_source", "unknown")
    # 仅统计 blocks 对应的标签，忽略 labels 里的元信息键
    label_list = [labels.get(b.block_id, "unknown") for b in blocks]
    label_counts = dict(Counter(label_list))

    # label vs fallback 规则的一致性（仅针对原始段落）
    mismatch = 0
    compared = 0
    mismatch_examples = []
    for b in blocks:
        p = para_by_index.get(b.paragraph_index)
        if p is None:
            continue
        lab = labels.get(b.block_id)
        if not lab or lab == "blank":
            continue
        compared += 1
        det = detect_role(p)
        if det != lab:
            mismatch += 1
            if len(mismatch_examples) < 5:
                mismatch_examples.append({
                    "paragraph_index": b.paragraph_index,
                    "block_id": b.block_id,
                    "label": lab,
                    "detect_role": det,
                    "text": (p.text or "")[:120],
                })

    list_para_count = sum(1 for p in orig_paras if is_list_paragraph(p))

    report = {
        "meta": {
            "paragraphs_before": len(orig_paras),
            "blank_paragraphs_before": sum(1 for p in orig_paras if is_effectively_blank_paragraph(p)),
            "list_paragraphs_before": list_para_count,
        },
        "labels": {
            "source": label_source,
            "counts": label_counts,
            "consistency": {
                "compared": compared,
                "mismatched": mismatch,
                "mismatch_rate": (mismatch / compared) if compared else 0.0,
                "mismatch_examples": mismatch_examples,
            },
        },
        "plan_executed": [
            "cleanup_consecutive_blanks",
            "delete_blanks_after_titles",
            "split_body_paragraphs_on_linebreaks",
            "apply_formatting",
        ],
        "actions": {},
        "formatted": {"counts": {}},
        "warnings": [],
    }
    # 1) 空段压缩/清理
    deleted_consecutive = _cleanup_consecutive_blanks(doc, max_blank_keep)
    report["actions"]["cleanup_consecutive_blanks_deleted"] = deleted_consecutive
    report["actions"]["cleanup_consecutive_blank_keep"] = max_blank_keep

    # 2) 标题/题注后空段删光
    deleted_after_roles = _delete_blanks_after_roles(doc, roles=set(["h1", "h2", "h3", "caption"]), role_getter=get_role)
    report["actions"]["delete_blanks_after_titles_deleted"] = deleted_after_roles

    # 3) 核心修复：拆正文段落里的软回车换行（\\n）
    def _inherit_label(parent_p, child_p):
        # 让拆分出来的新段落继承原段落的标签（避免 fallback 造成标签不一致）
        if parent_p in label_by_para and child_p not in label_by_para:
            label_by_para[child_p] = label_by_para[parent_p]

    created_by_split = _split_body_paragraphs_on_linebreaks(doc, role_getter=get_role, on_new_paragraph=_inherit_label)
    report["actions"]["split_body_new_paragraphs_created"] = created_by_split

    # 4) 套格式
    formatted_counter = Counter()
    for p in doc.paragraphs:
        if is_effectively_blank_paragraph(p):
            continue

        role = get_role(p)

        # 标题/题注：去掉段尾多余换行
        if role in ("h1", "h2", "h3", "caption"):
            _strip_trailing_newlines_in_paragraph(p)

        if role == "body":
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)

            # 缩进“清场”：避免 left/hanging 抵消 first_line
            p.paragraph_format.left_indent = Pt(0)
            p.paragraph_format.hanging_indent = Pt(0)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)

            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)
            formatted_counter["body"] += 1

        elif role in ("h1", "h2", "h3"):
            hc = heading_cfg[role]
            size = float(hc["font_size_pt"])
            bold = bool(hc["bold"])
            before = float(hc["space_before_pt"])
            after = float(hc["space_after_pt"])

            _apply_paragraph_common(p, body_line_spacing, before, after)
            p.paragraph_format.left_indent = Pt(0)
            p.paragraph_format.hanging_indent = Pt(0)
            p.paragraph_format.first_line_indent = Pt(0)
            _apply_runs_font(p, zh_font, en_font, size_pt=size, bold=bold)
            formatted_counter[role] += 1

        elif role == "caption":
            if caption_cfg:
                size = float(caption_cfg.get("font_size_pt", body_size))
                bold = bool(caption_cfg.get("bold", False))
                before = float(caption_cfg.get("space_before_pt", body_before))
                after = float(caption_cfg.get("space_after_pt", body_after))

                _apply_paragraph_common(p, body_line_spacing, before, after)
                p.paragraph_format.left_indent = Pt(0)
                p.paragraph_format.hanging_indent = Pt(0)
                p.paragraph_format.first_line_indent = Pt(0)
                _apply_runs_font(p, zh_font, en_font, size_pt=size, bold=bold)
            else:
                _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
                p.paragraph_format.left_indent = Pt(0)
                p.paragraph_format.hanging_indent = Pt(0)
                p.paragraph_format.first_line_indent = Pt(0)
                _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)

            formatted_counter["caption"] += 1

        else:
            # unknown：当正文处理，尽量不让段落漏掉缩进/字体统一
            _apply_paragraph_common(p, body_line_spacing, body_before, body_after)
            p.paragraph_format.left_indent = Pt(0)
            p.paragraph_format.hanging_indent = Pt(0)
            p.paragraph_format.first_line_indent = _first_line_indent_pt(first_line_chars, body_size)
            _apply_runs_font(p, zh_font, en_font, size_pt=body_size, bold=False)
            formatted_counter["unknown_as_body"] += 1


    # ====== 追加诊断提示（让报告更“智能体”）======
    # 1) 软回车拆段提示
    if created_by_split > 0:
        report["warnings"].append(
            f"检测到正文段落含软回车(\\n)，已自动拆分为独立段落：新增 {created_by_split} 段。"
        )

    # 2) 列表段落提示（Word 真编号/项目符号可能覆盖缩进）
    if list_para_count > 0:
        report["warnings"].append(
            f"检测到 {list_para_count} 个 Word 列表/编号段落(numPr)。其缩进可能由列表级别控制，首行缩进不一致时建议单独处理列表缩进。"
        )

    # 3) 标签一致性提示
    if compared > 0 and mismatch > 0:
        rate = report["labels"]["consistency"]["mismatch_rate"]
        report["warnings"].append(
            f"标签与回退规则(detect_role)存在不一致：{mismatch}/{compared} (≈{rate:.0%})。建议统一以 labels 为准，并逐步收敛规则/LLM 标注。"
        )

    # 4) 标题层级提示：h3 前无 h2
    roles_seq = [get_role(p) for p in doc.paragraphs if not is_effectively_blank_paragraph(p)]
    h2_seen = False
    orphan_h3 = 0
    for r in roles_seq:
        if r == "h2":
            h2_seen = True
        elif r == "h1":
            h2_seen = False
        elif r == "h3" and not h2_seen:
            orphan_h3 += 1
    if orphan_h3 > 0:
        report["warnings"].append(
            f"检测到 {orphan_h3} 个 h3 在其前方未出现 h2（可能层级断裂或标签误判）。"
        )

    report["meta"]["paragraphs_after"] = len(list(doc.paragraphs))
    report["meta"]["blank_paragraphs_after"] = sum(1 for p in doc.paragraphs if is_effectively_blank_paragraph(p))
    report["formatted"]["counts"] = dict(formatted_counter)
    return report
