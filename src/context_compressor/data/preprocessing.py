from __future__ import annotations

from typing import Any, Dict, Iterable, List


def build_synthetic_training_rows() -> List[Dict[str, Any]]:
    rows = [
        {
            "query": "What causes climate change?",
            "sentence": "Greenhouse gas emissions trap heat in the atmosphere and raise global temperatures.",
            "label": 1.0,
        },
        {
            "query": "What causes climate change?",
            "sentence": "The office cafeteria closes early on Wednesdays.",
            "label": 0.0,
        },
        {
            "query": "How does a neural network train?",
            "sentence": "Backpropagation adjusts model weights by propagating gradients from the loss function.",
            "label": 1.0,
        },
        {
            "query": "How does a neural network train?",
            "sentence": "This article explains the history of bicycles in Paris.",
            "label": 0.0,
        },
    ]
    return rows


def prepare_training_dataset(dataset_name: str = "synthetic") -> List[Dict[str, Any]]:
    """Prepare row-wise training data for relevance modeling.

    Production usage: replace this with an MS MARCO / NLI conversion pipeline
    and convert samples to a Hugging Face dataset instance.
    """
    if dataset_name.lower() in {"ms_marco", "marco", "msmarco"}:
        return build_synthetic_training_rows()
    return build_synthetic_training_rows()


def convert_to_hf_dataset(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]
