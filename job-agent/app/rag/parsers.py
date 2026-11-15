"""多格式知识文件解析：txt / md / docx / pdf → 纯文本。"""
from __future__ import annotations

import os

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}


def parse_file(path: str) -> str:
    """按扩展名分发解析，返回纯文本。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return _parse_docx(path)
    if ext == ".pdf":
        return _parse_pdf(path)
    return _parse_text(path)


def _parse_text(path: str) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


def _parse_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)
