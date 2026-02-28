# agent/schema.py
# 使用 pydantic 定义结构化输出 Schema，供 LLM 输出解析使用
from typing import List, Literal, Optional

from pydantic import BaseModel


class ParagraphTag(BaseModel):
    """单个段落的结构标签"""

    # 段落在文档中的序号（0-based）
    index: int
    # 段落前20字预览
    text_preview: str
    # 段落类型标签
    paragraph_type: Literal[
        "title_1",      # 一级标题
        "title_2",      # 二级标题
        "title_3",      # 三级标题
        "body",         # 正文
        "list_item",    # 列表项
        "table_caption",   # 表格题注
        "figure_caption",  # 图片题注
        "abstract",     # 摘要
        "keyword",      # 关键词
        "reference",    # 参考文献
        "footer",       # 页脚
        "unknown",      # 未知类型
    ]
    # 置信度 0.0~1.0
    confidence: float
    # 模型推理说明（可选）
    reasoning: Optional[str] = None


class DocumentStructure(BaseModel):
    """整个文档的结构化分析结果"""

    # 文档语言
    doc_language: str = "zh"
    # 文档总段落数
    total_paragraphs: int
    # 各段落的标签列表
    paragraphs: List[ParagraphTag]
