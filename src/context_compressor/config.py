from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    model_name: str = "cross-encoder/stsb-roberta-base"
    max_length: int = 256
    batch_size: int = 16
    threshold: float = 0.35
    top_k: int = 4
    max_context_tokens: int = 512
    device: str = "cpu"
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"


def get_runtime_config() -> RuntimeConfig:
    config = RuntimeConfig()
    if config.device == "cpu":
        return config
    return config
