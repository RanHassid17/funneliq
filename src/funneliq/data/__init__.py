"""Campaign data layer: loading, validation, profiling."""

from pathlib import Path

# Repo root, resolved from this file so scripts work from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = PROJECT_ROOT / "data" / "funnel_marketing_data.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

__all__ = ["DATA_PATH", "PROJECT_ROOT", "REPORTS_DIR"]
