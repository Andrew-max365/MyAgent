# core/parser.py
from dataclasses import dataclass
from typing import List, Tuple
from docx import Document

@dataclass
class Block:
    block_id: int
    kind: str              # "paragraph"
    text: str
    paragraph_index: int

def parse_docx_to_blocks(docx_path: str) -> Tuple[Document, List[Block]]:
    doc = Document(docx_path)
    blocks: List[Block] = []
    pid = 0
    for i, p in enumerate(doc.paragraphs):
        pid += 1
        blocks.append(Block(
            block_id=pid,
            kind="paragraph",
            text=(p.text or ""),
            paragraph_index=i
        ))
    return doc, blocks