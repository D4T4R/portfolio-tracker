-- Portfolio tracker: transaction-ledger schema.
--
-- Positions are never stored. Holdings, cost basis, realized gain and dividend
-- income are all derived from `transactions` and `dividends` at read time by
-- portfolio/ledger.py, so there is no denormalised total that can drift.
--
-- Run against Supabase with:  psql "$SUPABASE_DB_URL" -f 001_initial.sql

begin;

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- instruments

create table if not exists instruments (
    id                  uuid primary key default gen_random_uuid(),
    symbol              text not null unique,          -- Yahoo symbol, e.g. ITC.NS
    name                text not null,                 -- display name, e.g. ITC
    status              text not null default 'active'
                        check (status in ('active', 'archived')),

    -- Migration seam. The source workbook recorded a lifetime dividend total
    -- but no payment history, so those rupees are frozen here and the feed is
    -- only consulted from dividend_start_date onward. Without this split the
    -- pre-migration dividends would be counted twice.
    opening_dividends   numeric(18, 4) not null default 0,
    dividend_start_date date,

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

comment on column instruments.opening_dividends is
    'Dividends received before dividend_start_date, carried over from the Excel migration.';

-- --------------------------------------------------------------- transactions

create table if not exists transactions (
    id            uuid primary key default gen_random_uuid(),
    instrument_id uuid not null references instruments(id) on delete cascade,
    txn_type      text not null check (txn_type in ('BUY', 'SELL')),
    trade_date    date not null,
    quantity      numeric(18, 6) not null check (quantity > 0),
    price         numeric(18, 4) not null check (price >= 0),
    fees          numeric(18, 4) not null default 0 check (fees >= 0),
    note          text,
    created_at    timestamptz not null default now()
);

-- Every read replays a single instrument's ledger in date order.
create index if not exists transactions_instrument_date_idx
    on transactions (instrument_id, trade_date);

-- ------------------------------------------------------------------ dividends

create table if not exists dividends (
    id            uuid primary key default gen_random_uuid(),
    instrument_id uuid not null references instruments(id) on delete cascade,
    -- Entitlement follows whoever held the shares on the ex-date, so this is
    -- the date the ledger is replayed to when valuing the payment.
    ex_date       date not null,
    per_share     numeric(18, 6) not null check (per_share >= 0),
    source        text not null default 'yahoo',
    created_at    timestamptz not null default now(),
    unique (instrument_id, ex_date)
);

create index if not exists dividends_instrument_date_idx
    on dividends (instrument_id, ex_date);

-- ------------------------------------------------------------ price snapshots

-- Daily closes, kept so the dashboard can render instantly and survive the
-- Yahoo rate limiting that makes live fetches unreliable.
create table if not exists price_snapshots (
    instrument_id uuid not null references instruments(id) on delete cascade,
    as_of         date not null,
    close         numeric(18, 4) not null,
    fetched_at    timestamptz not null default now(),
    primary key (instrument_id, as_of)
);

-- ----------------------------------------------------------------------- misc

create or replace function touch_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists instruments_touch_updated_at on instruments;
create trigger instruments_touch_updated_at
    before update on instruments
    for each row execute function touch_updated_at();

-- Single-user app: the API talks to Postgres with the service role, and no
-- anon/authenticated policies are defined, so RLS denies everything else.
alter table instruments     enable row level security;
alter table transactions    enable row level security;
alter table dividends       enable row level security;
alter table price_snapshots enable row level security;

commit;
