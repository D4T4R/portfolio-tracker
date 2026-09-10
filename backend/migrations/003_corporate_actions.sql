-- Splits and bonus issues.
--
-- A split changes the share count without changing what the holding is worth.
-- Left unrecorded, the ledger keeps the old count while the market quotes the
-- new price, and the position reads as a collapse that never happened: a
-- 5-for-1 looks like an 80% loss. Three of these had already landed unnoticed.
--
-- Actions are stored, not applied destructively. Rewriting historical trades
-- would lose what was actually executed, and a ratio corrected upstream could
-- then never be undone. Quantities are restated at read time instead.
--
-- Safe to re-run.

begin;

-- The date the stored quantities and prices are stated as of. Figures migrated
-- from the workbook were already restated for every split up to the snapshot,
-- so replaying those would double-count: a 10-for-1 baked into an 87.08
-- average must not become 8.708. NULL means the ledger is as-traded and every
-- action applies.
alter table instruments
  add column if not exists basis_date date;

create table if not exists corporate_actions (
  id            varchar(36) primary key,
  instrument_id varchar(36) not null
                references instruments(id) on delete cascade,
  ex_date       date not null,
  -- Shares held after, per share held before: 10 for a 10-for-1 split.
  ratio         numeric(18,6) not null,
  action_type   varchar(16) not null default 'SPLIT',
  source        varchar(32) not null default 'yahoo',
  created_at    timestamptz not null default now(),
  constraint corporate_actions_unique_ex_date unique (instrument_id, ex_date),
  constraint corporate_actions_ratio_positive check (ratio > 0)
);

create index if not exists corporate_actions_instrument_idx
  on corporate_actions (instrument_id, ex_date);

-- Matches the other tables: enabled with no anon policy, so only the service
-- role reaches it.
alter table corporate_actions enable row level security;

-- Everything seeded from the workbook is stated as of the snapshot date.
-- Adjust the literal if a different snapshot is used.
update instruments
   set basis_date = date '2025-08-04'
 where basis_date is null
   and dividend_start_date is not null;

commit;
