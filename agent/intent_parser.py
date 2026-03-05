# agent/intent_parser.py
"""
意图解析器：将用户自然语言中的排版需求转换为结构化配置字典。
例："把标题改成黑色" → {"heading": {"h1": {"color": "000000"}, "h2": {"color": "000000"}, "h3": {"color": "000000"}}}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_INTENT_PARSE_TIMEOUT = 15.0   # 意图解析 API 超时（秒）
_INTENT_PARSE_MAX_TOKENS = 300  # 意图解析最大输出 token 数

_FORMATTING_SYSTEM_PROMPT = (
    "你是一个高级文档排版配置智能体。你的任务是理解用户的自然语言排版需求（不仅限于颜色，还包括字号、对齐、加粗、字体、行距等），并将其转换为严格的 JSON 配置覆盖字典。\n\n"
    "【支持的配置结构与字段说明】（仅输出用户明确提及需要修改的字段，不要输出多余层级）：\n"
    "{\n"
    '  "fonts": {\n'
    '    "zh": "宋体",                 // 中文字体\n'
    '    "en": "Times New Roman"       // 英文字体\n'
    '  },\n'
    '  "body": {\n'
    '    "color": "000000",          // 十六进制颜色（不含#号）\n'
    '    "font_size_pt": 12.0,       // 字号(磅)。常用换算：小四=12.0，四号=14.0，小三=15.0，三号=16.0，五号=10.5\n'
    '    "line_spacing": 1.5,        // 行间距（倍数）\n'
    '    "first_line_chars": 2,      // 首行缩进（字符数）\n'
    '    "alignment": "justify"      // 对齐方式：left(左对齐), center(居中), right(右对齐), justify(两端对齐)\n'
    '  },\n'
    '  "heading": {\n'
    '    "h1": {\n'
    '      "color": "000000", "font_size_pt": 16.0, "bold": true, "alignment": "center"\n'
    '    },\n'
    '    "h2": { /* 结构与h1相同 */ },\n'
    '    "h3": { /* 结构与h1相同 */ }\n'
    '  }\n'
    "}\n\n"
    "【智能解析规则】\n"
    "1. 语义泛化：如果用户说“大标题”、“一级标题”，对应修改 h1；“二级标题”、“副标题”对应 h2；如果说“所有标题”、“标题”，则必须同时填充 h1, h2, h3。\n"
    "2. 范围推断：如果用户说“全文”、“通篇”、“全部”改成某种颜色或字体，你需要同时输出 fonts、body 以及 heading 下所有层级的修改。\n"
    "3. 模糊意图：如果用户说“字太小了”，你可以适度将正文字号上调（如推测修改为 14.0 或 15.0）。\n"
    "4. 严格输出：如果没有涉及排版需求，输出 {}。严格输出纯 JSON，绝对不能包含任何 Markdown 标记（如 ```json）或额外的说明文字。\n"
)


async def parse_formatting_intent(user_text: str) -> Optional[Dict[str, Any]]:
    if not LLM_API_KEY:
        return None

    try:
        import openai as _openai

        client = _openai.AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=_INTENT_PARSE_TIMEOUT,
        )

        # ✅ 新增：请求前打印日志
        print(f"\n👉 [Debug] 正在请求大模型解析排版意图: {user_text}")

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _FORMATTING_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            max_tokens=_INTENT_PARSE_MAX_TOKENS,
            # 注意：这里我们去掉了 response_format，避免某些 API 报错
        )
        raw = response.choices[0].message.content or ""

        # ✅ 新增：打印原始回复，方便你在控制台监控
        print(f"✅ [Debug] 大模型原始回复:\n{raw}")

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            print("❌ [Debug] 未提取到有效的 JSON 配置")
            return None

        data = json.loads(match.group(0))
        if not isinstance(data, dict) or not data:
            print("⚠️ [Debug] 提取的 JSON 为空或非字典（非排版指令）")
            return None

        return data

    except Exception as e:
        # ✅ 打印出真正的错误，不再静默失败
        print(f"❌ [Debug] 意图解析器发生错误: {e}")
        return None


_FEEDBACK_SYSTEM_PROMPT = (
    "你是一个校对建议决策解析器。当前共有 {total} 条校对建议。\n"
    "用户的自然语言会指示他们想接受或拒绝哪些建议。\n"
    "你需要将其解析为严格的 JSON，格式如下：\n"
    "{{\n"
    '  "intent": "accept_all" | "reject_all" | "partial",\n'
    '  "rejected_indices": [2, 3] // 被拒绝的序号列表（从1开始计算）。如果是 partial 且只接受某几条，需推算出剩余被拒绝的序号。\n'
    "}}\n\n"
    "举例：\n"
    "用户说：“全要/好的/确认”，返回 {{\"intent\": \"accept_all\", \"rejected_indices\": []}}\n"
    "用户说：“都不要了/滚/全拒绝”，返回 {{\"intent\": \"reject_all\", \"rejected_indices\": [1,2,3...]}}\n"
    "用户说：“除了第二条其他的都同意”，假设共3条，返回 {{\"intent\": \"partial\", \"rejected_indices\": [2]}}\n"
    "用户说：“只要第1条和第3条”，假设共5条，返回 {{\"intent\": \"partial\", \"rejected_indices\": [2,4,5]}}\n"
)


async def parse_feedback_intent(user_text: str, total_items: int) -> dict:
    """把用户的反馈自然语言，解析为操作意图和拒绝序号列表"""
    if not LLM_API_KEY:
        return {"intent": "unknown", "rejected_indices": []}

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=10.0)

        prompt = _FEEDBACK_SYSTEM_PROMPT.format(total=total_items)
        print(f"\n👉 [Debug] 正在请求大模型解析校对反馈: {user_text}")

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"用户反馈: {user_text}"}
            ],
            max_tokens=200,
            temperature=0.1
        )
        raw = response.choices[0].message.content or ""
        print(f"✅ [Debug] 反馈解析结果:\n{raw}")

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))

    except Exception as e:
        print(f"❌ [Debug] 反馈解析报错: {e}")

    return {"intent": "unknown", "rejected_indices": []}