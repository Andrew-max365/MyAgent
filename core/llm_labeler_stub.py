# core/llm_labeler_stub.py
"""LLM labeling helpers (OpenAI-compatible chat completions API).

Environment variables:
- LLM_API_KEY (required for llm/hybrid mode)
- LLM_BASE_URL (optional, default https://api.openai.com/v1)
- LLM_MODEL (optional, default gpt-4o-mini)
- LLM_TIMEOUT_S (optional, default 45)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List

from .parser import Block

VALID_ROLES = {"blank", "h1", "h2", "h3", "caption", "body"}


def _build_prompt(blocks: List[Block]) -> str:
    payload = [
        {
            "block_id": b.block_id,
            "paragraph_index": b.paragraph_index,
            "text": (b.text or "")[:500],
        }
        for b in blocks
    ]
    schema = {
        "type": "object",
        "description": "Map block_id(string) -> role(string)",
        "roles": sorted(list(VALID_ROLES)),
    }
    return (
        "You are a DOCX structure labeling model. "
        "Classify each paragraph block into exactly one role: "
        "blank, h1, h2, h3, caption, body. "
        "Return ONLY a JSON object mapping block_id to role. "
        "No markdown, no explanation.\n\n"
        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Blocks: {json.dumps(payload, ensure_ascii=False)}"
    )


def _normalize_labels(raw: Dict, blocks: List[Block]) -> Dict[int, str]:
    by_id = {b.block_id: b for b in blocks}
    result: Dict[int, str] = {}
    for key, value in (raw or {}).items():
        try:
            block_id = int(key)
        except Exception:
            continue
        if block_id not in by_id:
            continue
        role = str(value).strip().lower()
        if role in VALID_ROLES:
            result[block_id] = role
    return result


def llm_labels(blocks: List[Block]) -> Dict[int, str]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not set")

    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    timeout_s = int(os.getenv("LLM_TIMEOUT_S", "45"))

    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": _build_prompt(blocks)},
        ],
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM HTTPError {e.code}: {detail[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM URLError: {e}") from e

    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "{}")
    )
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))

    try:
        raw = json.loads(content)
    except Exception as e:
        raise RuntimeError(f"LLM returned non-JSON content: {str(content)[:300]}") from e

    labels = _normalize_labels(raw, blocks)
    if not labels:
        raise RuntimeError("LLM returned empty/invalid labels")
    return labels
