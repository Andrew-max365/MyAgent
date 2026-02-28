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


def test_field_alias_canonicalization():
    payload = {
        "doc_language": "zh",
        "paragraphs": [
            {
                "paragraph_index": 0,
                "text": "这是标题",
                "type": "h1",
            },
            {
                "paragraph_index": 1,
                "text": "这是正文",
                "label": "paragraph",
                "confidence": 0.8,
            },
        ],
    }

    normalized = LLMClient._canonicalize_structure_payload(payload)

    assert normalized["total_paragraphs"] == 2
    assert normalized["paragraphs"][0]["index"] == 0
    assert normalized["paragraphs"][0]["text_preview"] == "这是标题"
    assert normalized["paragraphs"][0]["paragraph_type"] == "title_1"
    assert normalized["paragraphs"][0]["confidence"] == 0.0
    assert normalized["paragraphs"][1]["paragraph_type"] == "body"
    assert normalized["paragraphs"][1]["confidence"] == 0.8


def test_confidence_canonicalization_accepts_string_percent_and_clamps():
    payload = {
        "doc_language": "zh",
        "paragraphs": [
            {"index": 0, "text_preview": "a", "paragraph_type": "body", "confidence": "0.75"},
            {"index": 1, "text_preview": "b", "paragraph_type": "body", "confidence": "85%"},
            {"index": 2, "text_preview": "c", "paragraph_type": "body", "confidence": 2},
            {"index": 3, "text_preview": "d", "paragraph_type": "body", "confidence": -0.2},
            {"index": 4, "text_preview": "e", "paragraph_type": "body", "confidence": "bad"},
        ],
    }

    normalized = LLMClient._canonicalize_structure_payload(payload)
    confidences = [p["confidence"] for p in normalized["paragraphs"]]

    assert confidences == [0.75, 0.85, 0.02, 0.0, 0.0]
