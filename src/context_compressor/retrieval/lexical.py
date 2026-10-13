from __future__ import annotations

import re
from collections import Counter


_LATEX_SUBSCRIPT = re.compile(r"\$?([A-Za-z][A-Za-z0-9]*)_\{([A-Za-z0-9]+)\}\$?")
_TOKEN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE)
_MATH_SYMBOL = re.compile(r"\$([A-Za-z][A-Za-z0-9]*)\$")
_NUMERIC_OR_FORMULA = re.compile(
    r"(?:\$[^$]+\$|\b[A-Za-z]\s*(?:_|=)\s*\{?[A-Za-z0-9]+|\b\d+(?:\.\d+)?\b)"
)


def normalize_latex(text: str) -> str:
    """Normalize common LaTeX subscript identifiers for exact lexical matching."""
    return _LATEX_SUBSCRIPT.sub(lambda match: f"{match.group(1)}_{match.group(2)}", text)


def lexical_tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(normalize_latex(text))]


def technical_query_terms(query: str) -> set[str]:
    """Return explicit mathematical identifiers and aliases requested by a query."""
    normalized = normalize_latex(query).lower()
    tokens = set(lexical_tokens(normalized))
    requested = {token for token in tokens if "_" in token}
    requested.update(symbol.lower() for symbol in _MATH_SYMBOL.findall(query))

    if re.search(r"\bmodel\s+dimensions?\b|\bd_model\b", normalized):
        requested.update({"d_model", "model"})
    if re.search(r"\bkey\s+dimensions?\b|\bd_k\b", normalized):
        requested.update({"d_k", "key"})
    if re.search(r"\bvalue\s+dimensions?\b|\bd_v\b", normalized):
        requested.update({"d_v", "value"})
    if re.search(r"\b(?:attention\s+)?heads?\b|\bh\b", normalized):
        requested.update({"h", "head", "heads"})
    return requested


def is_technical_lookup(query: str) -> bool:
    normalized = normalize_latex(query).lower()
    return bool(
        technical_query_terms(query)
        or _NUMERIC_OR_FORMULA.search(query)
        or re.search(
            r"\b(?:dimension|dimensions|parameter|parameters|hyperparameter|"
            r"hyperparameters|exact value|numeric value|number of heads|how many)\b",
            normalized,
        )
    )


def technical_match_count(query: str, text: str) -> int:
    requested = technical_query_terms(query)
    if not requested:
        return 0
    available = set(lexical_tokens(text))
    return len(requested & available)


def term_frequencies(text: str) -> Counter[str]:
    return Counter(lexical_tokens(text))
