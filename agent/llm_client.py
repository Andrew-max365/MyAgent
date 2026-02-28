# agent/llm_client.py
# LLM 接入与调用封装：使用 openai SDK，支持 OpenAI 兼容接口
from __future__ import annotations

import json
from typing import Optional

import config
from agent.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from agent.schema import DocumentStructure


class LLMCallError(Exception):
    """LLM 调用失败时抛出的自定义异常"""


class LLMClient:
    """
    封装对大模型 API 的调用。
    - 支持通过 LLM_BASE_URL 切换 API 端点（国产兼容模型同样适用）
    - 超时控制（LLM_TIMEOUT_S）
    - 统一异常处理，失败时抛出 LLMCallError
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        # 优先使用构造函数参数，否则从 config 读取
        self.api_key = api_key or config.LLM_API_KEY
        self.base_url = base_url or config.LLM_BASE_URL
        self.model = model or config.LLM_MODEL
        self.timeout = timeout if timeout is not None else config.LLM_TIMEOUT_S

    def _get_openai_client(self):
        """惰性创建 openai 客户端，避免模块导入时要求 API Key 存在。"""
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMCallError("openai 包未安装，请执行 pip install openai>=1.0.0") from e

        if not self.api_key:
            raise LLMCallError("LLM_API_KEY 未设置，无法调用大模型 API")

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=float(self.timeout),
        )

    def call_raw(self, paragraphs: list[str]) -> str:
        """
        调用 LLM，返回原始 JSON 字符串。

        :param paragraphs: 文档段落文本列表
        :return: LLM 返回的原始字符串内容
        :raises LLMCallError: 调用失败时抛出
        """
        client = self._get_openai_client()
        user_prompt = build_user_prompt(paragraphs)

        try:
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as e:
            raise LLMCallError(f"LLM API 调用失败: {e}") from e

        content = response.choices[0].message.content or ""
        return content

    def call_structured(self, paragraphs: list[str]) -> DocumentStructure:
        """
        调用 LLM 并将结果解析为 DocumentStructure 对象。

        :param paragraphs: 文档段落文本列表
        :return: 解析后的 DocumentStructure 实例
        :raises LLMCallError: 调用失败或解析失败时抛出
        """
        raw = self.call_raw(paragraphs)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMCallError(f"LLM 返回内容无法解析为 JSON: {raw[:300]}") from e

        try:
            return DocumentStructure.model_validate(data)
        except Exception as e:
            raise LLMCallError(f"LLM 返回 JSON 不符合 DocumentStructure Schema: {e}") from e
