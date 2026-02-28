# agent/mode_router.py
# 三种排版模式路由：rule / llm / hybrid
# hybrid 模式置信度阈值为 0.7，低于阈值的段落由规则兜底；
# LLM 完全失败时回退到纯规则模式。
from __future__ import annotations

from typing import Dict, List, Optional

import config
from agent.llm_client import LLMClient, LLMCallError
from agent.doc_analyzer import DocAnalyzer
from agent.schema import DocumentStructure, ParagraphTag

# hybrid 模式下，置信度低于此阈值的段落将使用规则兜底
HYBRID_CONFIDENCE_THRESHOLD: float = 0.7

# LLM paragraph_type -> 内部 role 映射
_TYPE_TO_ROLE: Dict[str, str] = {
    "title_1": "h1",
    "title_2": "h2",
    "title_3": "h3",
    "body": "body",
    "list_item": "body",
    "table_caption": "caption",
    "figure_caption": "caption",
    "abstract": "body",
    "keyword": "body",
    "reference": "body",
    "footer": "body",
    "unknown": "body",
}


def _structure_to_labels(structure: DocumentStructure) -> Dict[int, str]:
    """将 DocumentStructure 转换为 {paragraph_index: role} 字典。"""
    return {
        tag.index: _TYPE_TO_ROLE.get(tag.paragraph_type, "body")
        for tag in structure.paragraphs
    }


def _structure_low_confidence(
    structure: DocumentStructure,
    threshold: float = HYBRID_CONFIDENCE_THRESHOLD,
) -> List[int]:
    """返回置信度低于阈值的段落索引列表。"""
    return [
        tag.index
        for tag in structure.paragraphs
        if tag.confidence < threshold
    ]


class ModeRouter:
    """
    根据 LLM_MODE 环境变量（或构造时传入的 mode）路由到不同处理逻辑。

    支持三种模式：
    - rule：纯规则模式，不调用 LLM
    - llm：纯 LLM 模式，完全由模型识别文档结构
    - hybrid：混合模式（推荐），LLM 主判断 + 规则兜底
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        client: Optional[LLMClient] = None,
    ):
        # 优先使用构造参数，否则从 config 读取
        self.mode = (mode or config.LLM_MODE).strip().lower()
        self.analyzer = DocAnalyzer(client=client)

    def route(self, doc, blocks, rule_labels: Dict) -> Dict:
        """
        根据模式返回段落标签字典。

        :param doc: python-docx Document 对象
        :param blocks: 解析后的 Block 列表（core.parser.Block）
        :param rule_labels: 已由规则模块计算好的标签字典 {block_id: role}
        :return: 最终标签字典（格式与 rule_labels 兼容）
        """
        if self.mode == "rule":
            return rule_labels

        if self.mode == "llm":
            return self._llm_only(doc, blocks, rule_labels)

        if self.mode == "hybrid":
            return self._hybrid(doc, blocks, rule_labels)

        # 未知模式退回规则，返回副本避免修改调用方的字典
        result = dict(rule_labels)
        result.setdefault("_warnings", [])
        result["_warnings"].append(
            f"未知 LLM_MODE='{self.mode}'，已回退到纯规则模式"
        )
        return result

    def _llm_only(self, doc, blocks, rule_labels: Dict) -> Dict:
        """纯 LLM 模式：完全由模型识别，LLM 失败则回退规则。"""
        try:
            structure = self.analyzer.analyze(doc)
        except LLMCallError as e:
            # 回退规则，返回副本避免修改调用方的字典
            result = dict(rule_labels)
            result.setdefault("_warnings", [])
            result["_warnings"].append(
                f"LLM 调用失败，已回退到纯规则模式: {e}"
            )
            return result

        # 将 paragraph_index 映射转换为 block_id 映射
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
