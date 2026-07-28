"""Package 6: monthly ad-budget allocation simulator.

Northbound has ₪50,000 a month and currently spreads it evenly. This simulates
allocation strategies -- one big campaign, ten mid-size, many small -- using the
pre-launch profit model, and reports which maximises expected total profit.

The honesty constraint that shapes this module: **`ad_budget` in the training
data ranges ₪500-20,000 across 16 discrete values.** A single ₪50,000 campaign is
2.5x beyond anything ever observed. Tree ensembles cannot extrapolate -- they
return the value of the nearest leaf and present it with the same confidence as
an interpolation. So every scenario is labelled `in_distribution` or
`extrapolated`, and an extrapolated result is never allowed to be the headline.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from . import REPORTS_DIR
from .registry import load

MONTHLY_BUDGET = 50_000.0


@dataclass(frozen=True)
class Scenario:
    """One way of splitting the monthly budget."""

    label: str
    campaigns: int
    budget_per_campaign: float
    predicted_profit_per_campaign: float
    predicted_total_profit: float
    return_on_ad_spend: float
    in_distribution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def observed_budget_range(df: pd.DataFrame) -> tuple[float, float]:
    return float(df["ad_budget"].min()), float(df["ad_budget"].max())


def simulate(
    df: pd.DataFrame,
    monthly_budget: float = MONTHLY_BUDGET,
    splits: tuple[int, ...] = (1, 3, 5, 10, 17, 25, 33),
) -> list[Scenario]:
    """Predict total profit for each way of splitting `monthly_budget`.

    `splits` are campaign counts. The brief names 1, 10 and 33; the others fill
    in the curve so the optimum is visible rather than inferred from three points.
    """
    model, _ = load("cumulative_profit")
    low, high = observed_budget_range(df)

    scenarios: list[Scenario] = []
    for count in splits:
        per_campaign = monthly_budget / count
        predicted = float(model.predict(pd.DataFrame({"ad_budget": [per_campaign]}))[0])
        # A campaign cannot lose more than it spent in this data (profit >= 0),
        # so a negative prediction is a model artefact, not a forecast.
        predicted = max(predicted, 0.0)
        total = predicted * count
        scenarios.append(
            Scenario(
                label=f"{count} x {per_campaign:,.0f}",
                campaigns=count,
                budget_per_campaign=round(per_campaign, 2),
                predicted_profit_per_campaign=round(predicted, 2),
                predicted_total_profit=round(total, 2),
                return_on_ad_spend=round(total / monthly_budget, 4),
                in_distribution=low <= per_campaign <= high,
            )
        )
    return scenarios


def recommend(scenarios: list[Scenario]) -> dict[str, Any]:
    """Pick the best strategy, considering only scenarios the model can support.

    Extrapolated scenarios are reported but excluded from the recommendation. A
    prediction 2.5x outside the training range is not a weaker prediction; it is
    not a prediction at all.
    """
    supported = [s for s in scenarios if s.in_distribution]
    extrapolated = [s for s in scenarios if not s.in_distribution]
    best = max(supported, key=lambda s: s.predicted_total_profit)

    return {
        "monthly_budget": MONTHLY_BUDGET,
        "recommended": best.to_dict(),
        "scenarios": [s.to_dict() for s in scenarios],
        "excluded_as_extrapolation": [s.label for s in extrapolated],
        "caveats": [
            "ad_budget in training data spans 500-20,000 across 16 discrete values. "
            "Scenarios outside that range are flagged and excluded from the recommendation.",
            "The pre-launch model uses ad_budget alone, so this simulates the average "
            "campaign at each budget level, not a specific campaign.",
            "Assumes cumulative_profit is gross of ad spend (docs/OPEN_QUESTIONS.md Q6). "
            "If it is net, the ROAS figures are overstated.",
            "The mid-budget advantage may be an artefact of how this dataset was "
            "generated. Validate with a controlled split before committing real spend.",
        ],
    }


def main() -> None:
    from ..data.frames import load_campaign_frame

    df = load_campaign_frame()
    result = recommend(simulate(df))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "budget_simulation.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {output}")
    for scenario in result["scenarios"]:
        flag = "" if scenario["in_distribution"] else "  [EXTRAPOLATED]"
        print(
            f"  {scenario['label']:>16}  "
            f"total {scenario['predicted_total_profit']:>12,.0f}  "
            f"ROAS {scenario['return_on_ad_spend']:>5.2f}{flag}"
        )
    print(f"Recommended: {result['recommended']['label']}")


if __name__ == "__main__":
    main()
