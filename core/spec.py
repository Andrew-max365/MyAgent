# core/spec.py
from dataclasses import dataclass
from typing import Any, Dict
import yaml

@dataclass
class Spec:
    raw: Dict[str, Any]

def load_spec(path: str) -> Spec:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Spec(raw=data)