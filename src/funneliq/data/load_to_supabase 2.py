"""Repeatable load of the campaign CSV into Supabase Postgres.

The brief requires loading "with a repeatable script -- not by hand". Repeatable
here means genuinely idempotent: running it twice leaves the table in the same
state as running it once, because rows are upserted on a deterministic
`campaign_id` rather than appended.

Uses the SERVICE-ROLE key, which bypasses Row Level Security by design. That is
correct for a server-side loader and catastrophic anywhere near a browser. The
key is read from the environment and never logged.

Run:  python -m funneliq.data.load_to_supabase --dry-run   # validate, write nothing
      python -m funneliq.data.load_to_supabase             # load
"""

from __future__ import annotations

import argparse
import math
import os
from typing import Any

import pandas as pd

from . import REPORTS_DIR
from .invariants import evaluate, write_report
from .profile import load_raw

#: Source columns as delivered. Used for duplicate detection, so that the
#: synthesised campaign_id (which is unique by construction) cannot mask a row
#: that is otherwise an exact copy.
SOURCE_COLUMNS: list[str] = [
    "ad_budget",
    "num_leads",
    "leads_answered",
    "leads_not_answered",
    "followup_1",
    "followup_2",
    "followup_3",
    "followup_4",
    "followup_5",
    "not_closed",
    "closed",
    "calls_to_closed",
    "calls_to_not_closed",
    "customer_acquisition_cost",
    "ltv_months",
    "purchased",
    "upsell",
    "cumulative_profit",
    "referred",
]

BATCH_SIZE = 500


def assign_campaign_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Give every row a stable key derived from its position in the source file.

    Assigned BEFORE de-duplication so that an id always refers to the same source
    line. If dedup logic ever changes, previously loaded ids keep their meaning
    instead of silently shifting to a different campaign.
    """
    return df.assign(campaign_id=[f"CMP-{i:05d}" for i in range(len(df))])


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce the source's mixed conventions into the schema's types.

    `referred` arrives as the text Yes/No; `purchased` and `upsell` as 1/0. The
    database stores all three as booleans so that no downstream consumer has to
    remember which convention applied to which column.
    """
    return df.assign(
        referred=df["referred"].map({"Yes": True, "No": False}),
        purchased=df["purchased"].astype(bool),
        upsell=df["upsell"].astype(bool),
    )


def prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean, validate and flag. Returns the loadable frame plus a summary."""
    with_ids = assign_campaign_ids(df)

    duplicate_mask = with_ids.duplicated(subset=SOURCE_COLUMNS, keep="first")
    deduped = with_ids[~duplicate_mask].copy()

    report = evaluate(deduped)
    prepared = normalise(deduped)
    prepared["data_quality_flags"] = report.flags
    # Declared in the schema for forward compatibility; the source has no dates.
    prepared["campaign_start_date"] = None
    prepared["campaign_end_date"] = None

    summary = {
        "source_rows": int(len(df)),
        "exact_duplicates_dropped": int(duplicate_mask.sum()),
        "rows_to_load": int(len(prepared)),
        "invariants": report.to_dict(),
    }
    return prepared, summary


def to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert to JSON-safe records.

    NaN becomes None, not 0. Missing lifetime or profit means "we do not know",
    and zero-filling it would quietly corrupt every average computed downstream.
    """
    records = df.to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                record[key] = None
    return records


def _client():  # pragma: no cover - requires live credentials
    """Build a Supabase client from the environment.

    Imported lazily so that --dry-run, the tests, and CI do not need the
    supabase package configured or any credentials present.
    """
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
            "Copy .env.example to .env and fill them in."
        )
    return create_client(url, key)


def upload(records: list[dict[str, Any]]) -> int:  # pragma: no cover - network
    """Upsert in batches, returning the number of rows written."""
    client = _client()
    written = 0
    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        client.table("campaigns").upsert(batch, on_conflict="campaign_id").execute()
        written += len(batch)
        print(f"  upserted {written}/{len(records)}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and write reports/invariants.json without touching Supabase",
    )
    args = parser.parse_args()

    prepared, summary = prepare(load_raw())

    report_path = REPORTS_DIR / "invariants.json"
    write_report(evaluate(prepared), report_path)
    print(f"Wrote {report_path}")

    print(
        f"source rows: {summary['source_rows']}, "
        f"duplicates dropped: {summary['exact_duplicates_dropped']}, "
        f"to load: {summary['rows_to_load']}"
    )
    for result in summary["invariants"]["invariants"]:
        status = "ok" if result["passed"] else f"{result['violations']} violations"
        print(f"  {result['name']}: {status}")

    if args.dry_run:
        print("Dry run: nothing written to Supabase.")
        return

    written = upload(to_records(prepared))
    print(f"Upserted {written} campaigns.")


if __name__ == "__main__":
    main()
