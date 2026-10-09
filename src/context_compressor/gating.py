"""Rule-based query-complexity analysis for adaptive context retention."""

from __future__ import annotations

import re
from dataclasses import dataclass


_COMPARATIVE_TERMS = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference|similarities|similarity|"
    r"better|worse|contrast|trade-?offs?)\b",
    re.IGNORECASE,
)
_MULTI_HOP_TERMS = re.compile(
    r"\b(and|then|because|therefore|how does .+ affect|relationship|"
    r"leads? to|results? in|depend(?:s|ing)? on|first|second|finally)\b",
    re.IGNORECASE,
)
_REASONING_QUESTION = re.compile(r"^\s*(why|how|explain|what would happen)\b", re.IGNORECASE)
_ENTITY_SPAN = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*|[A-Z]{2,})\b")
_QUERY_STARTER = re.compile(
    r"^\s*(?:compare|explain|describe|what|when|where|which|who|why|how|"
    r"is|does|do|can|could|would|should)\b\s*",
    re.IGNORECASE,
)
_NON_ENTITY_INITIALS = {
    "A", "An", "And", "Compare", "Does", "Explain", "How", "Is", "The",
    "This", "What", "When", "Where", "Which", "Who", "Why",
}


@dataclass(frozen=True, slots=True)
class QueryGateDecision:
    """Adaptive retention settings and interpretable query features."""

    complexity_score: float
    intent_type: str
    entity_count: int
    dynamic_threshold: float
    token_ratio_limit: float
    complexity_signals: tuple[str, ...] = ()


class QueryComplexityGater:
    """Estimate query complexity and derive bounded pruning parameters.

    The analyzer is intentionally lightweight and dependency-free. Its score is
    a transparent heuristic, not a calibrated probability or learned classifier.
    Higher complexity lowers the relevance cutoff and increases the permitted
    context ratio so that multi-step questions retain denser evidence.
    """

    MIN_THRESHOLD = 0.30
    MAX_THRESHOLD = 0.75
    MIN_TOKEN_RATIO = 0.20
    MAX_TOKEN_RATIO = 0.80

    def analyze(self, query: str) -> QueryGateDecision:
        """Analyze intent, named-entity-like spans, and reasoning structure."""
        text = query.strip()
        comparative = bool(_COMPARATIVE_TERMS.search(text))
        multi_hop_matches = list(_MULTI_HOP_TERMS.finditer(text))
        reasoning_question = bool(_REASONING_QUESTION.search(text))
        entity_count = self._count_entities(text)
        word_count = len(re.findall(r"\b[\w'-]+\b", text))

        score = 0.0
        signals: list[str] = []
        if comparative:
            score += 0.28
            signals.append("comparative_intent")
        if reasoning_question:
            score += 0.20
            signals.append("reasoning_question")
        if multi_hop_matches:
            score += min(0.28, 0.14 * len(multi_hop_matches))
            signals.append("logical_or_sequential_connective")
        if entity_count >= 2:
            score += min(0.14, 0.07 * (entity_count - 1))
            signals.append("multiple_entities")
        if word_count >= 14:
            score += 0.10
            signals.append("long_query")

        complexity = min(1.0, max(0.0, score))
        if comparative:
            intent = "comparative"
        elif multi_hop_matches:
            intent = "multi_hop"
        else:
            intent = "factual"

        threshold = self.MAX_THRESHOLD - (
            (self.MAX_THRESHOLD - self.MIN_THRESHOLD) * complexity
        )
        token_ratio = self.MIN_TOKEN_RATIO + (
            (self.MAX_TOKEN_RATIO - self.MIN_TOKEN_RATIO) * complexity
        )
        return QueryGateDecision(
            complexity_score=complexity,
            intent_type=intent,
            entity_count=entity_count,
            dynamic_threshold=min(self.MAX_THRESHOLD, max(self.MIN_THRESHOLD, threshold)),
            token_ratio_limit=min(self.MAX_TOKEN_RATIO, max(self.MIN_TOKEN_RATIO, token_ratio)),
            complexity_signals=tuple(signals),
        )

    @staticmethod
    def _count_entities(query: str) -> int:
        """Count distinct capitalized spans, excluding common sentence starters."""
        entity_text = _QUERY_STARTER.sub("", query, count=1)
        spans = {
            match.group(0).strip()
            for match in _ENTITY_SPAN.finditer(entity_text)
            if match.group(0).strip() not in _NON_ENTITY_INITIALS
        }
        return len(spans)
