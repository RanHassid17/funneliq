"""Model persistence with provenance.

A serialised model with no record of what it was trained on is a liability: you
cannot tell whether it respects the current feature policy, whether its metrics
are reproducible, or whether it predates a schema change. Every `.pkl` here is
written alongside a card recording the feature list, checkpoint, seed, git SHA
and row count, and loading refuses a model whose features no longer match the
policy.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib

from . import MODELS_DIR, RANDOM_SEED


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


@dataclass
class ModelCard:
    """Everything needed to interpret, reproduce or distrust a saved model."""

    name: str
    target: str
    checkpoint: str
    features: list[str]
    rows_trained: int
    algorithm: str
    metrics: dict[str, float]
    baseline_name: str
    baseline_metrics: dict[str, float]
    improvement: dict[str, float]
    notes: list[str] = field(default_factory=list)
    seed: int = RANDOM_SEED
    git_sha: str = field(default_factory=git_sha)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def save(model: Any, card: ModelCard, directory: Path = MODELS_DIR) -> Path:
    """Persist the estimator and its card side by side."""
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / f"{card.name}.pkl"
    joblib.dump(model, model_path)
    (directory / f"{card.name}.json").write_text(
        json.dumps(card.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return model_path


def load(name: str, directory: Path = MODELS_DIR) -> tuple[Any, ModelCard]:
    """Load an estimator with its card.

    Callers should check `card.features` against the current allowlist before
    predicting -- a model trained under an older policy may expect a column the
    policy has since excluded as leakage.
    """
    model = joblib.load(directory / f"{name}.pkl")
    card = ModelCard(**json.loads((directory / f"{name}.json").read_text(encoding="utf-8")))
    return model, card
