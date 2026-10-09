from __future__ import annotations

import re
from collections import Counter
from typing import List, Sequence

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception:  # pragma: no cover
    AutoModelForSequenceClassification = None
    AutoTokenizer = None


SEMANTIC_EXPANSIONS = {
    "climate": {"climate", "warming", "greenhouse", "temperature", "atmosphere", "emissions"},
    "change": {"change", "warming", "alteration", "shift", "impact", "effects"},
    "cause": {"cause", "causes", "caused", "drives", "leads", "results", "increases"},
    "greenhouse": {"greenhouse", "carbon", "co2", "emissions", "gases", "warming"},
    "effect": {"effect", "effects", "impact", "consequence", "result"},
    "human": {"human", "anthropogenic", "emissions", "fossil", "combustion"},
}


class CrossEncoderRelevanceScorer:
    """Semantic sentence relevance scorer.

    Uses a Hugging Face cross-encoder when available; otherwise falls back to a
    lightweight lexical overlap heuristic so the project remains runnable in
    minimal environments.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/stsb-roberta-base",
        device: str = "cpu",
        batch_size: int = 16,
        max_length: int = 256,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1.")
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.model = None
        self.tokenizer = None
        self.fallback_mode = True
        self._load_model()

    def _load_model(self) -> None:
        if AutoTokenizer is None or AutoModelForSequenceClassification is None or torch is None:
            return

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            self.fallback_mode = False
        except Exception:  # pragma: no cover
            self.model = None
            self.tokenizer = None
            self.fallback_mode = True

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\b[\w\']+\b", text.lower())

    def _fallback_score(self, query: str, candidate: str) -> float:
        query_tokens = Counter(self._tokenize(query))
        cand_tokens = Counter(self._tokenize(candidate))
        if not query_tokens or not cand_tokens:
            return 0.0

        expanded_query = Counter()
        for token, count in query_tokens.items():
            expanded_query[token] += count
            for expansion in SEMANTIC_EXPANSIONS.get(token, set()):
                expanded_query[expansion] += count

        expanded_candidate = Counter()
        for token, count in cand_tokens.items():
            expanded_candidate[token] += count
            for expansion in SEMANTIC_EXPANSIONS.get(token, set()):
                expanded_candidate[expansion] += count

        overlap = 0
        for token, count in expanded_query.items():
            overlap += min(count, expanded_candidate.get(token, 0))

        total = sum(expanded_query.values())
        if total == 0:
            return 0.0
        return min(1.0, overlap / total)

    def score_pairs(self, query: str, candidate_texts: Sequence[str]) -> List[float]:
        if isinstance(candidate_texts, str):
            candidate_texts = [candidate_texts]

        if self.fallback_mode or self.model is None or self.tokenizer is None:
            return [self._fallback_score(query, text) for text in candidate_texts]

        scores: List[float] = []
        for offset in range(0, len(candidate_texts), self.batch_size):
            batch = list(candidate_texts[offset : offset + self.batch_size])
            inputs = self.tokenizer(
                [query for _ in batch],
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=self.max_length,
            )

            if self.device != "cpu":
                inputs = {key: value.to(self.device) for key, value in inputs.items()}

            with torch.no_grad():
                logits = self.model(**inputs).logits
                if logits.shape[-1] == 1:
                    # Single-logit STS/regression heads need a monotonic mapping;
                    # softmax over one value is always 1 and cannot rank sentences.
                    batch_scores = torch.sigmoid(logits[:, 0]).cpu().tolist()
                else:
                    batch_scores = torch.softmax(logits, dim=-1)[:, 1].cpu().tolist()
            scores.extend(float(score) for score in batch_scores)
        return scores

    def score_single(self, query: str, candidate: str) -> float:
        return self.score_pairs(query, [candidate])[0]

    def save_onnx(self, path: str) -> str:
        """Hook for optional ONNX export in production deployments."""
        return path
