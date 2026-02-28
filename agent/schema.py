# agent/schema.py
# 使用 pydantic 定义 LLM 输出的结构化 Schema，供解析与校验使用
from typing import List, Literal, Optional

from pydantic import BaseModel


class ParagraphTag(BaseModel):
    """单个段落的结构标签"""
    index: int                          # 段落在文档中的索引（从 0 开始）
    text_preview: str                   # 段落文本预览（不超过 100 字符）
    paragraph_type: Literal[
        "title_1",       # 一级标题
        "title_2",       # 二级标题
        "title_3",       # 三级标题
        "body",          # 正文
        "list_item",     # 列表项
        "table_caption", # 表格题注
        "figure_caption",# 图片题注
        "abstract",      # 摘要
        "keyword",       # 关键词
        "reference",     # 参考文献
        "footer",        # 页脚
        "unknown",       # 无法识别
    ]
    confidence: float                   # 置信度（0.0 ~ 1.0）
    reasoning: Optional[str] = None     # LLM 判断依据（可选）


class DocumentStructure(BaseModel):
    """整篇文档的结构分析结果"""
    doc_language: str = "zh"            # 文档主要语言，默认中文
    total_paragraphs: int               # 段落总数
    paragraphs: List[ParagraphTag]      # 各段落的标签列表
