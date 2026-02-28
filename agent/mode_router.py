# agent/mode_router.py
# 根据 LLM_MODE 环境变量，将文档分析请求路由到不同的处理逻辑
from config import LLM_MODE
from agent.doc_analyzer import DocAnalyzer
from agent.schema import DocumentStructure


def route_and_analyze(doc_path: str) -> dict:
    """
    根据 LLM_MODE 路由到不同模式，统一返回分析结果字典。

    返回值格式：
      {
        'mode': str,                     # 实际使用的模式名称
        'structure': DocumentStructure or None,  # LLM 分析结果（rule 模式为 None）
        'use_rule': bool,                # 是否使用规则引擎
        'fallback_indices': list[int],   # hybrid 模式下置信度不足、需规则兜底的段落序号（可选）
      }

    :param doc_path: .docx 文件路径
    :return: 包含模式、结构分析结果和规则标志的字典
    :raises ValueError: LLM_MODE 取值不合法时抛出
    """
    if LLM_MODE == "rule":
        # 纯规则模式：不调用大模型，直接由规则引擎处理
        return {"mode": "rule", "structure": None, "use_rule": True}

    elif LLM_MODE == "llm":
        # 纯 LLM 模式：完全由大模型分析文档结构
        analyzer = DocAnalyzer()
        structure = analyzer.analyze(doc_path)
        return {"mode": "llm", "structure": structure, "use_rule": False}

    elif LLM_MODE == "hybrid":
        # 混合模式：LLM 主判断 + 低置信度段落规则兜底
        analyzer = DocAnalyzer()
        try:
            structure = analyzer.analyze(doc_path)
            # 筛选置信度低于 0.7 的段落，标记为需要规则兜底
            low_conf = [p for p in structure.paragraphs if p.confidence < 0.7]
            return {
                "mode": "hybrid",
                "structure": structure,
                "use_rule": True,
                "fallback_indices": [p.index for p in low_conf],
            }
        except Exception as e:
            # LLM 调用失败时，完全回退到规则模式；记录异常信息便于排查
            import warnings
            warnings.warn(f"hybrid 模式下 LLM 调用失败，已回退到纯规则模式。原因: {e}", stacklevel=2)
            return {"mode": "hybrid_fallback", "structure": None, "use_rule": True}

    else:
        raise ValueError(f"Unknown LLM_MODE: {LLM_MODE}")
