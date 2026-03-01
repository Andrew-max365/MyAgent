# agent/llm_client.py
# 封装对大模型 API 的调用（使用 openai SDK）
from __future__ import annotations

import json
import re
import time
from typing import Any, List

import openai
import pydantic

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT_S,
    LLM_CONNECT_TIMEOUT_S,
    LLM_MAX_TIMEOUT_S,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_BACKOFF_S,
)
from agent.prompt_templates import SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, build_user_prompt, build_review_prompt
from agent.schema import DocumentStructure, DocumentReview, LLMSuggestion

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


def compute_dynamic_timeout(n_paragraphs: int) -> int:
    """
    根据段落数量动态计算读取超时时间（秒）。

    公式：LLM_TIMEOUT_S + n_paragraphs * 0.5，结果限制在 [LLM_TIMEOUT_S, LLM_MAX_TIMEOUT_S]。

    :param n_paragraphs: 送入 LLM 的段落数量
    :return: 建议的读取超时秒数
    """
    dynamic = LLM_TIMEOUT_S + int(n_paragraphs * 0.5)
    return min(dynamic, LLM_MAX_TIMEOUT_S)


class LLMCallError(Exception):
    """LLM 调用失败时抛出的自定义异常"""
    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type  # "timeout" | "read_timeout" | "connect_timeout" | "connect_error" | "auth" | "format_error" | "unknown"


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
        # 使用 openai.Timeout 分别设置连接超时与读取超时，改善连接阶段的诊断能力
        self.client = openai.OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=openai.Timeout(LLM_TIMEOUT_S, connect=LLM_CONNECT_TIMEOUT_S),
        )

    def _execute_chat_completion(self, messages: list, timeout: int | None = None) -> str:
        """
        执行聊天补全调用，支持自动重试（指数退避）与详细超时类型分类。

        :param messages: 消息列表（system + user）
        :param timeout: 读取超时秒数；None 时使用客户端默认值
        :return: 模型输出内容字符串
        :raises LLMCallError: 调用失败时抛出（含 error_type）
        """
        call_timeout = (
            openai.Timeout(timeout, connect=LLM_CONNECT_TIMEOUT_S)
            if timeout is not None
            else None
        )
        last_error: LLMCallError | None = None
        for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
            try:
                kwargs: dict = dict(
                    model=LLM_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                if call_timeout is not None:
                    kwargs["timeout"] = call_timeout
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message.content
            except openai.APITimeoutError as e:
                # 尝试从底层 httpx 异常区分连接超时与读取超时
                cause = getattr(e, "__cause__", None)
                cause_name = type(cause).__name__ if cause is not None else ""
                if "Connect" in cause_name:
                    kind, err_type = "连接超时", "connect_timeout"
                elif "Read" in cause_name:
                    kind, err_type = "读取超时", "read_timeout"
                else:
                    kind, err_type = "请求超时", "timeout"
                last_error = LLMCallError(
                    f"LLM {kind} (尝试 {attempt}/{LLM_RETRY_ATTEMPTS}): {e}",
                    error_type=err_type,
                )
            except openai.APIConnectionError as e:
                last_error = LLMCallError(
                    f"LLM 网络连接失败 (尝试 {attempt}/{LLM_RETRY_ATTEMPTS}): {e}",
                    error_type="connect_error",
                )
            except openai.AuthenticationError as e:
                raise LLMCallError(f"LLM 鉴权失败: {e}", error_type="auth") from e
            except Exception as e:
                raise LLMCallError(f"LLM 调用失败: {e}", error_type="unknown") from e

            if attempt < LLM_RETRY_ATTEMPTS:
                backoff = LLM_RETRY_BACKOFF_S * (2 ** (attempt - 1))
                time.sleep(backoff)

        raise last_error  # type: ignore[misc]

    def call_raw(self, paragraphs: List[str]) -> str:
        """
        调用大模型，返回原始 JSON 字符串。

        :param paragraphs: 文档段落文本列表
        :return: 模型输出的原始 JSON 字符串
        :raises LLMCallError: 调用失败时抛出
        """
        user_prompt = build_user_prompt(paragraphs)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return self._execute_chat_completion(
            messages, timeout=compute_dynamic_timeout(len(paragraphs))
        )

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
        except json.JSONDecodeError as e:
            raise LLMCallError(f"LLM 响应 JSON 解析失败: {e}", error_type="format_error") from e
        except pydantic.ValidationError as e:
            raise LLMCallError(f"LLM 响应结构校验失败: {e}", error_type="format_error") from e
        except Exception as e:
            raise LLMCallError(f"LLM 响应解析失败: {e}", error_type="unknown") from e

    def call_review(
        self,
        paragraphs: List[str],
        triggered_indices: list | None = None,
        rule_labels: dict | None = None,
    ) -> "DocumentReview":
        """
        调用大模型进行语义审阅，返回 DocumentReview（含结构标签 + 建议列表）。

        :param paragraphs: 文档全部段落文本列表
        :param triggered_indices: 触发审阅的段落索引列表（hybrid 模式）；None 表示全量（llm 模式）
        :param rule_labels: 规则层标签（paragraph_index -> role），供 LLM 参考
        :return: DocumentReview 实例
        :raises LLMCallError: 调用失败或解析失败时抛出
        """
        try:
            user_prompt = build_review_prompt(paragraphs, triggered_indices, rule_labels)
            messages = [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            n = len(triggered_indices) if triggered_indices is not None else len(paragraphs)
            raw = self._execute_chat_completion(
                messages, timeout=compute_dynamic_timeout(n)
            )
            data = json.loads(self._normalize_json_text(raw))
            data = self._canonicalize_review_payload(data)
            return DocumentReview(**data)
        except LLMCallError:
            raise
        except json.JSONDecodeError as e:
            raise LLMCallError(f"LLM 审阅响应 JSON 解析失败: {e}", error_type="format_error") from e
        except pydantic.ValidationError as e:
            raise LLMCallError(f"LLM 审阅响应结构校验失败: {e}", error_type="format_error") from e
        except Exception as e:
            raise LLMCallError(f"LLM 审阅调用失败: {e}", error_type="unknown") from e

    @classmethod
    def _canonicalize_suggestion(cls, item: Any) -> Any:
        """规范化单条建议字段。"""
        if not isinstance(item, dict):
            return item
        s = dict(item)
        # 规范化 category
        valid_categories = {"hierarchy", "ambiguity", "structure", "style", "terminology"}
        if s.get("category") not in valid_categories:
            s["category"] = "ambiguity"
        # 规范化 severity
        valid_severities = {"low", "medium", "high"}
        if s.get("severity") not in valid_severities:
            s["severity"] = "low"
        # 规范化 confidence
        s["confidence"] = cls._normalize_confidence(s.get("confidence"))
        # 规范化 apply_mode
        if s.get("apply_mode") not in ("auto", "manual"):
            s["apply_mode"] = "manual"
        # 填充必要字段
        s.setdefault("evidence", "")
        s.setdefault("suggestion", "")
        s.setdefault("rationale", "")
        return s

    @classmethod
    def _canonicalize_review_payload(cls, data: Any) -> Any:
        """规范化 DocumentReview payload（含 paragraphs + suggestions）。"""
        if not isinstance(data, dict):
            return data
        payload = cls._canonicalize_structure_payload(data)
        suggestions = payload.get("suggestions")
        if isinstance(suggestions, list):
            payload["suggestions"] = [cls._canonicalize_suggestion(s) for s in suggestions]
        else:
            payload["suggestions"] = []
        return payload

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

    @staticmethod
    def _normalize_confidence(raw_confidence: Any) -> float:
        """规范化 confidence 到 [0, 1] 区间，兼容数字、字符串与百分比字符串。"""
        value: float
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
            value = float(raw_confidence)
        elif isinstance(raw_confidence, str):
            text = raw_confidence.strip()
            if not text:
                return 0.0
            is_percent = text.endswith("%")
            if is_percent:
                text = text[:-1].strip()
            try:
                value = float(text)
            except ValueError:
                return 0.0
            if is_percent:
                value /= 100.0
        else:
            return 0.0

        return max(0.0, min(1.0, value))

    @classmethod
    def _canonicalize_structure_payload(cls, data: Any) -> Any:
        """规范化 LLM payload 的字段（paragraph_type/confidence），并在缺失时补 total_paragraphs。"""
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
                raw_type = p.get("paragraph_type", p.get("type", p.get("label")))
                p["paragraph_type"] = cls._normalize_paragraph_type(raw_type)
                if "index" not in p and "paragraph_index" in p:
                    p["index"] = p["paragraph_index"]
                if "text_preview" not in p and isinstance(p.get("text"), str):
                    p["text_preview"] = p["text"]
                p["confidence"] = cls._normalize_confidence(p.get("confidence"))
                normalized_paragraphs.append(p)
            payload["paragraphs"] = normalized_paragraphs
            payload.setdefault("total_paragraphs", len(normalized_paragraphs))
        return payload
