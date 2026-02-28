# agent/prompt_templates.py
# Prompt 模板管理：系统 Prompt 与用户 Prompt 构建函数
from __future__ import annotations

import json
from typing import List

# 系统 Prompt：指导 LLM 以专家身份分析文档结构并严格输出 JSON
SYSTEM_PROMPT: str = (
    "你是一个专业的中文学术/公文文档结构分析专家。\n"
    "你的任务是分析给定的 Word 文档段落列表，为每个段落打上结构标签。\n"
    "你必须严格按照 JSON Schema 输出，不得包含任何额外说明文字。\n"
    "输出的 JSON 必须包含字段：doc_language, total_paragraphs, paragraphs（数组）。\n"
    "每个段落必须包含：index, text_preview, paragraph_type, confidence, reasoning。\n"
    "paragraph_type 只能从以下值中选择：\n"
    "  title_1, title_2, title_3, body, list_item, table_caption,\n"
    "  figure_caption, abstract, keyword, reference, footer, unknown\n"
    "confidence 为 0.0~1.0 之间的浮点数，表示判断置信度。"
)


def build_user_prompt(paragraphs: List[str]) -> str:
    """
    根据段落列表构造用户 Prompt。

    :param paragraphs: 文档段落文本列表（按文档顺序）
    :return: 格式化后的用户 Prompt 字符串
    """
    # 将段落列表序列化为 JSON，截断过长文本避免超出 token 限制
    items = [
        {
            "index": i,
            "text_preview": text[:200],  # 每段最多取 200 字符预览
        }
        for i, text in enumerate(paragraphs)
    ]
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    return (
        f"请分析以下 {len(paragraphs)} 个文档段落，为每个段落打上结构标签。\n\n"
        f"段落列表（JSON）：\n{payload}\n\n"
        "请按照系统 Prompt 中的 JSON Schema 格式输出分析结果，不得包含额外说明。"
    )
