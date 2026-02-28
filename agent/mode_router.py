# agent/mode_router.py
# 根据 LLM_MODE 环境变量，将文档分析请求路由到不同的处理逻辑
from __future__ import annotations

from typing import Dict

from config import LLM_MODE
from agent.doc_analyzer import DocAnalyzer
from agent.llm_client import LLMCallError
from agent.schema import DocumentStructure

# hybrid 模式下的置信度阈值：低于此值的段落回退到规则
HYBRID_CONFIDENCE_THRESHOLD = 0.7


LLM_TO_INTERNAL_ROLE = {
    "title_1": "h1",
    "title_2": "h2",
    "title_3": "h3",
    "body": "body",
    "list_item": "list_item",
    "table_caption": "caption",
    "figure_caption": "caption",
    "abstract": "abstract",
    "keyword": "keyword",
    "reference": "reference",
    "footer": "footer",
    "unknown": "unknown",
}


def _normalize_role(role: str) -> str:
    """将 LLM schema 标签统一映射为 formatter 可识别标签。"""
    return LLM_TO_INTERNAL_ROLE.get(role, "unknown")


def _structure_to_labels(structure: DocumentStructure) -> Dict[int, str]:
    """将 DocumentStructure 转换为 {paragraph_index: paragraph_type} 字典"""
    return {p.index: _normalize_role(p.paragraph_type) for p in structure.paragraphs}


def _structure_low_confidence(structure: DocumentStructure) -> list:
    """返回置信度低于阈值的段落索引列表"""
    return [
        p.index for p in structure.paragraphs
        if p.confidence < HYBRID_CONFIDENCE_THRESHOLD
    ]


class ModeRouter:
    """
    三模式路由器：根据 mode 参数（或 LLM_MODE 环境变量）将分析请求路由到
    rule / llm / hybrid 三种处理逻辑。
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
        纯 LLM 模式：完全由大模型分析，未覆盖段落用规则补全。
        """
        structure = self.analyzer.analyze(doc)
        labels = self._map_to_block_ids(structure, blocks, rule_labels)
        labels["_source"] = "llm"
        return labels

    def _hybrid(self, doc, blocks, rule_labels: Dict) -> Dict:
        """
        混合模式：LLM 主判断，置信度不足或失败时用规则兜底。
        """
        try:
            structure = self.analyzer.analyze(doc)
        except LLMCallError as e:
            # LLM 完全失败，回退纯规则，返回副本避免修改调用方的字典
            result = dict(rule_labels)
            result.setdefault("_warnings", [])
            result["_warnings"].append(
                f"LLM 调用失败，hybrid 模式已全量回退到纯规则: {e}"
            )
            return result

        # 找出置信度低的段落索引
        low_conf_indices = set(_structure_low_confidence(structure))

        # 按 paragraph_index 构建 LLM 标签
        llm_para_labels = _structure_to_labels(structure)

        # 构建 block_id -> role 映射（优先 LLM，低置信度则用规则兜底）
        merged: Dict = {}
        for b in blocks:
            if b.paragraph_index in low_conf_indices:
                # 规则兜底
                merged[b.block_id] = rule_labels.get(b.block_id, "body")
            elif b.paragraph_index in llm_para_labels:
                merged[b.block_id] = llm_para_labels[b.paragraph_index]
            else:
                # LLM 未覆盖到的段落，用规则补全
                merged[b.block_id] = rule_labels.get(b.block_id, "body")

        merged["_source"] = "hybrid"
        if low_conf_indices:
            merged.setdefault("_warnings", [])
            merged["_warnings"].append(
                f"hybrid 模式：{len(low_conf_indices)} 个段落置信度 < {HYBRID_CONFIDENCE_THRESHOLD}，已使用规则兜底"
            )
        return merged

    def _map_to_block_ids(
        self,
        structure: DocumentStructure,
        blocks,
        rule_labels: Dict,
    ) -> Dict:
        """
        将 DocumentStructure（按 paragraph_index 索引）映射到 block_id 索引。
        未覆盖的段落用规则标签补全。
        """
        llm_para_labels = _structure_to_labels(structure)
        result: Dict = {}
        for b in blocks:
            if b.paragraph_index in llm_para_labels:
                result[b.block_id] = llm_para_labels[b.paragraph_index]
            else:
                result[b.block_id] = rule_labels.get(b.block_id, "body")
        return result
