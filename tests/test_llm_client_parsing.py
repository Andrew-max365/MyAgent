from agent.llm_client import LLMClient


def test_normalize_json_text_accepts_plain_json():
    raw = '{"doc_language":"zh","total_paragraphs":0,"paragraphs":[]}'
    assert LLMClient._normalize_json_text(raw) == raw


def test_normalize_json_text_strips_markdown_json_fence():
    raw = """```json
{"doc_language":"zh","total_paragraphs":0,"paragraphs":[]}
```"""
    assert LLMClient._normalize_json_text(raw) == (
        '{"doc_language":"zh","total_paragraphs":0,"paragraphs":[]}'
    )
