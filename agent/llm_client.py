# agent/llm_client.py
# 封装对大模型 API 的调用（使用 openai SDK）
import json

import openai

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_S
from agent.prompt_templates import SYSTEM_PROMPT
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

    def analyze_document(self, prompt: str) -> DocumentStructure:
        """
        调用大模型分析文档结构，返回结构化的 DocumentStructure 对象。

        :param prompt: 由 build_user_prompt() 构造的用户 Prompt
        :return: DocumentStructure 对象
        :raises LLMCallError: 调用失败或解析失败时抛出
        """
        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                # 要求模型以 JSON 格式输出
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            return DocumentStructure(**data)
        except Exception as e:
            raise LLMCallError(f"LLM call failed: {e}") from e
