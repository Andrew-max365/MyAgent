# core/judge.py
import re
import warnings
from typing import Dict, List

from .parser import Block
from .docx_utils import iter_all_paragraphs

# 兼容：无 doc 情况下的简易规则（保留）
RE_H1 = re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+章")
RE_H2 = re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+节")
RE_CN_ENUM = re.compile(r"^\s*[一二三四五六七八九十]+、")
RE_NUM_DOT = re.compile(r"^\s*\d+(\.\d+){0,3}\s+")  # 1 / 1.1 / 1.1.1

def rule_based_labels(blocks: List[Block], doc=None) -> Dict[int, str]:
    """
    returns: {block_id: role} where role in:
      - blank
      - h1 / h2 / h3
      - caption
      - body

    优化点：
    - 如果传入 doc（python-docx Document），则优先对“真实段落对象”调用 formatter.detect_role，
      这样会考虑 Word 标题样式、题注、以及段内多行结构等，和后续 apply_formatting 的 fallback 规则保持一致。
    - 若未传入 doc，则退回到简单 regex 规则（兼容旧调用方式）。
    """
    labels: Dict[int, str] = {}

    if doc is not None:
        try:
            # 注意：这里导入的是你优化后的 formatter（若你直接替换文件名，可改回 .formatter）
            from .formatter import detect_role
            paras = iter_all_paragraphs(doc)
            for b in blocks:
                p = paras[b.paragraph_index] if 0 <= b.paragraph_index < len(paras) else None
                if p is None:
                    # 段落越界则退回文本规则
                    text = (b.text or "").strip()
                    labels[b.block_id] = "blank" if text == "" else "body"
                    continue
                labels[b.block_id] = detect_role(p)
            return labels
        except Exception as e:
            warnings.warn(
                f"[judge] detect_role via doc failed, falling back to regex rules: {e}",
                stacklevel=2,
            )

    # -------- fallback: regex rules over plain text --------
    for b in blocks:
        text = (b.text or "").strip()
        if text == "":
            labels[b.block_id] = "blank"
            continue

        if RE_H1.match(text):
            labels[b.block_id] = "h1"
        elif RE_H2.match(text):
            labels[b.block_id] = "h2"
        elif RE_NUM_DOT.match(text):
            depth = text.split()[0].count(".")
            labels[b.block_id] = "h2" if depth <= 0 else "h3"
        elif RE_CN_ENUM.match(text):
            labels[b.block_id] = "h2"
        else:
            labels[b.block_id] = "body"

    return labels
