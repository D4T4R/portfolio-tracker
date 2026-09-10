-- Adds a human-readable handle to every trade.
--
-- transactions.id is a UUID and remains the primary key; it is what foreign
-- keys and the API address. It is not, however, something you can read off a
-- screen, quote in a note, or type into a spreadsheet column. `reference` is
-- that: short, ordered, and unique, which also lets a re-uploaded import sheet
-- be recognised as already applied instead of silently doubling a position.
--
-- Safe to re-run.

begin;

alter table transactions
  add column if not exists reference varchar(16);

-- Backfill in ledger order so the numbering reads like the history does.
with numbered as (
  select id,
         row_number() over (order by trade_date, created_at, id) as seq
  from transactions
  where reference is null
)
update transactions t
   set reference = 'TXN-' || lpad(numbered.seq::text, 6, '0')
  from numbered
 where t.id = numbered.id;

alter table transactions
  alter column reference set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'transactions_reference_unique'
  ) then
    alter table transactions
      add constraint transactions_reference_unique unique (reference);
  end if;
end $$;

-- The high-water mark for reference numbers. Kept separately because
-- max(reference) rewinds when the newest trade is deleted, which would hand a
-- retired number to a different trade.
create table if not exists counters (
  name  varchar(32) primary key,
  value bigint not null default 0
);

alter table counters enable row level security;

insert into counters (name, value)
select 'transaction_reference', coalesce(count(*), 0) from transactions
on conflict (name) do nothing;

commit;
