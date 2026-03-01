# agent/schema.py
# 使用 pydantic 定义结构化输出 Schema，供 LLM 输出解析使用
from typing import List, Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 校对问题（LLM 仅做错别字/标点/规范性校对，不做结构标注）
# ---------------------------------------------------------------------------

class ProofreadIssue(BaseModel):
    """单条校对问题（由 LLM 校对模块产出）"""

    # 问题类型：错别字 / 标点符号 / 规范性
    issue_type: Literal["typo", "punctuation", "standardization"]
    # 严重程度
    severity: Literal["low", "medium", "high"]
    # 关联段落序号（可选）
    paragraph_index: Optional[int] = None
    # 原文中有问题的片段
    evidence: str
    # 建议的修改内容
    suggestion: str
    # 问题说明
    rationale: str


class DocumentProofread(BaseModel):
    """文档校对结果（仅含错别字、标点、规范性问题，不做结构分析）"""

    doc_language: str = "zh"
    # 校对问题列表（供提交者自行修改，不自动应用）
    issues: List[ProofreadIssue] = []


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


# ---------------------------------------------------------------------------
# 语义建议（LLM 语义审阅输出）
# ---------------------------------------------------------------------------

class LLMSuggestion(BaseModel):
    """单条语义建议，由 LLM Reviewer 产出"""

    # 建议类别：标题层级 / 歧义风险 / 结构改写 / 文体风格 / 术语一致
    category: Literal["hierarchy", "ambiguity", "structure", "style", "terminology"]
    # 严重程度
    severity: Literal["low", "medium", "high"]
    # 建议置信度 0.0~1.0
    confidence: float
    # 原文片段或定位信息（"段落 N: <片段>"）
    evidence: str
    # 建议内容（具体可执行的修改建议）
    suggestion: str
    # 建议原因（为什么提出这条建议）
    rationale: str
    # 应用方式：auto（可自动应用）/ manual（需人工确认，默认）
    apply_mode: Literal["auto", "manual"] = "manual"
    # 关联段落索引（可选）
    paragraph_index: Optional[int] = None


class DocumentReview(BaseModel):
    """文档语义审阅结果（含结构标签 + 可执行建议列表）

    llm 模式：全量结构标签 + 全文建议
    hybrid 模式（触发时）：仅触发段落的标签建议
    """

    doc_language: str = "zh"
    # 本次审阅覆盖的段落数（llm 为总段落数，hybrid 为触发段落数）
    total_paragraphs: int
    # 各段落的结构标签
    paragraphs: List[ParagraphTag]
    # 语义建议列表（区分"已自动应用"与"仅建议未应用"由 apply_mode 标识）
    suggestions: List[LLMSuggestion] = []
