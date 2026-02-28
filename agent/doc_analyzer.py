# agent/doc_analyzer.py
# 文档结构分析 Agent：从 docx 提取段落，调用 LLMClient，返回 DocumentStructure
from __future__ import annotations

from typing import Optional

from agent.llm_client import LLMClient, LLMCallError
from agent.schema import DocumentStructure


class DocAnalyzer:
    """
    文档结构分析器。
    负责从 python-docx Document 对象中提取段落文本，
    调用 LLMClient 进行结构分析，并返回 DocumentStructure。
    """

    def __init__(self, client: Optional[LLMClient] = None):
        # 允许注入自定义 LLMClient，便于测试和替换
        self.client = client or LLMClient()

    @staticmethod
    def extract_paragraphs(doc) -> list[str]:
        """
        从 python-docx Document 对象中提取所有段落的文本。

        :param doc: python-docx Document 对象
        :return: 段落文本列表（保留空段落占位，以保持索引对应关系）
        """
        # 遍历文档所有段落（含表格外段落）
        return [p.text for p in doc.paragraphs]

    def analyze(self, doc) -> DocumentStructure:
        """
        分析文档结构，返回结构化标签结果。

        :param doc: python-docx Document 对象
        :return: DocumentStructure 实例
        :raises LLMCallError: LLM 调用或解析失败时抛出
        """
        paragraphs = self.extract_paragraphs(doc)
        return self.client.call_structured(paragraphs)

    def analyze_from_path(self, docx_path: str) -> DocumentStructure:
        """
        从文件路径加载 docx 并分析文档结构。

        :param docx_path: .docx 文件路径
        :return: DocumentStructure 实例
        :raises LLMCallError: LLM 调用或解析失败时抛出
        """
        try:
            from docx import Document
        except ImportError as e:
            raise LLMCallError("python-docx 包未安装，请执行 pip install python-docx>=1.1.0") from e

        doc = Document(docx_path)
        return self.analyze(doc)
