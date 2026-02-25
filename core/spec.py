# core/spec.py
from dataclasses import dataclass
from typing import Any, Dict

import yaml


@dataclass
class Spec:
    raw: Dict[str, Any]


def _ensure_dict(value: Any, key: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"spec.{key} must be a mapping")
    return value


def _validate_and_fill_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(data)

    fonts = _ensure_dict(cfg.get("fonts"), "fonts")
    if not fonts.get("zh") or not fonts.get("en"):
        raise ValueError("spec.fonts.zh and spec.fonts.en are required")

    body = _ensure_dict(cfg.get("body"), "body")
    for key in ["font_size_pt", "line_spacing", "space_before_pt", "space_after_pt", "first_line_chars"]:
        if key not in body:
            raise ValueError(f"spec.body.{key} is required")

    heading = _ensure_dict(cfg.get("heading"), "heading")
    for h in ["h1", "h2", "h3"]:
        hc = _ensure_dict(heading.get(h), f"heading.{h}")
        for key in ["font_size_pt", "bold", "space_before_pt", "space_after_pt"]:
            if key not in hc:
                raise ValueError(f"spec.heading.{h}.{key} is required")

    cleanup = dict(cfg.get("cleanup") or {})
    if cleanup.get("remove_all_blank_paragraphs"):
        cleanup["max_consecutive_blank_paragraphs"] = 0
    cleanup.setdefault("max_consecutive_blank_paragraphs", 1)
    cleanup.setdefault("remove_blank_after_roles", ["h1", "h2", "h3", "caption"])
    cfg["cleanup"] = cleanup

    list_item = dict(cfg.get("list_item") or {})
    list_item.setdefault("left_indent_pt", 18)
    list_item.setdefault("hanging_indent_pt", 18)
    list_item.setdefault("min_run_len", 2)
    cfg["list_item"] = list_item

    return cfg


def load_spec(path: str) -> Spec:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("spec file must be a YAML mapping at top-level")

    return Spec(raw=_validate_and_fill_defaults(data))
