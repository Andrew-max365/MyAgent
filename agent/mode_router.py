# agent/mode_router.py
# 根据 LLM_MODE 环境变量，将文档分析请求路由到不同的处理逻辑
from __future__ import annotations

from typing import Dict, List, Optional, Set

from config import LLM_MODE
from agent.doc_analyzer import DocAnalyzer
from agent.llm_client import LLMCallError
from agent.schema import DocumentProofread

# hybrid 触发条件阈值
# 规则标为 unknown 的段落数阈值（≥1 即触发）
HYBRID_TRIGGER_UNKNOWN_MIN = 1
# 标题段落文本长度阈值：超过此字符数视为"疑似误分类"触发
HYBRID_TRIGGER_HEADING_LEN = 30
# 连续短 body 段落数阈值：可能是未识别的列表
HYBRID_TRIGGER_CONSECUTIVE_BODY_MIN = 3
# 连续 body 段落中认定为"短"的字符数上限
HYBRID_TRIGGER_SHORT_BODY_CHARS = 60


def _compute_hybrid_triggers(blocks, rule_labels: Dict) -> Dict:
    """
    评估规则层标签，判断是否需要调用 LLM 进行语义审阅。

    触发条件：
    1. unknown_labels：规则无法判定类型的段落（≥1 个）
    2. heading_ambiguity：被规则标为 h2/h3 但文本较长（>30字）的标题段落
    3. potential_list：连续 ≥3 个短 body 段落，可能是未识别的列表

    :param blocks: List[Block]
    :param rule_labels: {block_id: role}
    :return: {
        "triggered": bool,
        "reasons": ["原因描述", ...],
        "triggered_indices": set[paragraph_index],
        "metrics": {"unknown_count": N, ...}
    }
    """
    triggered_indices: Set[int] = set()
    reasons: List[str] = []
    metrics: Dict = {}

    # --- Trigger 1: unknown labels ---
    unknown_blocks = [b for b in blocks if rule_labels.get(b.block_id) == "unknown"]
    metrics["unknown_count"] = len(unknown_blocks)
    if len(unknown_blocks) >= HYBRID_TRIGGER_UNKNOWN_MIN:
        for b in unknown_blocks:
            triggered_indices.add(b.paragraph_index)
        reasons.append(
            f"术语/类型不明: {len(unknown_blocks)} 个段落规则无法判定 (unknown)，需语义审阅"
        )

    # --- Trigger 2: heading ambiguity ---
    ambiguous_headings = [
        b for b in blocks
        if rule_labels.get(b.block_id) in ("h2", "h3")
        and len(b.text or "") > HYBRID_TRIGGER_HEADING_LEN
    ]
    metrics["ambiguous_heading_count"] = len(ambiguous_headings)
    if ambiguous_headings:
        for b in ambiguous_headings:
            triggered_indices.add(b.paragraph_index)
        reasons.append(
            f"标题层级疑似错误: {len(ambiguous_headings)} 个标题段落文本超过 "
            f"{HYBRID_TRIGGER_HEADING_LEN} 字符，可能被误分类"
        )

    # --- Trigger 3: consecutive short body paragraphs (potential list) ---
    sorted_blocks = sorted(blocks, key=lambda x: x.paragraph_index)
    run: List = []
    for b in sorted_blocks:
        role = rule_labels.get(b.block_id)
        text = b.text or ""
        if role == "body" and 0 < len(text.strip()) <= HYBRID_TRIGGER_SHORT_BODY_CHARS:
            run.append(b)
        else:
            if len(run) >= HYBRID_TRIGGER_CONSECUTIVE_BODY_MIN:
                for rb in run:
                    triggered_indices.add(rb.paragraph_index)
                reasons.append(
                    f"结构化改写机会: {len(run)} 个连续短正文段落（≤{HYBRID_TRIGGER_SHORT_BODY_CHARS}字），"
                    f"可能适合列表化（段落 {run[0].paragraph_index}~{run[-1].paragraph_index}）"
                )
            run = []
    # flush last run
    if len(run) >= HYBRID_TRIGGER_CONSECUTIVE_BODY_MIN:
        for rb in run:
            triggered_indices.add(rb.paragraph_index)
        reasons.append(
            f"结构化改写机会: {len(run)} 个连续短正文段落（≤{HYBRID_TRIGGER_SHORT_BODY_CHARS}字），"
            f"可能适合列表化（段落 {run[0].paragraph_index}~{run[-1].paragraph_index}）"
        )

    metrics["consecutive_short_body_triggered"] = any(
        "结构化改写机会" in r for r in reasons
    )

    return {
        "triggered": bool(triggered_indices),
        "reasons": reasons,
        "triggered_indices": triggered_indices,
        "metrics": metrics,
    }


class ModeRouter:
    """
    三模式路由器：根据 mode 参数（或 LLM_MODE 环境变量）将分析请求路由到
    rule / llm / hybrid 三种处理逻辑。

    模式职责边界
    ============
    rule：仅执行确定性规则完成排版，不调用 LLM。

    llm：规则负责全部排版，LLM 仅对整篇文档做校对（错别字/标点/规范性），
         输出校对问题列表供提交者自行修改（不自动应用）。
         输出包含 _llm_proofread 键，携带 DocumentProofread（issues 校对问题列表）。

    hybrid：先运行规则层排版，仅当触发条件命中时调用 LLM 对触发段落做校对。
            输出包含 _hybrid_triggers 键（触发原因/指标）和 _llm_proofread
            键（若触发了 LLM）。若无触发，完全等同于规则模式，不会调用 LLM。
    """

    def __init__(self, mode: str = LLM_MODE):
        """
        :param mode: 排版模式，"rule" / "llm" / "hybrid"
        """
        if mode not in ("rule", "llm", "hybrid"):
            raise ValueError(f"mode 必须为 rule/llm/hybrid，当前值: {mode!r}")
        self.mode = mode
        # DocAnalyzer 按需初始化（rule 模式下不创建，避免触发 API Key 检查）
        self._analyzer: DocAnalyzer | None = None

    @property
    def analyzer(self) -> DocAnalyzer:
        """懒加载 DocAnalyzer（rule 模式下不需要）"""
        if self._analyzer is None:
            self._analyzer = DocAnalyzer()
        return self._analyzer

    def route(self, doc, blocks, rule_labels: Dict) -> Dict:
        """
        路由入口：根据 mode 分发到对应的处理逻辑。

        :param doc: python-docx Document 对象
        :param blocks: List[Block]，由 core.parser.parse_docx_to_blocks 返回
        :param rule_labels: {block_id: role}，由 core.judge.rule_based_labels 返回
        :return: {block_id: role, "_source": mode} 标签字典，rule_labels 不被修改
        """
        if self.mode == "rule":
            result = dict(rule_labels)
            result["_source"] = "rule"
            return result
        elif self.mode == "llm":
            return self._llm(doc, blocks, rule_labels)
        else:
            return self._hybrid(doc, blocks, rule_labels)

    def _llm(self, doc, blocks, rule_labels: Dict) -> Dict:
        """
        LLM 模式：规则负责全部排版，LLM 仅对整篇文档做校对。

        校对结果（错别字/标点/规范性问题）写入 _llm_proofread，
        供提交者自行修改，不自动应用。
        """
        # 排版标签完全来自规则
        result = dict(rule_labels)
        result["_source"] = "llm"

        # LLM 仅做校对，不做结构标注
        proofread: DocumentProofread = self.analyzer.client.call_proofread(
            paragraphs=self._extract_paragraphs(doc),
        )
        result["_llm_proofread"] = {
            "issues": [issue.model_dump() for issue in proofread.issues],
        }
        return result

    def _hybrid(self, doc, blocks, rule_labels: Dict) -> Dict:
        """
        混合模式：规则负责全部排版，仅当触发条件命中时 LLM 对触发段落做校对。

        执行流程：
        1. 使用规则标签作为排版基准（不依赖 LLM 的结构判断）
        2. 评估触发条件（unknown/标题歧义/潜在列表）
        3. 仅在触发时调用 LLM，仅校对触发段落（≤20% 高价值任务）
        4. 校对结果写入 _llm_proofread，供提交者自行修改，不自动应用
        5. 在 _hybrid_triggers 中记录触发原因与指标
        """
        # 步骤 1: 计算触发条件
        trigger_info = _compute_hybrid_triggers(blocks, rule_labels)

        # 排版标签完全来自规则
        result: Dict = {}
        for b in blocks:
            result[b.block_id] = rule_labels.get(b.block_id, "body")

        result["_source"] = "hybrid"
        result["_hybrid_triggers"] = {
            "triggered": trigger_info["triggered"],
            "reasons": trigger_info["reasons"],
            "triggered_paragraph_count": len(trigger_info["triggered_indices"]),
            "total_paragraph_count": len(blocks),
            "metrics": trigger_info["metrics"],
        }

        if not trigger_info["triggered"]:
            # 无触发：完全使用规则结果，不调用 LLM
            result["_hybrid_triggers"]["llm_called"] = False
            return result

        # 步骤 2: 调用 LLM 对触发段落做校对
        all_paragraphs = self._extract_paragraphs(doc)
        try:
            proofread: DocumentProofread = self.analyzer.client.call_proofread(
                paragraphs=all_paragraphs,
                paragraph_indices=sorted(trigger_info["triggered_indices"]),
            )
        except LLMCallError as e:
            # LLM 已尝试调用但失败，保留规则结果并记录警告
            result.setdefault("_warnings", [])
            result["_warnings"].append(
                f"hybrid 模式 LLM 校对失败，已保留规则结果: {e}"
            )
            result["_hybrid_triggers"]["llm_called"] = True
            result["_hybrid_triggers"]["llm_error"] = str(e)
            return result

        result["_hybrid_triggers"]["llm_called"] = True

        # 步骤 3: 记录校对结果（供提交者自行修改）
        result["_llm_proofread"] = {
            "issues": [issue.model_dump() for issue in proofread.issues],
        }

        return result

    @staticmethod
    def _extract_paragraphs(doc) -> List[str]:
        """从 doc 提取所有段落文本（含表格段落），保持索引一致。"""
        from core.docx_utils import iter_all_paragraphs
        return [p.text for p in iter_all_paragraphs(doc)]
