-- FunnelIQ campaign table.
--
-- The unit of analysis is ONE ADVERTISING CAMPAIGN, never one customer. Column
-- comments below restate that per field, because the single most likely way for
-- this project to go wrong is someone reading `ltv_months` as one person's
-- tenure rather than the average tenure of the customers a campaign produced.
--
-- Run in the Supabase SQL editor, or via `psql < sql/schema.sql`.
-- Idempotent: safe to re-run.

create table if not exists public.campaigns (
    -- The source CSV has no key. `campaign_id` is synthesised deterministically
    -- from the original row index at load time (CMP-00000, CMP-00001, ...) so
    -- that re-running the loader upserts rather than duplicates.
    campaign_id text primary key,

    -- Declared but always null: the source data carries no dates. Present so the
    -- schema is forward-compatible with the Dataset Explainer's recommended
    -- shape, and so time-based validation can be added without a migration.
    campaign_start_date date,
    campaign_end_date   date,

    -- Campaign investment ------------------------------------------------
    ad_budget numeric not null check (ad_budget >= 0),

    -- Lead volume and response -------------------------------------------
    num_leads          integer not null check (num_leads >= 0),
    leads_answered     integer not null check (leads_answered >= 0),
    leads_not_answered integer not null check (leads_not_answered >= 0),

    -- Follow-up survival: leads still engaged after each round ------------
    followup_1 integer not null check (followup_1 >= 0),
    followup_2 integer not null check (followup_2 >= 0),
    followup_3 integer not null check (followup_3 >= 0),
    followup_4 integer not null check (followup_4 >= 0),
    followup_5 integer not null check (followup_5 >= 0),

    -- Sales outcomes ------------------------------------------------------
    not_closed integer not null check (not_closed >= 0),
    closed     integer not null check (closed >= 0),

    -- Call effort ---------------------------------------------------------
    calls_to_closed     numeric not null check (calls_to_closed >= 0),
    calls_to_not_closed numeric not null check (calls_to_not_closed >= 0),

    -- Economics -----------------------------------------------------------
    customer_acquisition_cost numeric not null check (customer_acquisition_cost >= 0),

    -- Nullable on purpose. Missing lifetime and profit are NOT zero-filled:
    -- a campaign with unknown profit is a different thing from one that earned
    -- nothing, and conflating them would corrupt every downstream average.
    ltv_months        numeric check (ltv_months >= 0),
    cumulative_profit numeric check (cumulative_profit >= 0),

    -- Campaign outcomes ---------------------------------------------------
    purchased boolean not null,
    upsell    boolean not null,
    referred  boolean not null,

    -- Populated by src/funneliq/data/invariants.py. A row that fails a
    -- structural check is flagged and kept, not silently dropped, so the
    -- problem stays visible in the database rather than only in a script.
    data_quality_flags text[] not null default '{}',

    loaded_at timestamptz not null default now()
);

-- Budget drives the tier analysis (Low <= 1500, Mid 2000-5000, High > 5000) and
-- the budget simulator, so it is the one column worth an index at this size.
create index if not exists campaigns_ad_budget_idx on public.campaigns (ad_budget);

-- Lets the dashboard surface problem campaigns without a full scan.
create index if not exists campaigns_quality_flags_idx
    on public.campaigns using gin (data_quality_flags);

comment on table public.campaigns is
    'One row per advertising campaign or campaign period. NOT one row per customer.';

comment on column public.campaigns.ad_budget is
    'Total advertising spend assigned to the campaign, in shekels.';
comment on column public.campaigns.num_leads is
    'Total leads the campaign generated. Normally equals answered + not answered.';
comment on column public.campaigns.followup_1 is
    'Leads still engaged after follow-up round 1. Denominator is leads_answered.';
comment on column public.campaigns.closed is
    'Deals closed by the campaign. closed + not_closed equals followup_5 in all source rows.';
comment on column public.campaigns.calls_to_closed is
    'Call effort for closed outcomes. Assumed to be an average per outcome; unconfirmed.';
comment on column public.campaigns.customer_acquisition_cost is
    'Equals floor(ad_budget / closed) in all source rows, so it encodes the sales '
    'outcome and must not be used as a feature before that outcome is known.';
comment on column public.campaigns.ltv_months is
    'AVERAGE lifetime in months of the customers this campaign produced. Not one persons tenure.';
comment on column public.campaigns.cumulative_profit is
    'TOTAL profit attributed to the campaign. Gross of ad spend (assumed, unconfirmed).';
comment on column public.campaigns.purchased is
    'True exactly when cumulative_profit > 0 in the source data, i.e. the campaign earned revenue.';
comment on column public.campaigns.upsell is
    'Campaign produced at least one upsell (assumed definition, unconfirmed).';
comment on column public.campaigns.referred is
    'Campaign produced at least one referral (assumed definition, unconfirmed). '
    'Normalised from the source Yes/No text.';
comment on column public.campaigns.data_quality_flags is
    'Structural check failures for this row. Empty array means all invariants held.';
