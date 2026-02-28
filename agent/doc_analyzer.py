# agent/doc_analyzer.py
# 文档结构分析器：从 docx 提取段落文本，调用 LLMClient，返回 DocumentStructure
from docx import Document

from agent.llm_client import LLMClient
from agent.prompt_templates import build_user_prompt
from agent.schema import DocumentStructure


class DocAnalyzer:
    """
    文档分析器。
    负责从 .docx 文件中提取段落文本，构造 Prompt，调用大模型完成结构分析。
    """

    def __init__(self):
        # 初始化 LLM 客户端
        self.llm = LLMClient()

    def extract_paragraphs(self, doc_path: str) -> list[str]:
        """
        提取 docx 文档中所有非空段落的文本。

        :param doc_path: .docx 文件路径
        :return: 非空段落文本列表
        """
        doc = Document(doc_path)
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    def analyze(self, doc_path: str) -> DocumentStructure:
        """
        分析 docx 文档结构，返回结构化标签结果。

        :param doc_path: .docx 文件路径
        :return: DocumentStructure 对象
        """
        paragraphs = self.extract_paragraphs(doc_path)
        prompt = build_user_prompt(paragraphs)
        return self.llm.analyze_document(prompt)
