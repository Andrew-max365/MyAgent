# agent/prompt_templates.py
# Prompt 模板管理：系统 Prompt 和用户 Prompt 模板
from typing import List

# 系统 Prompt：告知模型角色与输出格式要求
SYSTEM_PROMPT = (
    "你是一个专业的中文学术/公文文档结构分析专家。\n"
    "你的任务是分析给定的 Word 文档段落列表，为每个段落打上结构标签。\n"
    "你必须严格按照 JSON Schema 输出，不得包含任何额外说明文字。\n"
    "输出的 JSON 必须包含字段：doc_language, total_paragraphs, paragraphs（数组）。\n"
    "每个段落必须包含：index, text_preview, paragraph_type, confidence, reasoning。\n"
    "paragraph_type 只能取以下值之一：\n"
    "  title_1, title_2, title_3, body, list_item, table_caption,\n"
    "  figure_caption, abstract, keyword, reference, footer, unknown\n"
    "confidence 为 0.0~1.0 之间的浮点数，表示分类的置信度。"
)


def build_user_prompt(paragraphs: List[str]) -> str:
    """
    构造用户 Prompt。

    :param paragraphs: 文档段落文本列表（已去除空段落），每段最多取前50字作为预览
    :return: 格式化后的用户 Prompt 字符串
    """
    n = len(paragraphs)
    # 每段最多取前50字作为预览，避免 Prompt 过长
    lines = "\n".join(
        f"  序号{i}: \"{text[:50]}{'...' if len(text) > 50 else ''}\""
        for i, text in enumerate(paragraphs)
    )
    return (
        f"请分析以下中文文档的段落结构，共 {n} 个段落：\n\n"
        f"{lines}\n\n"
        "请输出符合 Schema 的 JSON。"
    )
