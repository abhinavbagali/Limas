"""Two-stage isolated and adjacent-pair relevance scoring."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .models.cross_encoder import CrossEncoderRelevanceScorer


class BatchedScorer(Protocol):
    def score_pairs(self, query: str, candidate_texts: Sequence[str]) -> list[float]: ...


class SingleScorer(Protocol):
    def score_single(self, query: str, candidate: str) -> float: ...


@dataclass(frozen=True, slots=True)
class MultiHopScoreResult:
    """Final and component relevance scores plus inference timings."""

    weights: list[float]
    isolated_latency_ms: float
    pairwise_latency_ms: float
    pair_dependencies: list[tuple[int, int]]
    isolated_weights: list[float]
    pairwise_gains: list[float]


class MultiHopInterdependenceScorer:
    """Batch isolated sentence scores and conditional contiguous-pair gains."""

    def __init__(
        self,
        scorer: BatchedScorer | SingleScorer | CrossEncoderRelevanceScorer,
        alpha: float = 0.70,
        pair_candidate_floor: float = 0.10,
    ) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be between 0 and 1.")
        if not 0.0 <= pair_candidate_floor <= 1.0:
            raise ValueError("pair_candidate_floor must be between 0 and 1.")
        self.scorer = scorer
        self.alpha = alpha
        self.pair_candidate_floor = pair_candidate_floor

    def score(
        self,
        query: str,
        sentences: Sequence[str],
        document_ids: Sequence[int],
        enabled: bool = True,
    ) -> MultiHopScoreResult:
        """Score every sentence, then add positive relevance gain from its predecessor."""
        if len(sentences) != len(document_ids):
            raise ValueError("sentences and document_ids must have equal lengths.")
        if not sentences:
            return MultiHopScoreResult([], 0.0, 0.0, [], [], [])

        isolated_start = time.perf_counter()
        isolated = self._score_pairs(query, sentences)
        isolated_latency = (time.perf_counter() - isolated_start) * 1000.0
        if len(isolated) != len(sentences):
            raise ValueError("Scorer returned a different number of isolated scores than inputs.")
        weights = [self._bound(score) for score in isolated]
        if not enabled or len(sentences) < 2 or self.alpha == 1.0:
            return MultiHopScoreResult(
                weights,
                isolated_latency,
                0.0,
                [],
                weights.copy(),
                [0.0] * len(sentences),
            )

        pairs: list[tuple[int, int]] = []
        pair_texts: list[str] = []
        for current in range(1, len(sentences)):
            previous = current - 1
            if document_ids[previous] != document_ids[current]:
                continue
            if max(isolated[previous], isolated[current]) < self.pair_candidate_floor:
                continue
            pairs.append((previous, current))
            pair_texts.append(f"{sentences[previous]} {sentences[current]}")

        if not pair_texts:
            return MultiHopScoreResult(
                weights,
                isolated_latency,
                0.0,
                [],
                weights.copy(),
                [0.0] * len(sentences),
            )

        pairwise_start = time.perf_counter()
        joint_scores = self._score_pairs(query, pair_texts)
        pairwise_latency = (time.perf_counter() - pairwise_start) * 1000.0
        if len(joint_scores) != len(pairs):
            raise ValueError("Scorer returned a different number of pairwise scores than inputs.")

        gains = [0.0] * len(sentences)
        pair_dependencies: list[tuple[int, int]] = []
        for (previous, current), joint_score in zip(pairs, joint_scores):
            joint_score = self._bound(joint_score)
            gains[current] = self._bound(max(0.0, joint_score - isolated[previous]))
            if joint_score > max(isolated[previous], isolated[current]) + 0.05:
                pair_dependencies.append((previous, current))
        for index, gain in enumerate(gains):
            if index and document_ids[index - 1] == document_ids[index]:
                weights[index] = self._bound(
                    self.alpha * isolated[index] + (1.0 - self.alpha) * gain
                )
        return MultiHopScoreResult(
            weights=weights,
            isolated_latency_ms=isolated_latency,
            pairwise_latency_ms=pairwise_latency,
            pair_dependencies=pair_dependencies,
            isolated_weights=[self._bound(score) for score in isolated],
            pairwise_gains=gains,
        )

    @staticmethod
    def _bound(score: float) -> float:
        return min(1.0, max(0.0, float(score)))

    def _score_pairs(self, query: str, texts: Sequence[str]) -> list[float]:
        """Use batched scoring when available; support legacy score_single scorers."""
        score_pairs = getattr(self.scorer, "score_pairs", None)
        if callable(score_pairs):
            return list(score_pairs(query, texts))
        score_single = getattr(self.scorer, "score_single", None)
        if not callable(score_single):
            raise TypeError("Scorer must define score_pairs() or score_single().")
        return [float(score_single(query, text)) for text in texts]
