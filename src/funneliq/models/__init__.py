"""Campaign models: LTV, upsell, referral score, profit, budget simulation.

Every model here predicts a property of a CAMPAIGN. None of them says anything
about an individual customer, and the 0-100 referral score in particular is a
campaign-level likelihood, not a person's probability of referring.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_ROOT / "models"
REPORTS_DIR = PROJECT_ROOT / "reports"

#: Fixed everywhere so two runs of the same code produce the same numbers.
RANDOM_SEED = 42

__all__ = ["MODELS_DIR", "PROJECT_ROOT", "RANDOM_SEED", "REPORTS_DIR"]
