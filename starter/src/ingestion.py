"""Read and normalize source data."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

CHAPTER_RE = re.compile(r"^(Chương\s+[IVX]+)\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^(Mục\s+\d+)\b", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace without discarding useful structure."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def load_pdf_with_logs(
    path: Path,
    document_id: str,
    source: str,
    base_metadata: dict[str, Any] | None = None,
) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Extract each physical page, track chapter/section metadata, and log empty/error pages."""
    if not path.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")

    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    logs: list[dict[str, Any]] = []

    current_chapter = "Chương I"
    current_section = "Quy định chung"

    for page_num, raw_page in enumerate(reader.pages, start=1):
        try:
            raw_text = raw_page.extract_text() or ""
        except Exception as exc:
            logs.append({"page": page_num, "status": "error", "detail": str(exc)})
            continue

        text = normalize_text(raw_text)
        if not text:
            logs.append({"page": page_num, "status": "empty", "detail": "No extractable text"})
            continue

        for line in text.splitlines():
            s = line.strip()
            chap_m = CHAPTER_RE.match(s)
            if chap_m:
                current_chapter = chap_m.group(1)
                if current_chapter in {"Chương I", "Chương IV"}:
                    current_section = "Quy định chung" if current_chapter == "Chương I" else "Điều khoản thi hành"
            sec_m = SECTION_RE.match(s)
            if sec_m:
                current_section = sec_m.group(1)

        meta: dict[str, Any] = dict(base_metadata or {})
        meta.update(
            {
                "chapter": current_chapter,
                "section": current_section,
                "document_type": meta.get("document_type", "nghi_dinh"),
                "language": meta.get("language", "vi"),
                "year": meta.get("year", 2024),
            }
        )
        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_num,
                text=text,
                metadata=meta,
            )
        )

    return pages, logs


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page; keep its page number and source."""
    pages, _ = load_pdf_with_logs(path=path, document_id=document_id, source=source)
    return pages
