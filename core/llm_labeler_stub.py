# core/llm_labeler_stub.py
"""
This is a stub for DeepSeek/GPT labeling.
Goal: input blocks -> output {block_id: role} in strict JSON.
Do NOT generate docx/xml. Only return labels.
"""

from typing import Dict, List
from .parser import Block

def llm_labels(blocks: List[Block]) -> Dict[int, str]:
    # TODO: call DeepSeek API here and return labels.
    # For now, raise to remind you this is not implemented.
    raise NotImplementedError("LLM labeling not implemented yet. Use rule_based_labels in judge.py")