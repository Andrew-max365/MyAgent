# core/writer.py
from docx.document import Document as DocxDocument

def save_docx(doc: DocxDocument, output_path: str):
    doc.save(output_path)