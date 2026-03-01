# tests/test_mode_differentiation.py
# 验证 rule / llm / hybrid 三种模式的职责边界与行为差异
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docx import Document

from agent.mode_router import (
    ModeRouter,
    _compute_hybrid_triggers,
    HYBRID_CONFIDENCE_THRESHOLD,
    HYBRID_TRIGGER_UNKNOWN_MIN,
)
from agent.schema import DocumentReview, LLMSuggestion, ParagraphTag
from core.parser import Block


# ---------------------------------------------------------------------------
# 测试辅助：构造 Block 列表
# ---------------------------------------------------------------------------

def _make_block(block_id: int, paragraph_index: int, text: str) -> Block:
    b = MagicMock(spec=Block)
    b.block_id = block_id
    b.paragraph_index = paragraph_index
    b.text = text
    return b


def _make_review(paragraphs_data, suggestions=None) -> DocumentReview:
    """构造 DocumentReview 测试对象。"""
    paras = [ParagraphTag(**p) for p in paragraphs_data]
    suggs = [LLMSuggestion(**s) for s in (suggestions or [])]
    return DocumentReview(
        doc_language="zh",
        total_paragraphs=len(paras),
        paragraphs=paras,
        suggestions=suggs,
    )


# ---------------------------------------------------------------------------
# 1. _compute_hybrid_triggers 触发条件测试
# ---------------------------------------------------------------------------

class TestHybridTriggers:
    def test_no_trigger_when_all_known_roles(self):
        """全部为确定角色时不应触发。"""
        blocks = [
            _make_block(0, 0, "第一章 引言"),
            _make_block(1, 1, "这是正文内容。"),
            _make_block(2, 2, "一、概述"),
        ]
        rule_labels = {0: "h1", 1: "body", 2: "h2"}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        assert result["triggered"] is False
        assert result["reasons"] == []
        assert len(result["triggered_indices"]) == 0

    def test_trigger_on_unknown_label(self):
        """存在 unknown 标签时应触发。"""
        blocks = [
            _make_block(0, 0, "第一章 引言"),
            _make_block(1, 1, "这是不可识别的段落内容，规则无法判断类型。"),
        ]
        rule_labels = {0: "h1", 1: "unknown"}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        assert result["triggered"] is True
        assert 1 in result["triggered_indices"]
        assert any("unknown" in r for r in result["reasons"])

    def test_trigger_on_long_heading(self):
        """超长标题文本（疑似误分类）应触发。"""
        long_text = "一、" + "这是一段超过三十字的所谓标题内容，实际上可能是正文段落" * 2
        blocks = [
            _make_block(0, 0, long_text),
        ]
        rule_labels = {0: "h2"}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        assert result["triggered"] is True
        assert 0 in result["triggered_indices"]
        assert any("标题层级" in r for r in result["reasons"])

    def test_trigger_on_consecutive_short_body(self):
        """连续多个短正文段落（潜在列表）应触发。"""
        blocks = [
            _make_block(i, i, f"条目内容{i}，短文本") for i in range(4)
        ]
        rule_labels = {i: "body" for i in range(4)}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        assert result["triggered"] is True
        assert any("结构化改写" in r for r in result["reasons"])

    def test_no_trigger_when_long_body_paragraphs(self):
        """长正文段落（非短）不应触发连续 body 触发器。"""
        long_text = "这是一段很长的正文内容，超过六十个字符，所以不应该被识别为潜在列表。" * 3
        blocks = [
            _make_block(i, i, long_text) for i in range(4)
        ]
        rule_labels = {i: "body" for i in range(4)}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        # 长段落不满足"短 body"条件
        assert not any("结构化改写" in r for r in result["reasons"])

    def test_metrics_are_populated(self):
        """触发后 metrics 字典应包含各计数。"""
        blocks = [_make_block(0, 0, "X")]
        rule_labels = {0: "unknown"}
        result = _compute_hybrid_triggers(blocks, rule_labels)
        assert "unknown_count" in result["metrics"]
        assert "ambiguous_heading_count" in result["metrics"]
        assert result["metrics"]["unknown_count"] >= HYBRID_TRIGGER_UNKNOWN_MIN


# ---------------------------------------------------------------------------
# 2. rule 模式：从不调用 LLM
# ---------------------------------------------------------------------------

class TestRuleMode:
    def test_rule_mode_does_not_call_llm(self):
        """rule 模式不应创建 DocAnalyzer 或调用 LLM。"""
        router = ModeRouter(mode="rule")
        doc = MagicMock()
        blocks = [_make_block(0, 0, "正文内容")]
        rule_labels = {0: "body"}

        result = router.route(doc, blocks, rule_labels)

        assert result["_source"] == "rule"
        assert result[0] == "body"
        # DocAnalyzer 从未被初始化
        assert router._analyzer is None

    def test_rule_mode_does_not_produce_llm_review(self):
        """rule 模式结果不应含 _llm_review 键。"""
        router = ModeRouter(mode="rule")
        blocks = [_make_block(0, 0, "正文")]
        result = router.route(MagicMock(), blocks, {0: "body"})
        assert "_llm_review" not in result
        assert "_hybrid_triggers" not in result


# ---------------------------------------------------------------------------
# 3. hybrid 模式：无触发时不调用 LLM
# ---------------------------------------------------------------------------

class TestHybridNoTrigger:
    def test_hybrid_skips_llm_when_no_trigger(self):
        """hybrid 模式在无触发时不应调用 LLM。"""
        router = ModeRouter(mode="hybrid")
        doc = MagicMock()
        blocks = [
            _make_block(0, 0, "第一章 引言"),
            _make_block(1, 1, "这是正文内容，描述了本文的主要研究方向和目标。"),
        ]
        rule_labels = {0: "h1", 1: "body"}

        result = router.route(doc, blocks, rule_labels)

        assert result["_source"] == "hybrid"
        assert result["_hybrid_triggers"]["triggered"] is False
        assert result["_hybrid_triggers"]["llm_called"] is False
        # 从未初始化 DocAnalyzer（即从未尝试调用 LLM）
        assert router._analyzer is None
        # 标签来自规则
        assert result[0] == "h1"
        assert result[1] == "body"
        # 无 llm_review
        assert "_llm_review" not in result

    def test_hybrid_preserves_rule_labels_when_no_trigger(self):
        """无触发时 hybrid 结果与 rule 结果完全一致（标签层面）。"""
        rule_router = ModeRouter(mode="rule")
        hybrid_router = ModeRouter(mode="hybrid")
        doc = MagicMock()
        blocks = [
            _make_block(0, 0, "第一章"),
            _make_block(1, 1, "这是一段正文内容，描述详细信息，超过了六十个字符的限制以避免触发连续 body 触发器。"),
            _make_block(2, 2, "第二章"),
        ]
        rule_labels = {0: "h1", 1: "body", 2: "h1"}

        rule_result = rule_router.route(doc, blocks, rule_labels)
        hybrid_result = hybrid_router.route(doc, blocks, rule_labels)

        # 标签相同
        for b in blocks:
            assert rule_result[b.block_id] == hybrid_result[b.block_id], (
                f"block_id={b.block_id}: rule={rule_result[b.block_id]}, "
                f"hybrid={hybrid_result[b.block_id]}"
            )


# ---------------------------------------------------------------------------
# 4. hybrid 模式：触发时调用 LLM（仅触发段落）
# ---------------------------------------------------------------------------

class TestHybridWithTrigger:
    def _make_review_for_triggered(self, triggered_idx: int) -> DocumentReview:
        return _make_review(
            paragraphs_data=[
                {
                    "index": triggered_idx,
                    "text_preview": "触发段落",
                    "paragraph_type": "list_item",
                    "confidence": 0.92,
                }
            ],
            suggestions=[
                {
                    "category": "structure",
                    "severity": "medium",
                    "confidence": 0.85,
                    "evidence": f"段落{triggered_idx}: 短正文段落",
                    "suggestion": "建议改写为列表",
                    "rationale": "多个短段落适合列表化",
                    "apply_mode": "manual",
                    "paragraph_index": triggered_idx,
                }
            ],
        )

    def test_hybrid_calls_llm_when_triggered(self):
        """hybrid 模式在触发时应调用 LLM 并记录 llm_called=True。"""
        blocks = [
            _make_block(i, i, f"条目{i}，短文本") for i in range(4)
        ]
        rule_labels = {i: "body" for i in range(4)}

        mock_review = self._make_review_for_triggered(0)
        router = ModeRouter(mode="hybrid")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["条目0", "条目1", "条目2", "条目3"]):
            result = router.route(MagicMock(), blocks, rule_labels)

        assert result["_hybrid_triggers"]["triggered"] is True
        assert result["_hybrid_triggers"]["llm_called"] is True
        mock_client.call_review.assert_called_once()

    def test_hybrid_llm_review_contains_suggestions(self):
        """hybrid 触发后结果中应包含 _llm_review 及建议。"""
        blocks = [
            _make_block(i, i, f"条目{i}，短文本") for i in range(4)
        ]
        rule_labels = {i: "body" for i in range(4)}

        mock_review = self._make_review_for_triggered(0)
        router = ModeRouter(mode="hybrid")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["条目0", "条目1", "条目2", "条目3"]):
            result = router.route(MagicMock(), blocks, rule_labels)

        assert "_llm_review" in result
        review = result["_llm_review"]
        assert isinstance(review["suggestions"], list)
        assert len(review["suggestions"]) > 0
        # 验证建议字段完整性
        s = review["suggestions"][0]
        assert "category" in s
        assert "severity" in s
        assert "confidence" in s
        assert "evidence" in s
        assert "suggestion" in s
        assert "rationale" in s
        assert "apply_mode" in s

    def test_hybrid_only_reviews_triggered_paragraphs(self):
        """hybrid 模式 call_review 调用时应传入 triggered_indices（非 None）。"""
        blocks = [
            _make_block(0, 0, "第一章"),               # h1 - 不触发
            _make_block(1, 1, "条目一，短文本"),         # body - 触发
            _make_block(2, 2, "条目二，短文本"),         # body - 触发
            _make_block(3, 3, "条目三，短文本"),         # body - 触发
            _make_block(4, 4, "条目四，短文本"),         # body - 触发
        ]
        rule_labels = {0: "h1", 1: "body", 2: "body", 3: "body", 4: "body"}

        mock_review = _make_review(
            paragraphs_data=[
                {"index": i, "text_preview": f"条目{i}", "paragraph_type": "list_item", "confidence": 0.9}
                for i in range(1, 5)
            ]
        )
        router = ModeRouter(mode="hybrid")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["第一章", "条目一", "条目二", "条目三", "条目四"]):
            router.route(MagicMock(), blocks, rule_labels)

        call_kwargs = mock_client.call_review.call_args
        # triggered_indices 应非 None，且不包含 0（h1 未触发）
        if call_kwargs.kwargs.get("triggered_indices") is not None:
            triggered = call_kwargs.kwargs["triggered_indices"]
        elif len(call_kwargs.args) > 1:
            triggered = call_kwargs.args[1]
        else:
            triggered = None
        assert triggered is not None, "call_review 应传入 triggered_indices"
        assert 0 not in triggered, "未触发的段落不应包含在 triggered_indices 中"


# ---------------------------------------------------------------------------
# 5. LLM 模式：全量审阅，always calls LLM
# ---------------------------------------------------------------------------

class TestLLMMode:
    def test_llm_mode_always_calls_llm(self):
        """llm 模式应始终调用 LLM 进行全量审阅。"""
        blocks = [
            _make_block(0, 0, "第一章"),
            _make_block(1, 1, "正文内容"),
        ]
        rule_labels = {0: "h1", 1: "body"}

        mock_review = _make_review(
            paragraphs_data=[
                {"index": 0, "text_preview": "第一章", "paragraph_type": "title_1", "confidence": 0.98},
                {"index": 1, "text_preview": "正文", "paragraph_type": "body", "confidence": 0.95},
            ],
            suggestions=[
                {
                    "category": "style",
                    "severity": "low",
                    "confidence": 0.7,
                    "evidence": "段落1: 正文内容",
                    "suggestion": "建议增加过渡语",
                    "rationale": "增强可读性",
                    "apply_mode": "manual",
                }
            ],
        )
        router = ModeRouter(mode="llm")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["第一章", "正文内容"]):
            result = router.route(MagicMock(), blocks, rule_labels)

        assert result["_source"] == "llm"
        mock_client.call_review.assert_called_once()
        # llm 模式的 call_review 应传 triggered_indices=None（全量审阅）
        call_kwargs = mock_client.call_review.call_args
        triggered = call_kwargs.kwargs.get("triggered_indices")
        assert triggered is None, "llm 模式应全量审阅（triggered_indices=None）"

    def test_llm_mode_produces_llm_review(self):
        """llm 模式应产出 _llm_review 键（含 suggestions）。"""
        blocks = [_make_block(0, 0, "第一章")]
        rule_labels = {0: "h1"}

        mock_review = _make_review(
            paragraphs_data=[
                {"index": 0, "text_preview": "第一章", "paragraph_type": "title_1", "confidence": 0.98},
            ],
            suggestions=[
                {
                    "category": "hierarchy",
                    "severity": "high",
                    "confidence": 0.9,
                    "evidence": "段落0: 第一章",
                    "suggestion": "建议使用一级标题样式",
                    "rationale": "统一标题层级",
                    "apply_mode": "auto",
                }
            ],
        )
        router = ModeRouter(mode="llm")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["第一章"]):
            result = router.route(MagicMock(), blocks, rule_labels)

        assert "_llm_review" in result
        review = result["_llm_review"]
        assert len(review["suggestions"]) == 1
        # manual_pending 应只含 apply_mode=manual 的建议
        assert len(review["manual_pending"]) == 0  # apply_mode=auto 不在 manual_pending
        assert result["_source"] == "llm"

    def test_llm_mode_does_not_produce_hybrid_triggers(self):
        """llm 模式结果不应含 _hybrid_triggers 键。"""
        blocks = [_make_block(0, 0, "正文")]
        mock_review = _make_review([{"index": 0, "text_preview": "正文", "paragraph_type": "body", "confidence": 0.9}])
        router = ModeRouter(mode="llm")
        mock_client = MagicMock()
        mock_client.call_review.return_value = mock_review
        mock_analyzer = MagicMock()
        mock_analyzer.client = mock_client
        router._analyzer = mock_analyzer

        with patch.object(ModeRouter, "_extract_paragraphs", return_value=["正文"]):
            result = router.route(MagicMock(), blocks, {0: "body"})

        assert "_hybrid_triggers" not in result


# ---------------------------------------------------------------------------
# 6. LLMSuggestion 字段完整性
# ---------------------------------------------------------------------------

class TestLLMSuggestionSchema:
    def test_suggestion_required_fields(self):
        """LLMSuggestion 的必要字段应均可设置并序列化。"""
        s = LLMSuggestion(
            category="hierarchy",
            severity="high",
            confidence=0.9,
            evidence="段落2: 第一节 概述",
            suggestion="建议将「第一节」改为二级标题样式",
            rationale="当前使用了一级标题字号但层级为二级",
            apply_mode="manual",
            paragraph_index=2,
        )
        d = s.model_dump()
        for field in ("category", "severity", "confidence", "evidence", "suggestion", "rationale", "apply_mode"):
            assert field in d, f"字段 {field} 缺失"

    def test_suggestion_default_apply_mode(self):
        """apply_mode 默认值应为 manual。"""
        s = LLMSuggestion(
            category="ambiguity",
            severity="low",
            confidence=0.6,
            evidence="段落5",
            suggestion="改写",
            rationale="歧义",
        )
        assert s.apply_mode == "manual"

    def test_suggestion_all_categories_valid(self):
        """所有 category 枚举值应可构造。"""
        for cat in ("hierarchy", "ambiguity", "structure", "style", "terminology"):
            s = LLMSuggestion(
                category=cat,
                severity="low",
                confidence=0.5,
                evidence="e",
                suggestion="s",
                rationale="r",
            )
            assert s.category == cat

    def test_document_review_suggestions_optional(self):
        """DocumentReview 的 suggestions 应默认为空列表。"""
        review = DocumentReview(
            total_paragraphs=1,
            paragraphs=[ParagraphTag(index=0, text_preview="x", paragraph_type="body", confidence=0.9)],
        )
        assert review.suggestions == []


# ---------------------------------------------------------------------------
# 7. LLMClient canonicalize suggestion
# ---------------------------------------------------------------------------

class TestLLMClientCanonicalizeSuggestion:
    def test_canonicalize_suggestion_normalizes_fields(self):
        from agent.llm_client import LLMClient
        raw = {
            "category": "not_valid",  # -> ambiguity
            "severity": "extreme",    # -> low
            "confidence": "85%",      # -> 0.85
            "apply_mode": "unknown",  # -> manual
        }
        result = LLMClient._canonicalize_suggestion(raw)
        assert result["category"] == "ambiguity"
        assert result["severity"] == "low"
        assert abs(result["confidence"] - 0.85) < 1e-9
        assert result["apply_mode"] == "manual"
        assert result["evidence"] == ""
        assert result["suggestion"] == ""
        assert result["rationale"] == ""

    def test_canonicalize_review_payload_with_suggestions(self):
        from agent.llm_client import LLMClient
        payload = {
            "doc_language": "zh",
            "paragraphs": [
                {"index": 0, "text_preview": "标题", "paragraph_type": "title_1", "confidence": 0.9},
            ],
            "suggestions": [
                {
                    "category": "hierarchy",
                    "severity": "high",
                    "confidence": 0.8,
                    "evidence": "段落0",
                    "suggestion": "调整层级",
                    "rationale": "层级混乱",
                    "apply_mode": "manual",
                }
            ],
        }
        result = LLMClient._canonicalize_review_payload(payload)
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["category"] == "hierarchy"

    def test_canonicalize_review_payload_missing_suggestions(self):
        from agent.llm_client import LLMClient
        payload = {
            "doc_language": "zh",
            "paragraphs": [],
        }
        result = LLMClient._canonicalize_review_payload(payload)
        assert result["suggestions"] == []
