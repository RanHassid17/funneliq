"""Request and response models.

Campaign inputs are validated with real bounds rather than accepted blindly. A
negative budget or a follow-up count exceeding the leads that answered is not a
prediction problem -- it is a bad request, and saying so is more useful than
returning a confident number derived from impossible input.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class CampaignInput(BaseModel):
    """Campaign facts known after follow-up 2 (checkpoint C2).

    This is the widest input any served model needs. The LTV and profit models
    use only `ad_budget`; the feature policy decides what each one actually
    reads, so a caller supplying extra fields does not thereby leak them into a
    model.
    """

    ad_budget: float = Field(gt=0, le=1_000_000, description="Campaign spend in shekels")
    num_leads: int = Field(default=0, ge=0, le=10_000)
    leads_answered: int = Field(default=0, ge=0, le=10_000)
    leads_not_answered: int = Field(default=0, ge=0, le=10_000)
    followup_1: int = Field(default=0, ge=0, le=10_000)
    followup_2: int = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def check_funnel_is_possible(self) -> CampaignInput:
        if self.leads_answered > self.num_leads:
            raise ValueError("leads_answered cannot exceed num_leads")
        if self.followup_1 > self.leads_answered:
            raise ValueError("followup_1 cannot exceed leads_answered")
        if self.followup_2 > self.followup_1:
            raise ValueError("followup_2 cannot exceed followup_1")
        return self

    def to_features(self) -> dict[str, float]:
        """Raw fields for the feature builder.

        `followup_3..5`, `closed` and the economics columns are set to zero
        because no served model is allowed to read them -- they sit past every
        served checkpoint. They exist only so `add_derived_metrics` can run the
        same code it ran in training.
        """
        return {
            **self.model_dump(),
            "followup_3": 0,
            "followup_4": 0,
            "followup_5": 0,
            "closed": 0,
            "not_closed": 0,
            "cumulative_profit": 0.0,
        }


class BudgetSimulationInput(BaseModel):
    monthly_budget: float = Field(default=50_000, gt=0, le=10_000_000)
    splits: list[int] = Field(
        default=[1, 3, 5, 10, 17, 25, 33],
        min_length=1,
        max_length=20,
        description="Campaign counts to simulate",
    )

    @model_validator(mode="after")
    def check_splits(self) -> BudgetSimulationInput:
        if any(s < 1 for s in self.splits):
            raise ValueError("every split must be at least 1 campaign")
        return self


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    """Readiness is distinct from liveness.

    `/health` answers "is this process alive" and must not depend on Supabase --
    otherwise a brief database blip restarts a process that was never broken.
    `/ready` answers "can this instance actually serve requests", which does
    require the database and the model artifacts.
    """

    ready: bool
    configured: bool
    database: dict[str, Any]
    models: dict[str, Any]
