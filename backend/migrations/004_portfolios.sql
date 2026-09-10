-- Multiple portfolios.
--
-- An instrument belongs to exactly one portfolio, and everything else
-- (transactions, dividends, corporate actions, price snapshots) hangs off an
-- instrument. So this single foreign key scopes the whole model, and no other
-- table needs a portfolio column.
--
-- Note portfolio_id is a foreign key, not a primary key. Each instrument keeps
-- its own identity; the portfolio is what it belongs to. Making it the primary
-- key would allow only one instrument per portfolio.
--
-- Safe to re-run.

begin;

create table if not exists portfolios (
  id         varchar(36) primary key,
  name       varchar(128) not null unique,
  -- Exactly one portfolio answers a request that names none, so existing
  -- callers and bookmarks keep working after this migration.
  is_default boolean not null default false,
  created_at timestamptz not null default now()
);

alter table portfolios enable row level security;

alter table instruments
  add column if not exists portfolio_id varchar(36) references portfolios(id)
    on delete cascade;

-- Everything that already exists belongs to one book; give it a home rather
-- than leaving rows unreachable behind a NOT NULL.
insert into portfolios (id, name, is_default)
select gen_random_uuid()::text, 'My portfolio', true
where not exists (select 1 from portfolios);

update instruments
   set portfolio_id = (select id from portfolios order by created_at limit 1)
 where portfolio_id is null;

alter table instruments
  alter column portfolio_id set not null;

-- The same stock can now sit in two portfolios with different cost bases, so
-- the symbol is unique per portfolio rather than globally.
alter table instruments
  drop constraint if exists instruments_symbol_key;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'instruments_unique_symbol'
  ) then
    alter table instruments
      add constraint instruments_unique_symbol unique (portfolio_id, symbol);
  end if;
end $$;

create index if not exists instruments_portfolio_idx
  on instruments (portfolio_id);

-- At most one default. A partial unique index says so rather than trusting
-- application code to maintain it.
create unique index if not exists portfolios_single_default
  on portfolios (is_default) where is_default;

commit;
