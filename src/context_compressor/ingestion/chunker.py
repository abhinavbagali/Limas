from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4
from typing import Sequence

from .pdf_extractor import PageMetadata

TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_id: str
    doc_id: str
    text: str
    page_start: int
    page_end: int
    section_title: str | None
    token_count: int


class _TokenCodec:
    def __init__(self) -> None:
        self.tokenizer = None
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME, local_files_only=True)
        except Exception:
            pass

    def encode(self, text: str) -> list[int] | list[str]:
        if self.tokenizer is not None:
            return self.tokenizer.encode(text, add_special_tokens=False)
        return re.findall(r"\w+|[^\w\s]", text, re.UNICODE)

    def decode(self, tokens: Sequence[int] | Sequence[str]) -> str:
        if self.tokenizer is not None:
            return self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        return " ".join(tokens)


def chunk_pages(
    pages: Sequence[PageMetadata],
    target_tokens: int = 500,
    overlap_tokens: int = 80,
    *,
    codec: _TokenCodec | None = None,
) -> list[TextChunk]:
    if target_tokens < 1 or overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("Require target_tokens > overlap_tokens >= 0.")
    codec = codec or _TokenCodec()
    chunks: list[TextChunk] = []
    current_tokens: list[int] | list[str] = []
    current_start = current_end = 0
    current_doc = ""
    current_section: str | None = None

    def flush() -> None:
        nonlocal current_tokens
        if not current_tokens:
            return
        text = codec.decode(current_tokens)
        if text.strip():
            chunks.append(TextChunk(str(uuid4()), current_doc, text, current_start, current_end, current_section, len(current_tokens)))
        current_tokens = []

    for page in pages:
        if not page.text.strip():
            continue
        if current_tokens and page.doc_id != current_doc:
            flush()
        if not current_tokens:
            current_doc, current_start, current_end, current_section = page.doc_id, page.page_number, page.page_number, page.section_title
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page.text) if part.strip()]
        if not paragraphs:
            paragraphs = [page.text.strip()]
        for paragraph in paragraphs:
            units = re.split(r"(?<=[.!?])\s+", paragraph)
            for unit in filter(None, (item.strip() for item in units)):
                tokens = codec.encode(unit)
                if not tokens:
                    continue
                if current_tokens and len(current_tokens) + len(tokens) > target_tokens:
                    previous = list(current_tokens)
                    flush()
                    overlap = previous[-overlap_tokens:] if overlap_tokens else []
                    current_tokens = list(overlap)
                    current_doc, current_start, current_end, current_section = page.doc_id, page.page_number, page.page_number, page.section_title
                if len(tokens) > target_tokens:
                    for offset in range(0, len(tokens), target_tokens - overlap_tokens):
                        part = tokens[offset : offset + target_tokens]
                        if current_tokens and len(current_tokens) + len(part) > target_tokens:
                            flush()
                        current_doc, current_start, current_end, current_section = page.doc_id, page.page_number, page.page_number, page.section_title
                        current_tokens = list(part)
                        current_end = page.page_number
                        flush()
                    continue
                if current_tokens and len(current_tokens) + len(tokens) > target_tokens:
                    flush()
                if not current_tokens:
                    current_doc, current_start, current_end, current_section = page.doc_id, page.page_number, page.page_number, page.section_title
                current_tokens.extend(tokens)
                current_end = page.page_number
    flush()
    return chunks
