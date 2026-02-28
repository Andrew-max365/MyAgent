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


def test_canonicalize_structure_payload_normalizes_alias_types():
    payload = {
        "doc_language": "zh",
        "paragraphs": [
            {"index": 0, "text_preview": "标题", "paragraph_type": "一级标题", "confidence": 0.9},
            {"index": 1, "text_preview": "正文", "paragraph_type": "paragraph", "confidence": 0.9},
            {"index": 2, "text_preview": "图注", "paragraph_type": "caption", "confidence": 0.9},
            {"index": 3, "text_preview": "未知", "paragraph_type": "not-a-role", "confidence": 0.2},
        ],
    }

    normalized = LLMClient._canonicalize_structure_payload(payload)

    assert normalized["total_paragraphs"] == 4
    assert [p["paragraph_type"] for p in normalized["paragraphs"]] == [
        "title_1",
        "body",
        "figure_caption",
        "unknown",
    ]
