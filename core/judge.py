# core/judge.py
import re
from typing import Dict, List
from .parser import Block

# 一些常见标题模式（你可继续加）
RE_H1 = re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+章")
RE_H2 = re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+节")
RE_CN_ENUM = re.compile(r"^\s*[一二三四五六七八九十]+、")
RE_NUM_DOT = re.compile(r"^\s*\d+(\.\d+){0,3}\s+")  # 1 / 1.1 / 1.1.1

def rule_based_labels(blocks: List[Block]) -> Dict[int, str]:
    """
    returns: {block_id: role} where role in:
      - blank
      - h1 / h2 / h3
      - body
    """
    labels: Dict[int, str] = {}

    for b in blocks:
        text = b.text.strip()
        if text == "":
            labels[b.block_id] = "blank"
            continue

        if RE_H1.match(text):
            labels[b.block_id] = "h1"
        elif RE_H2.match(text):
            labels[b.block_id] = "h2"
        elif RE_NUM_DOT.match(text):
            # 数字标题：1 1.1 1.1.1 大概率是标题（这里先统一当 h2/h3）
            # 简单策略：层级越深越小
            depth = text.split()[0].count(".")
            labels[b.block_id] = "h2" if depth <= 0 else "h3"
        elif RE_CN_ENUM.match(text):
            labels[b.block_id] = "h2"
        else:
            labels[b.block_id] = "body"

    return labels