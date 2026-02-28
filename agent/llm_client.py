# agent/llm_client.py
# 封装对大模型 API 的调用（使用 openai SDK）
from __future__ import annotations

import json
import re
from typing import Any, List

import openai

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_S
from agent.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from agent.schema import DocumentStructure

ALLOWED_PARAGRAPH_TYPES = {
    "title_1",
    "title_2",
    "title_3",
    "body",
    "list_item",
    "table_caption",
    "figure_caption",
    "abstract",
    "keyword",
    "reference",
    "footer",
    "unknown",
}

PARAGRAPH_TYPE_ALIASES = {
    "title1": "title_1",
    "heading1": "title_1",
    "h1": "title_1",
    "一级标题": "title_1",
    "title2": "title_2",
    "heading2": "title_2",
    "h2": "title_2",
    "二级标题": "title_2",
    "title3": "title_3",
    "heading3": "title_3",
    "h3": "title_3",
    "三级标题": "title_3",
    "正文": "body",
    "paragraph": "body",
    "list": "list_item",
    "bullet": "list_item",
    "列表": "list_item",
    "列表项": "list_item",
    "caption": "figure_caption",
    "图注": "figure_caption",
    "表注": "table_caption",
    "摘要": "abstract",
    "关键词": "keyword",
    "关键字": "keyword",
    "参考文献": "reference",
    "页脚": "footer",
    "other": "unknown",
    "unk": "unknown",
    "未知": "unknown",
}
_WHITESPACE_DASH_PATTERN = re.compile(r"[\s\-]+")


class LLMCallError(Exception):
    """LLM 调用失败时抛出的自定义异常"""
    pass


class LLMClient:
    """
    大模型 API 客户端，封装调用逻辑、超时控制与异常处理。
    兼容 OpenAI 接口规范，支持通过 LLM_BASE_URL 切换到国产模型端点。
    """

    def __init__(self):
        # API Key 不能为空（llm/hybrid 模式下必须设置 LLM_API_KEY）
        if not LLM_API_KEY:
            raise LLMCallError(
                "LLM_API_KEY 未设置。请通过环境变量 LLM_API_KEY 提供大模型 API 密钥。"
            )
        # 初始化 OpenAI 客户端，支持自定义 base_url 和超时
        self.client = openai.OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=LLM_TIMEOUT_S,
        )

    def call_raw(self, paragraphs: List[str]) -> str:
        """
        调用大模型，返回原始 JSON 字符串。

        :param paragraphs: 文档段落文本列表
        :return: 模型输出的原始 JSON 字符串
        :raises LLMCallError: 调用失败时抛出
        """
        try:
            user_prompt = build_user_prompt(paragraphs)
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                # 要求模型以 JSON 格式输出
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content
        except Exception as e:
            raise LLMCallError(f"LLM 调用失败: {e}") from e

    def call_structured(self, paragraphs: List[str]) -> DocumentStructure:
        """
        调用大模型并解析为 DocumentStructure 对象。

        :param paragraphs: 文档段落文本列表
        :return: DocumentStructure 实例
        :raises LLMCallError: 调用失败或解析失败时抛出
        """
        try:
            raw = self.call_raw(paragraphs)
            data = json.loads(self._normalize_json_text(raw))
            data = self._canonicalize_structure_payload(data)
            return DocumentStructure(**data)
        except LLMCallError:
            raise
        except Exception as e:
            raise LLMCallError(f"LLM 响应解析失败: {e}") from e

    @staticmethod
    def _normalize_json_text(raw: str) -> str:
        """兼容不同模型端点可能返回的 Markdown 代码块包装。"""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    @staticmethod
    def _normalize_paragraph_type(raw_type: str) -> str:
        """标准化段落类型：直接命中 -> 别名字典 -> 去下划线后二次别名 -> unknown。"""
        if not isinstance(raw_type, str):
            return "unknown"
        text = raw_type.strip().lower()
        normalized = _WHITESPACE_DASH_PATTERN.sub("_", text)
        if normalized in ALLOWED_PARAGRAPH_TYPES:
            return normalized
        collapsed = normalized.replace("_", "")
        return (
            PARAGRAPH_TYPE_ALIASES.get(normalized)
            or PARAGRAPH_TYPE_ALIASES.get(collapsed)
            or "unknown"
        )

    @classmethod
    def _canonicalize_structure_payload(cls, data: Any) -> Any:
        """规范化 LLM payload 的 paragraph_type，并在缺失时补 total_paragraphs。"""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        paragraphs = payload.get("paragraphs")
        if isinstance(paragraphs, list):
            normalized_paragraphs = []
            for item in paragraphs:
                if not isinstance(item, dict):
                    normalized_paragraphs.append(item)
                    continue
                p = dict(item)
                p["paragraph_type"] = cls._normalize_paragraph_type(p.get("paragraph_type"))
                normalized_paragraphs.append(p)
            payload["paragraphs"] = normalized_paragraphs
            payload.setdefault("total_paragraphs", len(normalized_paragraphs))
        return payload
