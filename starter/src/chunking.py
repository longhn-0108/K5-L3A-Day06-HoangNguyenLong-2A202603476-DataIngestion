"""Implement fixed-size and structure-aware chunking."""
from __future__ import annotations

import re

from .models import Chunk, DocumentPage

STRUCTURE_START_RE = re.compile(
    r"^(Chương\s+[IVX]+|Mục\s+\d+|Điều\s+\d+\.|\d+\.\s+|[a-zđ]\)\s+)"
)


def _collapse_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fixed_size(page: DocumentPage, size: int = 500, overlap: int = 50, strategy_tag: str = "A") -> list[Chunk]:
    """Split text into overlapping windows and retain page metadata."""
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    text = _collapse_inline(page.text)
    if not text:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            meta = dict(page.metadata)
            meta["chunk_index"] = idx
            meta["chunking"] = "fixed_size"
            chunks.append(
                Chunk(
                    chunk_id=f"{strategy_tag}::{page.document_id}::p{page.page}::c{idx}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=piece,
                    metadata=meta,
                )
            )
            idx += 1
        if end == len(text):
            break
        start += step
    return chunks


def _split_legal_paragraphs(text: str) -> list[str]:
    """Group wrapped lines into logical legal clauses/paragraphs."""
    paragraphs: list[str] = []
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_lines:
                paragraphs.append(" ".join(current_lines))
                current_lines = []
            continue

        if STRUCTURE_START_RE.match(line) and current_lines:
            paragraphs.append(" ".join(current_lines))
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        paragraphs.append(" ".join(current_lines))
    return [p for p in paragraphs if p.strip()]


def by_paragraph(
    page: DocumentPage,
    max_size: int = 700,
    overlap: int = 80,
    strategy_tag: str = "B",
) -> list[Chunk]:
    """Group paragraphs, split oversized paragraphs and retain metadata."""
    if max_size <= 0:
        raise ValueError("max_size must be > 0")

    paragraphs = _split_legal_paragraphs(page.text)
    if not paragraphs:
        return []

    grouped_texts: list[str] = []
    buffer = ""

    for para in paragraphs:
        if len(para) > max_size:
            if buffer:
                grouped_texts.append(buffer)
                buffer = ""
            step = max(1, max_size - overlap)
            start = 0
            while start < len(para):
                end = min(start + max_size, len(para))
                grouped_texts.append(para[start:end].strip())
                if end == len(para):
                    break
                start += step
            continue

        candidate = f"{buffer}\n{para}".strip() if buffer else para
        if len(candidate) <= max_size:
            buffer = candidate
        else:
            if buffer:
                grouped_texts.append(buffer)
            buffer = para

    if buffer:
        grouped_texts.append(buffer)

    chunks: list[Chunk] = []
    for idx, piece in enumerate(grouped_texts):
        meta = dict(page.metadata)
        meta["chunk_index"] = idx
        meta["chunking"] = "by_paragraph"
        chunks.append(
            Chunk(
                chunk_id=f"{strategy_tag}::{page.document_id}::p{page.page}::c{idx}",
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=piece,
                metadata=meta,
            )
        )
    return chunks
