from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Sequence

from ..config import RuntimeConfig
from ..coreference import CoreferenceLink, DiscoursePreserver
from ..gating import QueryComplexityGater, QueryGateDecision
from ..models.cross_encoder import CrossEncoderRelevanceScorer
from ..scorer import BatchedScorer, MultiHopInterdependenceScorer, SingleScorer
from ..types import CompressedDocument, SentenceAudit, SentenceItem
from .sentence_splitter import split_document_into_sentences


def estimate_word_count(text: str) -> int:
    """Count regex word-like units; this is not an LLM tokenizer count."""
    return len(re.findall(r"\b\w+\b", text.lower())) if text else 0


class ContextCompressor:
    """Score, select, and discourse-preserve relevant passage sentences."""

    def __init__(
        self,
        scorer: BatchedScorer | SingleScorer | CrossEncoderRelevanceScorer | None = None,
        config: RuntimeConfig | None = None,
        discourse_preserver: DiscoursePreserver | None = None,
        complexity_gater: QueryComplexityGater | None = None,
        pairwise_alpha: float = 0.70,
    ) -> None:
        self.config = config or RuntimeConfig()
        self.scorer = scorer or CrossEncoderRelevanceScorer(
            model_name=self.config.model_name,
            device=self.config.device,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
        )
        self.multi_hop_scorer = MultiHopInterdependenceScorer(
            self.scorer,
            alpha=pairwise_alpha,
        )
        self.discourse_preserver = discourse_preserver or DiscoursePreserver()
        self.complexity_gater = complexity_gater or QueryComplexityGater()

    def compress(
        self,
        query: str,
        documents: Sequence[str] | str,
        threshold: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        enable_coref: bool = True,
        enable_multihop: bool = True,
        adaptive_gating: bool = True,
    ) -> CompressedDocument:
        """Compress text and return selection, complexity, and overhead metadata.

        ``estimated_*_word_count`` and ``compression_ratio`` use a regex word
        counter. Actual provider token counts are only available after an LLM
        request, so this method never presents the local estimate as exact tokens.
        An explicit ``threshold`` overrides adaptive thresholding; an explicit
        ``max_tokens`` remains a hard upper bound on the adaptive word budget.
        """
        if isinstance(documents, str):
            documents = [documents]
        passages = list(documents)
        gate = self.complexity_gater.analyze(query)

        candidates: list[SentenceItem] = []
        candidate_texts: list[str] = []
        document_ids: list[int] = []
        for document_index, document in enumerate(passages):
            for sentence in split_document_into_sentences(document):
                sentence_index = len(candidates)
                candidates.append(
                    SentenceItem(
                        index=sentence_index,
                        sentence=sentence,
                        score=0.0,
                    )
                )
                candidate_texts.append(sentence)
                document_ids.append(document_index)

        if not query.strip() or not candidates:
            audit = [
                SentenceAudit(
                    sentence_index=item.index,
                    text=item.sentence,
                    isolated_score=0.0,
                    pairwise_gain=0.0,
                    final_weight=0.0,
                    retained=False,
                    atomic_group_id=None,
                    discard_reason="No non-empty query was provided.",
                )
                for item in candidates
            ]
            return self._empty_result(
                gate,
                threshold,
                adaptive_gating,
                self.config.threshold,
                audit,
            )

        scoring = self.multi_hop_scorer.score(
            query=query,
            sentences=candidate_texts,
            document_ids=document_ids,
            enabled=enable_multihop,
        )
        for candidate, score in zip(candidates, scoring.weights):
            candidate.score = score

        active_threshold = (
            threshold
            if threshold is not None
            else gate.dynamic_threshold
            if adaptive_gating
            else self.config.threshold
        )
        active_top_k = self.config.top_k if top_k is None else top_k
        max_context_words = self.config.max_context_tokens if max_tokens is None else max_tokens
        original_text = " ".join(passages)
        estimated_original_word_count = estimate_word_count(original_text)
        if adaptive_gating and estimated_original_word_count:
            adaptive_word_budget = max(
                1,
                round(estimated_original_word_count * gate.token_ratio_limit),
            )
            max_context_words = min(max_context_words, adaptive_word_budget)

        threshold_candidates = [
            item for item in candidates if item.score >= active_threshold
        ]
        used_fallback = not threshold_candidates
        eligible_selection = threshold_candidates
        if used_fallback:
            eligible_selection = sorted(
                candidates,
                key=lambda item: (-item.score, item.index),
            )
        initial_selection = sorted(eligible_selection, key=lambda item: item.index)[
            :active_top_k
        ]
        initial_indices = {item.index for item in initial_selection}
        eligible_indices = {item.index for item in eligible_selection}

        links: list[CoreferenceLink] = []
        coreference_latency_ms = 0.0
        if enable_coref:
            coreference_start = time.perf_counter()
            links = self.discourse_preserver.find_links(candidate_texts, document_ids)
            coreference_latency_ms = (time.perf_counter() - coreference_start) * 1000.0

        dependency_links = links + [
            CoreferenceLink(
                antecedent_index=antecedent,
                dependent_index=dependent,
                reason="pairwise_interdependence",
            )
            for antecedent, dependent in scoring.pair_dependencies
        ]
        retained_indices = (
            self.discourse_preserver.mandatory_antecedents(
                initial_indices,
                dependency_links,
            )
            if dependency_links
            else set(initial_indices)
        )
        dependency_candidate_indices = set(retained_indices)
        retained_indices = self._apply_word_budget(
            retained_indices=retained_indices,
            candidates=candidates,
            links=dependency_links,
            max_context_words=max_context_words,
        )
        selected = [item for item in candidates if item.index in retained_indices]
        combined = " ".join(item.sentence for item in selected)
        estimated_compressed_word_count = estimate_word_count(combined)
        estimated_reduction = 0.0
        compression_ratio = 0.0
        if estimated_original_word_count:
            estimated_reduction = max(
                0.0,
                (estimated_original_word_count - estimated_compressed_word_count)
                / estimated_original_word_count
                * 100.0,
            )
            compression_ratio = max(
                0.0,
                min(
                    1.0,
                    (estimated_original_word_count - estimated_compressed_word_count)
                    / estimated_original_word_count,
                ),
            )

        retained_coreferences = {
            (link.antecedent_index, link.dependent_index)
            for link in links
            if link.dependent_index in retained_indices
            and link.antecedent_index in retained_indices
        }
        atomic_parent = {index: index for index in retained_indices}

        def find_atomic_root(index: int) -> int:
            while atomic_parent[index] != index:
                atomic_parent[index] = atomic_parent[atomic_parent[index]]
                index = atomic_parent[index]
            return index

        for link in dependency_links:
            if link.antecedent_index in atomic_parent and link.dependent_index in atomic_parent:
                antecedent_root = find_atomic_root(link.antecedent_index)
                dependent_root = find_atomic_root(link.dependent_index)
                if antecedent_root != dependent_root:
                    atomic_parent[dependent_root] = antecedent_root
        roots = sorted(
            {find_atomic_root(index) for index in retained_indices},
            key=lambda root: min(
                index for index in retained_indices if find_atomic_root(index) == root
            ),
        )
        group_ids = {root: group_id for group_id, root in enumerate(roots, start=1)}
        atomic_group_ids = {
            index: group_ids[find_atomic_root(index)] for index in retained_indices
        }

        audit: list[SentenceAudit] = []
        for item in candidates:
            sentence_index = item.index
            retained = sentence_index in retained_indices
            retention_reason = None
            discard_reason = None
            if retained:
                if sentence_index in initial_indices:
                    if used_fallback:
                        retention_reason = (
                            "Selected as a top-ranked fallback because no sentence "
                            "passed the threshold."
                        )
                    else:
                        retention_reason = (
                            f"Passes threshold τ={active_threshold:.2f} and top-K selection."
                        )
                else:
                    preserving_link = next(
                        (
                            link
                            for link in dependency_links
                            if sentence_index in {link.antecedent_index, link.dependent_index}
                            and link.antecedent_index in retained_indices
                            and link.dependent_index in retained_indices
                        ),
                        None,
                    )
                    if preserving_link is None:
                        retention_reason = "Retained with a selected atomic dependency group."
                    else:
                        relation = preserving_link.reason.replace("_", " ")
                        if preserving_link.antecedent_index == sentence_index:
                            retention_reason = (
                                f"Retained as antecedent for sentence "
                                f"{preserving_link.dependent_index + 1} "
                                f"({relation} dependency)."
                            )
                        else:
                            retention_reason = (
                                f"Retained to preserve {relation} dependency with "
                                f"antecedent sentence "
                                f"{preserving_link.antecedent_index + 1}."
                            )
            elif sentence_index in dependency_candidate_indices:
                discard_reason = (
                    "Excluded by the estimated word-budget cap; its atomic dependency "
                    "group did not fit."
                )
            elif used_fallback:
                discard_reason = "Not selected within the top-K fallback selection."
            elif sentence_index in eligible_indices:
                discard_reason = "Passed threshold but fell outside the top-K selection."
            else:
                discard_reason = f"Below threshold τ={active_threshold:.2f}."
            audit.append(
                SentenceAudit(
                    sentence_index=sentence_index,
                    text=item.sentence,
                    isolated_score=scoring.isolated_weights[sentence_index],
                    pairwise_gain=scoring.pairwise_gains[sentence_index],
                    final_weight=item.score,
                    retained=retained,
                    atomic_group_id=(
                        atomic_group_ids[sentence_index] if retained else None
                    ),
                    retention_reason=retention_reason,
                    discard_reason=discard_reason,
                )
            )
        return CompressedDocument(
            selected_sentences=[item.sentence for item in selected],
            scores=[item.score for item in selected],
            estimated_original_word_count=estimated_original_word_count,
            estimated_compressed_word_count=estimated_compressed_word_count,
            estimated_word_reduction_percent=estimated_reduction,
            compressed_text=combined,
            compression_ratio=compression_ratio,
            query_complexity_score=gate.complexity_score,
            query_intent_type=gate.intent_type,
            query_entity_count=gate.entity_count,
            complexity_signals=list(gate.complexity_signals),
            dynamic_threshold_used=active_threshold,
            dynamic_token_ratio_limit=(
                gate.token_ratio_limit if adaptive_gating else None
            ),
            sentence_audit=audit,
            preserved_coreferences_count=len(retained_coreferences),
            retained_sentence_indices=sorted(retained_indices),
            isolated_scoring_latency_ms=scoring.isolated_latency_ms,
            pairwise_scoring_latency_ms=scoring.pairwise_latency_ms,
            coreference_analysis_latency_ms=coreference_latency_ms,
        )

    def _apply_word_budget(
        self,
        retained_indices: set[int],
        candidates: Sequence[SentenceItem],
        links: Sequence[CoreferenceLink],
        max_context_words: int,
    ) -> set[int]:
        """Prune whole discourse-linked groups, never splitting an antecedent pair."""
        if not retained_indices:
            return set()
        candidate_by_index = {item.index: item for item in candidates}
        parent = {index: index for index in retained_indices}

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for link in links:
            if link.antecedent_index in parent and link.dependent_index in parent:
                antecedent_root = find(link.antecedent_index)
                dependent_root = find(link.dependent_index)
                if antecedent_root != dependent_root:
                    parent[dependent_root] = antecedent_root

        groups: dict[int, list[int]] = defaultdict(list)
        for index in retained_indices:
            groups[find(index)].append(index)
        ranked_groups = sorted(
            groups.values(),
            key=lambda indices: (
                -max(candidate_by_index[index].score for index in indices),
                min(indices),
            ),
        )

        retained: set[int] = set()
        used_words = 0
        for group in ranked_groups:
            group_words = sum(
                estimate_word_count(candidate_by_index[index].sentence)
                for index in group
            )
            if used_words + group_words <= max_context_words or not retained:
                retained.update(group)
                used_words += group_words
        return retained

    @staticmethod
    def _empty_result(
        gate: QueryGateDecision,
        threshold: float | None,
        adaptive_gating: bool,
        configured_threshold: float,
        sentence_audit: list[SentenceAudit],
    ) -> CompressedDocument:
        return CompressedDocument(
            query_complexity_score=gate.complexity_score,
            query_intent_type=gate.intent_type,
            query_entity_count=gate.entity_count,
            complexity_signals=list(gate.complexity_signals),
            dynamic_threshold_used=(
                threshold
                if threshold is not None
                else gate.dynamic_threshold
                if adaptive_gating
                else configured_threshold
            ),
            dynamic_token_ratio_limit=(
                gate.token_ratio_limit if adaptive_gating else None
            ),
            sentence_audit=sentence_audit,
        )
