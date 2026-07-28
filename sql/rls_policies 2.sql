-- Row Level Security for public.campaigns.
--
-- The brief's requirement: "enable Row Level Security and write policies so the
-- database itself enforces that only authenticated users can read the data."
--
-- The property this buys us: even if the anon key leaks out of the browser --
-- and it is a public key, so assume it will -- an attacker still cannot read a
-- single campaign row without a valid signed-in session. Access control lives in
-- the database, not only in the API layer that happens to sit in front of it.
--
-- Run AFTER sql/schema.sql. Idempotent: safe to re-run.

alter table public.campaigns enable row level security;

-- Belt and braces. RLS with no matching policy already denies everything, but
-- revoking the grant means an accidental permissive policy later cannot silently
-- open anonymous access.
revoke all on public.campaigns from anon;

grant select on public.campaigns to authenticated;

drop policy if exists "Authenticated users can read campaigns" on public.campaigns;
create policy "Authenticated users can read campaigns"
    on public.campaigns
    for select
    to authenticated
    using (true);

-- No insert, update or delete policy exists for any client role, so writes are
-- refused for both anon and authenticated. Loading is done server-side with the
-- service-role key, which bypasses RLS by design. That key must never reach a
-- browser.
--
-- Verify after applying:
--   1. With the anon key and no session:  select should return zero rows / be denied.
--   2. With a signed-in user's JWT:       select should return all campaigns.
--   3. With a signed-in user's JWT:       insert should be refused.
