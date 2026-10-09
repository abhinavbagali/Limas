"""Lightweight discourse links that preserve antecedents during extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


_LEADING_REFERENCE = re.compile(
    r"^\s*(?:(?:however|therefore|thus|meanwhile|consequently|"
    r"as a result|in contrast|for this reason)\s*[,;:]?\s*)?"
    r"(?:it|they|them|their|he|him|his|she|her|hers|this|that|these|those|"
    r"this company|these results|those results)\b",
    re.IGNORECASE,
)
_LEADING_CONNECTIVE = re.compile(
    r"^\s*(however|therefore|thus|meanwhile|consequently|as a result|"
    r"in contrast|for this reason)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CoreferenceLink:
    """A local discourse edge from a sentence to its preceding antecedent."""

    antecedent_index: int
    dependent_index: int
    reason: str


class DiscoursePreserver:
    """Find conservative adjacent-sentence discourse dependencies.

    If spaCy and its English small model are available, dependency annotations
    are used to detect subject pronouns. The built-in regex rules remain the
    offline fallback and also recognize leading discourse connectives. spaCy's
    standard models do not provide general coreference resolution, so antecedents
    are deliberately limited to the immediately preceding sentence in the same
    input passage.
    """

    def __init__(self, use_spacy: bool = True) -> None:
        self._nlp = self._load_spacy_pipeline() if use_spacy else None

    @staticmethod
    def _load_spacy_pipeline():
        try:
            import spacy
        except ImportError:
            return None
        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            return None

    def find_links(
        self,
        sentences: Sequence[str],
        document_ids: Sequence[int],
    ) -> list[CoreferenceLink]:
        """Return adjacent antecedent links without crossing passage boundaries."""
        if len(sentences) != len(document_ids):
            raise ValueError("sentences and document_ids must have equal lengths.")
        dependency_reasons = self._dependency_reasons(sentences)
        links: list[CoreferenceLink] = []
        for index, sentence in enumerate(sentences):
            if index == 0 or document_ids[index] != document_ids[index - 1]:
                continue
            reason = dependency_reasons[index]
            if reason is None:
                if _LEADING_REFERENCE.search(sentence):
                    reason = "leading_reference"
                elif _LEADING_CONNECTIVE.search(sentence):
                    reason = "discourse_connective"
            if reason is not None:
                links.append(
                    CoreferenceLink(
                        antecedent_index=index - 1,
                        dependent_index=index,
                        reason=reason,
                    )
                )
        return links

    def _dependency_reasons(self, sentences: Sequence[str]) -> list[str | None]:
        """Parse eligible sentences through spaCy in one batch when available."""
        reasons: list[str | None] = [None] * len(sentences)
        if self._nlp is None:
            return reasons
        eligible_indices = [
            index
            for index, sentence in enumerate(sentences)
            if len(sentence) <= self._nlp.max_length
        ]
        parsed_sentences = self._nlp.pipe(sentences[index] for index in eligible_indices)
        for index, doc in zip(eligible_indices, parsed_sentences):
            if any(
                token.pos_ == "PRON" and token.dep_ in {"nsubj", "nsubjpass"}
                for token in doc
            ):
                reasons[index] = "subject_pronoun"
        return reasons

    @staticmethod
    def mandatory_antecedents(
        selected_indices: set[int],
        links: Sequence[CoreferenceLink],
    ) -> set[int]:
        """Close selected discourse dependents over all connected antecedents."""
        antecedents_by_dependent: dict[int, list[int]] = {}
        for link in links:
            antecedents_by_dependent.setdefault(link.dependent_index, []).append(
                link.antecedent_index
            )

        retained = set(selected_indices)
        pending = list(selected_indices)
        while pending:
            dependent = pending.pop()
            for antecedent in antecedents_by_dependent.get(dependent, ()):
                if antecedent not in retained:
                    retained.add(antecedent)
                    pending.append(antecedent)
        return retained
