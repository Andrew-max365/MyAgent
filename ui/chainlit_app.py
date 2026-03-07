# ui/chainlit_app.py
"""
Chainlit 前端入口 — MyAgent ReAct 文档格式化（增强版）。

功能：
  1. 点击按钮选择排版模式（无需手动输入命令）。
  2. 直接上传 .docx 文件即可处理，无需同时输入文字。
  3. Diff 视图：直接在页面中渲染修改前后对比（GFM ~~删除线~~ → 建议，含段落上下文）。
  4. 通用聊天：不上传文件时，支持直接与 LLM 对话（流式输出）。

启动方式：
    chainlit run ui/chainlit_app.py
"""
from __future__ import annotations

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import asyncio
import copy
import json
import tempfile
from typing import Any, Dict, List, Set

try:
    import chainlit as cl
except ImportError as e:
    raise ImportError("chainlit 未安装，请运行: pip install chainlit") from e

from config import LLM_MODE, REACT_MAX_ITERS, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from service.format_service import format_docx_bytes
from ui.diff_utils import (
    build_diff_items,
    parse_rejected_numbers,
    apply_and_save_proofread,
    generate_structural_diff,
    _ACCEPT_ALL_PATTERNS,
    DiffItem,
)

LABEL_MODES = ["hybrid", "react"]

# Session state keys
_KEY_LABEL_MODE = "label_mode"
_KEY_USE_REACT = "use_react"
_KEY_MAX_ITERS = "max_iters"
_KEY_STATE = "ui_state"        # "ready" | "awaiting_feedback"
_KEY_INPUT_BYTES = "input_bytes"
_KEY_OUTPUT_BYTES = "output_bytes"
_KEY_FILENAME = "filename"
_KEY_ISSUES = "pending_issues"
_KEY_DIFF_ITEMS = "diff_items"
_KEY_REPORT = "pending_report"
_KEY_CHAT_HISTORY = "chat_history"
_KEY_SPEC_OVERRIDES = "spec_overrides"

# Maximum number of chat messages (user+assistant turns) to keep in session context.
_MAX_CHAT_HISTORY = 20


def _deep_merge_dicts(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个配置字典，update 中的叶子值覆盖 base，不整层替换。委托给 core.spec._deep_merge。"""
    from core.spec import _deep_merge
    return _deep_merge(base, update)


def _make_mode_actions() -> List[cl.Action]:
    """Return the two mode-selection action buttons."""
    return [
        cl.Action(name="mode_hybrid", payload={"mode": "hybrid"}, label="⚡ Hybrid（推荐）",
                  tooltip="规则 + LLM 混合，兼顾速度与质量"),
        cl.Action(name="mode_react",  payload={"mode": "react"},  label="🔁 ReAct 模式",
                  tooltip="多轮迭代，适合复杂文档"),
    ]


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set(_KEY_LABEL_MODE, LLM_MODE)
    cl.user_session.set(_KEY_USE_REACT, False)
    cl.user_session.set(_KEY_MAX_ITERS, REACT_MAX_ITERS)
    cl.user_session.set(_KEY_STATE, "ready")
    cl.user_session.set(_KEY_CHAT_HISTORY, [])
    cl.user_session.set(_KEY_SPEC_OVERRIDES, {})

    await cl.Message(
        content=(
            "👋 欢迎使用 **Sturctra 文档排版智能体**！\n\n"
            f"当前模式：**{LLM_MODE}**。点击下方按钮切换模式，然后直接上传 `.docx` 文件即可开始排版。\n\n"
            "💬 也可以直接发送消息与我对话。"
        ),
        actions=_make_mode_actions(),
    ).send()

"""   #引入 Slash 命令（/f 或 /format） 来实现物理隔离
@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set(_KEY_LABEL_MODE, LLM_MODE)
    cl.user_session.set(_KEY_USE_REACT, False)
    cl.user_session.set(_KEY_MAX_ITERS, REACT_MAX_ITERS)
    cl.user_session.set(_KEY_STATE, "ready")
    cl.user_session.set(_KEY_CHAT_HISTORY, [])
    cl.user_session.set(_KEY_SPEC_OVERRIDES, {})

    await cl.Message(
        content=(
            "👋 欢迎使用 **Sturctra 文档排版智能体**！\n\n"
            f"当前模式：**{LLM_MODE}**。点击下方按钮切换模式，直接上传 `.docx` 文件即可开始排版。\n\n"
            "💬 **自由交谈**：直接发送消息与我对话。\n"
            "🎨 **修改排版**：请使用 `/f` 或 `/format` 开头。例如：\n"
            "> `/f 把大标题改成红色，正文字号改成 14`"
        ),
        actions=_make_mode_actions(),
    ).send()
"""




# ── Mode action callbacks ────────────────────────────────────────────────────

async def _set_mode(value: str, action: cl.Action) -> None:
    if value == "react":
        cl.user_session.set(_KEY_LABEL_MODE, "rule")
        cl.user_session.set(_KEY_USE_REACT, True)
    else:
        cl.user_session.set(_KEY_LABEL_MODE, value)
        cl.user_session.set(_KEY_USE_REACT, False)
    await cl.Message(
        content=f"✅ 已切换到 **{value}** 模式。请直接上传 `.docx` 文件开始排版。",
        actions=_make_mode_actions(),
    ).send()
    await action.remove()


@cl.action_callback("mode_hybrid")
async def on_mode_hybrid(action: cl.Action):
    await _set_mode(action.payload.get("mode", "hybrid"), action)


@cl.action_callback("mode_react")
async def on_mode_react(action: cl.Action):
    await _set_mode(action.payload.get("mode", "react"), action)

# @cl.action_callback("diff_action")    #当用户点击了 '全部接受' 或 '全部拒绝' 按钮
# async def on_diff_action(action: cl.Action):
#     await action.remove()  # 点完就让按钮消失，防止重复点击
#     intent = action.value  # "accept_all" 或 "reject_all"
#     await _execute_feedback(intent, [])

@cl.action_callback("accept_all_action")
async def on_accept_all(action: cl.Action):
    await action.remove()  # 点完就让按钮消失
    await _execute_feedback("accept_all", [])

@cl.action_callback("reject_all_action")
async def on_reject_all(action: cl.Action):
    await action.remove()  # 点完就让按钮消失
    await _execute_feedback("reject_all", [])


@cl.on_message
async def on_message(message: cl.Message):
    state = cl.user_session.get(_KEY_STATE, "ready")

    # Allow uploading a new file even while awaiting feedback (starts fresh)
    docx_file = None
    for f in (message.elements or []):
        if hasattr(f, "name") and f.name.lower().endswith(".docx"):
            docx_file = f
            break

    if state == "awaiting_feedback" and docx_file is None:
        await _handle_feedback(message)
        return

    text = message.content.strip()

    # ── Mode selection via text (kept for backwards compatibility) ───────────
    if text.lower() in LABEL_MODES:
        if text.lower() == "react":
            cl.user_session.set(_KEY_LABEL_MODE, "rule")
            cl.user_session.set(_KEY_USE_REACT, True)
        else:
            cl.user_session.set(_KEY_LABEL_MODE, text.lower())
            cl.user_session.set(_KEY_USE_REACT, False)
        await cl.Message(
            content=f"✅ 已切换到 **{text.lower()}** 模式，请上传 .docx 文件。",
            actions=_make_mode_actions(),
        ).send()
        return

    # ── File upload (text is optional) ──────────────────────────────────────
    if docx_file is not None:
        label_mode = cl.user_session.get(_KEY_LABEL_MODE, LLM_MODE)
        use_react = cl.user_session.get(_KEY_USE_REACT, False)
        max_iters = cl.user_session.get(_KEY_MAX_ITERS, REACT_MAX_ITERS)
        overrides = cl.user_session.get(_KEY_SPEC_OVERRIDES, {})

        with open(docx_file.path, "rb") as fp:
            input_bytes = fp.read()

        cl.user_session.set(_KEY_INPUT_BYTES, input_bytes)
        cl.user_session.set(_KEY_FILENAME, docx_file.name)

        await _process_file(input_bytes, docx_file.name, label_mode, use_react, max_iters,
                            overrides=overrides if overrides else None)
        return

    # ── General chat fallback ────────────────────────────────────────────────
    if text:
        await _handle_chat(text)
    else:
        await cl.Message(
            content="💡 请上传 `.docx` 文件开始排版，或直接发送消息与我对话。",
            actions=_make_mode_actions(),
        ).send()


# ── Core processing ────────────────────────────────────────────────────────

async def _process_file(
    input_bytes: bytes,
    filename: str,
    label_mode: str,
    use_react: bool,
    max_iters: int,
    overrides: dict = None,
) -> None:
    """Run the formatting pipeline and display results."""

    mode_display = "react" if use_react else label_mode
    # 显示带旋转沙漏的"正在处理"提示（Task 1 fix）
    processing_msg = cl.Message(content=f"⏳ 正在处理文档（模式: **{mode_display}**）… ⌛")
    await processing_msg.send()

    try:
        if use_react:
            out_bytes, report = await _run_react_with_steps(
                input_bytes, filename, max_iters, overrides=overrides
            )
        else:
            out_bytes, report = await asyncio.to_thread(
                format_docx_bytes,
                input_bytes,
                filename_hint=filename,
                label_mode=label_mode,
                overrides=overrides,
            )
    except Exception as e:
        processing_msg.content = f"❌ 处理失败：{e}"
        await processing_msg.update()
        return

    # 更新提示为"处理完成"
    processing_msg.content = f"✅ 处理完成（模式: **{mode_display}**）"
    await processing_msg.update()

    # ── Store formatted doc (structural changes only, no text replacements yet)
    cl.user_session.set(_KEY_OUTPUT_BYTES, out_bytes)
    cl.user_session.set(_KEY_REPORT, report)

    # ── Structural diff summary ──────────────────────────────────────────────
    struct_diff = generate_structural_diff(report)
    if struct_diff:
        await cl.Message(
            content=f"### 📐 格式化变更摘要\n\n{struct_diff}"
        ).send()

    # ── LLM proofread diff cards ─────────────────────────────────────────────
    raw_issues: list = report.get("llm_proofread", {}).get("issues", [])
    diff_items = build_diff_items(raw_issues)
    cl.user_session.set(_KEY_ISSUES, raw_issues)
    cl.user_session.set(_KEY_DIFF_ITEMS, diff_items)

    if diff_items:
        await _show_diff_cards(diff_items)
        cl.user_session.set(_KEY_STATE, "awaiting_feedback")

    else:
        await _provide_download(out_bytes, report, filename, applied=0)


async def _run_react_with_steps(
    input_bytes: bytes,
    filename: str,
    max_iters: int,
    overrides: dict = None,
) -> tuple:
    """Run the ReAct agent and display each iteration as cl.Steps."""
    tmp_in = tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(input_bytes)
            tmp_in = f.name
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            tmp_out = f.name

        from agent.graph.workflow import run_react_agent

        async with cl.Step(name="ReAct 初始化", type="tool") as step:
            step.input = f"文件: {filename}，最大迭代: {max_iters}"
            result_state = await asyncio.to_thread(
                run_react_agent,
                tmp_in, tmp_out, label_mode="rule", max_iters=max_iters,
                overrides=overrides,
            )
            step.output = f"共 {result_state.get('current_iter', 0)} 轮迭代完成"

        # Show each iteration
        thoughts = result_state.get("thoughts", [])
        observations = result_state.get("observations", [])
        import itertools
        _sentinel = object()
        for idx, (thought, obs) in enumerate(
            itertools.zip_longest(thoughts, observations, fillvalue=None), start=1
        ):
            if thought is None:
                thought = "(无 Thought 记录)"
            if obs is None:
                obs = {}
            async with cl.Step(name=f"迭代 {idx}", type="run") as step:
                step.input = f"**Thought**: {thought}"
                passed = obs.get("passed", False)
                errors = obs.get("errors", [])
                status = "✅ 通过" if passed else f"❌ 失败 ({len(errors)} 错误)"
                details = "\n".join(f"  - {e}" for e in errors) if errors else "  无错误"
                step.output = f"**Observation**: {status}\n{details}"

        with open(tmp_out, "rb") as f:
            out_bytes = f.read()
        report = result_state.get("report", {})
        return out_bytes, report

    except Exception as e:
        await cl.Message(
            content=f"⚠️ ReAct 模式失败，已回退到 rule 模式: {e}"
        ).send()
        out_bytes, report = await asyncio.to_thread(
            format_docx_bytes,
            input_bytes, filename_hint=filename, label_mode="rule",
            overrides=overrides,
        )
        return out_bytes, report

    finally:
        for p in (tmp_in, tmp_out):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


async def _show_diff_cards(diff_items: List[DiffItem]) -> None:
    """Display diff items as plain markdown with action buttons at the bottom."""
    lines = [f"### 🔍 LLM 校对建议（共 {len(diff_items)} 条）\n"]
    for item in diff_items:
        lines.append(item.to_markdown())
        lines.append("")  # blank line between items

    lines.append("---\n🤔 **请点击下方按钮快捷操作，或者直接打字告诉我您的决定：**")

    # 核心修改：将按钮直接挂载在输出建议的这条消息上！
    await cl.Message(
        content="\n".join(lines),
        actions=[
            # 💡 补充 value="accept"，防止前端渲染失败
            cl.Action(name="accept_all_action", payload={"action": "accept"}, label="✅ 全部接受"),
            cl.Action(name="reject_all_action", payload={"action": "reject"}, label="❌ 全部拒绝"),
        ]
    ).send()


async def _execute_feedback(intent: str, rejected: List[int]) -> None:
    """执行校对反馈操作并输出文档"""
    cl.user_session.set(_KEY_STATE, "ready")  # 恢复状态

    diff_items = cl.user_session.get(_KEY_DIFF_ITEMS, [])
    raw_issues = cl.user_session.get(_KEY_ISSUES, [])
    out_bytes = cl.user_session.get(_KEY_OUTPUT_BYTES, b"")
    report = cl.user_session.get(_KEY_REPORT, {})
    filename = cl.user_session.get(_KEY_FILENAME, "output.docx")
    total = len(diff_items)

    if intent == "reject_all":
        await cl.Message(content="⏭️ 已跳过所有校对建议，正在生成最终文档…").send()
        await _provide_download(out_bytes, report, filename, applied=0)
        return

    if rejected:
        kept = total - len(rejected)
        await cl.Message(
            content=f"⏳ 已拒绝 **#{', #'.join(str(n) for n in sorted(rejected))}**，"
                    f"正在应用其余 **{kept}** 条建议…"
        ).send()
    else:
        await cl.Message(content=f"⏳ 正在应用全部 **{total}** 条校对建议…").send()

    try:
        from ui.diff_utils import apply_and_save_proofread
        final_bytes, applied = apply_and_save_proofread(
            out_bytes, raw_issues, excluded_numbers=rejected
        )
    except Exception as e:
        await cl.Message(content=f"⚠️ 应用校对建议出错: {e}").send()
        final_bytes, applied = out_bytes, 0

    await _provide_download(final_bytes, report, filename, applied=applied)


# ── General chat ────────────────────────────────────────────────────────────
'''  # 物理隔离版本的配套代码
async def _handle_chat(text: str) -> None:
    """处理用户输入：隔离 Slash 命令与普通聊天"""
    if not LLM_API_KEY:
        await cl.Message(
            content="💬 未配置 LLM API Key，暂无法进行对话或解析指令。",
            actions=_make_mode_actions(),
        ).send()
        return

    text_strip = text.strip()
    is_format_cmd = text_strip.startswith("/f ") or text_strip.startswith("/format ") or text_strip == "/f" or text_strip == "/format"

    # ════════════════════════════════════════════════════════════════════════
    # 分支 A：用户明确下达排版指令 (Slash Command)
    # ════════════════════════════════════════════════════════════════════════
    if is_format_cmd:
        # 提取真实的指令内容
        cmd_content = text_strip.replace("/format", "").replace("/f", "").strip()
        
        if not cmd_content:
            await cl.Message(content="⚠️ 请在命令后输入具体要求，例如：`/f 所有标题居中`").send()
            return
            
        thinking_msg = cl.Message(content="⏳ 正在将您的指令翻译为排版配置...")
        await thinking_msg.send()

        try:
            from agent.intent_parser import parse_formatting_intent
            formatting_intent = await parse_formatting_intent(cmd_content)
        except Exception as e:
            formatting_intent = None
            print(f"解析报错: {e}")

        if formatting_intent:
            current_overrides: Dict[str, Any] = cl.user_session.get(_KEY_SPEC_OVERRIDES, {})
            new_overrides = _deep_merge_dicts(copy.deepcopy(current_overrides), formatting_intent)
            cl.user_session.set(_KEY_SPEC_OVERRIDES, new_overrides)

            pretty_intent = json.dumps(formatting_intent, ensure_ascii=False, indent=2)
            pretty_overrides = json.dumps(new_overrides, ensure_ascii=False, indent=2)

            input_bytes: bytes = cl.user_session.get(_KEY_INPUT_BYTES)
            if input_bytes:
                thinking_msg.content = (
                    f"✅ **指令已确认！**\n\n"
                    f"**增量修改：**\n```json\n{pretty_intent}\n```\n"
                    f"🚀 正在为您**重新生成文档**..."
                )
                await thinking_msg.update()

                filename: str = cl.user_session.get(_KEY_FILENAME, "document.docx")
                label_mode = cl.user_session.get(_KEY_LABEL_MODE, LLM_MODE)
                use_react = cl.user_session.get(_KEY_USE_REACT, False)
                max_iters = cl.user_session.get(_KEY_MAX_ITERS, REACT_MAX_ITERS)
                
                await _process_file(
                    input_bytes, filename, label_mode, use_react, max_iters,
                    overrides=new_overrides,
                )
            else:
                thinking_msg.content = (
                    f"✅ **已记录您的排版偏好！** 下次上传文档时将自动应用。\n\n"
                    f"**当前完整配置：**\n```json\n{pretty_overrides}\n```\n"
                    f"💡 请直接上传 `.docx` 文件。"
                )
                await thinking_msg.update()
        else:
            thinking_msg.content = "❌ 抱歉，未能从您的指令中提取出有效的排版属性，请换种说法重试。"
            await thinking_msg.update()
            
        return

    # ════════════════════════════════════════════════════════════════════════
    # 分支 B：普通自由交谈 (无需解析意图，速度极快)
    # ════════════════════════════════════════════════════════════════════════
    import openai as _openai
    history: List[dict] = cl.user_session.get(_KEY_CHAT_HISTORY, [])
    history.append({"role": "user", "content": text})

    try:
        client = _openai.AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        msg = cl.Message(content="")
        await msg.send()
        reply_parts: List[str] = []
        
        async with await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 MyAgent 文档格式化助手。"
                        "你可以帮助用户了解文档格式化知识、解答关于本工具的使用问题，也可以进行一般性的中文对话。"
                        "如果用户在聊天中提出了排版要求，请提醒他使用 '/f + 需求' 的命令格式。" # 顺便让大模型也知道这个规则
                    ),
                },
                *history[-_MAX_CHAT_HISTORY:],
            ],
            stream=True,
        ) as stream:
            async for chunk in stream:
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    reply_parts.append(token)
                    await msg.stream_token(token)
        await msg.update()
        
        reply = "".join(reply_parts)
        history.append({"role": "assistant", "content": reply})
        cl.user_session.set(_KEY_CHAT_HISTORY, history)
    except Exception as e:
        await cl.Message(content=f"💬 对话失败：{e}").send()
'''
async def _handle_chat(text: str) -> None:
    """全自动路由：自动判断是聊天还是排版指令，且提供丝滑加载提示"""
    if not LLM_API_KEY:
        await cl.Message(
            content="💬 未配置 LLM API Key，暂无法进行对话或解析指令。",
            actions=_make_mode_actions(),
        ).send()
        return

    # 1. 极致体验：先发一个过渡提示，防止前端“假死”
    thinking_msg = cl.Message(content="⏳ 正在理解您的意图...")
    await thinking_msg.send()

    # 2. 智能路由：交给底层的意图解析器去“猜”
    try:
        from agent.intent_parser import parse_formatting_intent
        # 它会在后台悄悄问大模型：这句话是排版吗？如果不是，大模型会返回 {}
        formatting_intent = await parse_formatting_intent(text)
    except Exception as e:
        formatting_intent = None
        print(f"意图解析异常: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # 分支 A：大模型判定为排版指令 (成功提取到了属性)
    # ════════════════════════════════════════════════════════════════════════
    if formatting_intent:
        current_overrides: Dict[str, Any] = cl.user_session.get(_KEY_SPEC_OVERRIDES, {})
        new_overrides = _deep_merge_dicts(copy.deepcopy(current_overrides), formatting_intent)
        cl.user_session.set(_KEY_SPEC_OVERRIDES, new_overrides)

        pretty_intent = json.dumps(formatting_intent, ensure_ascii=False, indent=2)
        pretty_overrides = json.dumps(new_overrides, ensure_ascii=False, indent=2)

        input_bytes: bytes = cl.user_session.get(_KEY_INPUT_BYTES)
        if input_bytes:
            # 更新过渡提示为：准备重排文档
            thinking_msg.content = (
                f"✅ **指令已确认！**\n\n"
                f"**本次修改：**\n```json\n{pretty_intent}\n```\n"
                f"🚀 正在为您**重新生成文档**..."
            )
            await thinking_msg.update()

            filename: str = cl.user_session.get(_KEY_FILENAME, "document.docx")
            label_mode = cl.user_session.get(_KEY_LABEL_MODE, LLM_MODE)
            use_react = cl.user_session.get(_KEY_USE_REACT, False)
            max_iters = cl.user_session.get(_KEY_MAX_ITERS, REACT_MAX_ITERS)

            await _process_file(
                input_bytes, filename, label_mode, use_react, max_iters,
                overrides=new_overrides,
            )
        else:
            thinking_msg.content = (
                f"✅ **已记录您的排版偏好！** 下次上传文档时将自动应用。\n\n"
                f"**当前完整配置：**\n```json\n{pretty_overrides}\n```\n"
                f"💡 请直接上传 `.docx` 文件。"
            )
            await thinking_msg.update()

        return

    # ════════════════════════════════════════════════════════════════════════
    # 分支 B：大模型判定为普通聊天 (返回了空字典或解析失败)
    # ════════════════════════════════════════════════════════════════════════
    # 撤回刚才的“思考中”提示
    await thinking_msg.remove()

    import openai as _openai
    history: List[dict] = cl.user_session.get(_KEY_CHAT_HISTORY, [])
    history.append({"role": "user", "content": text})

    try:
        client = _openai.AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=30.0)
        msg = cl.Message(content="")
        await msg.send()
        reply_parts: List[str] = []

        async with await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                                "你是 MyAgent 文档格式化助手。"
                                "你可以帮助用户了解文档格式化知识、解答关于本工具的使用问题，也可以进行一般性的中文对话。"
                        ),
                    },
                    *history[-_MAX_CHAT_HISTORY:],
                ],
                stream=True,
        ) as stream:
            async for chunk in stream:
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    reply_parts.append(token)
                    await msg.stream_token(token)
        await msg.update()

        reply = "".join(reply_parts)
        history.append({"role": "assistant", "content": reply})
        cl.user_session.set(_KEY_CHAT_HISTORY, history)
    except Exception as e:
        await cl.Message(content=f"💬 对话失败：{e}").send()


# ── User feedback handling ─────────────────────────────────────────────────

async def _handle_feedback(message: cl.Message) -> None:
    """Handle user's natural language response for the pending diff items."""
    text = message.content.strip()
    diff_items: List[DiffItem] = cl.user_session.get(_KEY_DIFF_ITEMS, [])
    total = len(diff_items)

    # 显示过渡动画
    thinking_msg = cl.Message(content="⏳ 正在理解您的处理决定...")
    await thinking_msg.send()

    # 🚀 召唤大模型解析意图！
    from agent.intent_parser import parse_feedback_intent
    result = await parse_feedback_intent(text, total)
    await thinking_msg.remove()

    intent = result.get("intent", "unknown")
    rejected = result.get("rejected_indices", [])

    if intent == "unknown":
        await cl.Message(
            content="❓ 没太听懂您的意思，请明确说明您想保留或拒绝哪些建议，或者直接点击上方的按钮哦。"
        ).send()
        return

    # 交给执行引擎
    await _execute_feedback(intent, rejected)

# ── Download helper ────────────────────────────────────────────────────────

async def _provide_download(
    out_bytes: bytes,
    report: dict,
    filename: str,
    *,
    applied: int,
) -> None:
    """Send download links for the output docx and report JSON."""
    meta = report.get("meta", {})
    para_before = meta.get("paragraphs_before", "?")
    para_after = meta.get("paragraphs_after", "?")

    summary_lines = [
        "✅ **处理完成！**",
        "",
        f"📊 段落数：{para_before} → {para_after}",
    ]
    if applied:
        summary_lines.append(f"✏️ 文本校对应用：{applied} 处")

    warnings_list = report.get("warnings", [])
    if warnings_list:
        summary_lines.append(f"⚠️ 警告：{len(warnings_list)} 条")

    await cl.Message(content="\n".join(summary_lines)).send()

    base_name = os.path.splitext(os.path.basename(filename))[0]
    output_el = cl.File(
        name=f"{base_name}_formatted.docx",
        content=out_bytes,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    report_el = cl.File(
        name=f"{base_name}_report.json",
        content=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
        mime="application/json",
    )
    await cl.Message(
        content="📥 下载产物：",
        elements=[output_el, report_el],
    ).send()
