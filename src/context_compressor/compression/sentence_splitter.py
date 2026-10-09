from __future__ import annotations

import re
from typing import List


def split_document_into_sentences(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    normalized = re.sub(r"\s+", " ", text.strip())
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    return [s.strip() for s in sentences if s and s.strip()]
