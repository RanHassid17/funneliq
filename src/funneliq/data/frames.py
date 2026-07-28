"""The prepared campaign frame.

Lives here rather than in `models.train` so the serving path does not import the
training path. That was not a style preference: importing `models.train` pulls in
LightGBM and XGBoost, whose native libraries need OpenMP at import time, and the
first Railway deploy of the API crashed on `libgomp.so.1: cannot open shared
object file` for exactly that reason.

Serving needs the data and the saved models. It does not need the libraries that
produced them.
"""

from __future__ import annotations

import pandas as pd

from .load_to_supabase import prepare
from .metrics import add_derived_metrics
from .profile import load_raw


def load_campaign_frame() -> pd.DataFrame:
    """De-duplicated campaigns with derived metrics attached.

    Reads the committed CSV rather than Supabase: this is the modelling and
    simulation view of the whole dataset, which must be identical in training
    and at serving time. Live per-campaign reads go through `api.db`.
    """
    prepared, _ = prepare(load_raw())
    return add_derived_metrics(prepared)
