# agent/llm_client.py
# 封装对大模型 API 的调用（使用 openai SDK）
from __future__ import annotations

import json
from typing import List

import openai

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_S
from agent.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from agent.schema import DocumentStructure


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
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text
