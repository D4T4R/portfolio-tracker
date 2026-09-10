"""Convert the legacy workbook into ledger seed SQL.

The workbook stores a position snapshot, not a history: it knows the average
price and how many shares were booked, but not when anything was traded. So the
seed synthesises the smallest ledger that reproduces the sheet exactly:

  * one BUY of INITIAL QTY at AVG PRICE on OPENING_TRADE_DATE
  * where shares were booked, one SELL of BOOKED QTY priced so the resulting
    realized gain equals the sheet's REALIZED column

Dividends are *not* replayed. The sheet's DIVIDEND TILL NOW is carried as an
opening balance and the market feed is only consulted from the migration date
onward, because the synthetic trade dates above are not real enough to decide
who held what on a historical ex-date.

Usage:
    python scripts/seed_from_excel.py <workbook.xlsx> -o seed.sql
    python scripts/seed_from_excel.py <workbook.xlsx> --report-only
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio.ledger import Transaction, TxnType, weighted_average  # noqa: E402

# Purchase date for every migrated holding. The real dates are unknown; this is
# early enough that all seeded lots classify as long-term.
OPENING_TRADE_DATE = date(2021, 12, 15)

# Booked shares are dated to the workbook's own CMP snapshot, the latest moment
# the sheet is known to describe. Only affects FIFO term classification, never
# dividends, because those start at MIGRATION_DATE.
OPENING_SALE_DATE = date(2025, 8, 4)

# Dividends from here on are fetched from the market feed; anything earlier is
# already inside opening_dividends.
MIGRATION_DATE = date(2025, 8, 4)

# Column indices (1-based) in the sheet.
COL_NAME, COL_AVG_PRICE, COL_INITIAL_QTY, COL_QTY = 1, 2, 3, 4
COL_DIVIDEND, COL_REALIZED, COL_BOOKED_QTY = 9, 12, 13

NON_POSITION_LABELS = {"", "NAME", "STOCK", "STOCK NAME", "TOTAL", "TOTALS", "NONE"}

# Matches numeric(18, 4) on transactions.price in 001_initial.sql.
PRICE_SCALE = Decimal("0.0001")

# Sheet names that are not Yahoo tickers. Anything absent falls back to
# "<NAME>.NS" with spaces stripped, which the operator should review.
SYMBOL_OVERRIDES = {
    "MAHINDRA & MAHINDRA": "M&M.NS",
    "STATE BANK OF INDIA": "SBIN.NS",
    "HAPPIEST MINDS TECH": "HAPPSTMNDS.NS",
    "HCL TECHNOLOGIES": "HCLTECH.NS",
    "ASIAN PAINTS": "ASIANPAINT.NS",
    "BRITANNIA INDUSTRIES": "BRITANNIA.NS",
    "TATA CHEMICALS": "TATACHEM.NS",
    "TATA ELXSI": "TATAELXSI.NS",
    "TATA POWER": "TATAPOWER.NS",
    "TATA STEEL": "TATASTEEL.NS",
    "ADANI PORTS": "ADANIPORTS.NS",
    "INDIAN HOTELS": "INDHOTEL.NS",
    "PTC INDIA": "PTC.NS",
    "LIC INDIA": "LICI.NS",
    "INDUSIND BANK": "INDUSINDBK.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS",
    "INFOSYS": "INFY.NS",
    "ITC HOTELS": "ITCHOTELS.NS",
}


@dataclass
class SeededPosition:
    name: str
    symbol: str
    avg_price: Decimal
    initial_qty: Decimal
    quantity: Decimal
    booked_qty: Decimal
    realized: Decimal
    dividends: Decimal
    transactions: list[Transaction]

    @property
    def status(self) -> str:
        return "active" if self.quantity > 0 else "archived"


def to_decimal(value, default="0") -> Decimal:
    """Coerce a cell to Decimal, tolerating blanks and thousands separators."""
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value).replace(",", "").strip() or default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def resolve_symbol(name: str) -> str:
    if name in SYMBOL_OVERRIDES:
        return SYMBOL_OVERRIDES[name]
    return f"{name.replace(' ', '')}.NS"


def build_position(row) -> SeededPosition | None:
    """Turn one sheet row into a seeded position, or None if it is not one."""
    name = str(row[COL_NAME - 1] or "").strip()
    if name.upper() in NON_POSITION_LABELS:
        return None

    initial_qty = to_decimal(row[COL_INITIAL_QTY - 1])
    quantity = to_decimal(row[COL_QTY - 1])
    avg_price = to_decimal(row[COL_AVG_PRICE - 1])

    # Watchlist rows carry a name and nothing else.
    if initial_qty <= 0 and quantity <= 0:
        return None

    booked_qty = to_decimal(row[COL_BOOKED_QTY - 1])
    realized = to_decimal(row[COL_REALIZED - 1])
    dividends = to_decimal(row[COL_DIVIDEND - 1])

    txns = [
        Transaction(OPENING_TRADE_DATE, TxnType.BUY, initial_qty, avg_price)
    ]

    if booked_qty > 0:
        # Choose the sell price that reproduces the sheet's realized figure:
        #   realized = (sell_price - avg_price) * booked_qty
        # Quantized to the column's scale so reconciliation checks the value
        # Postgres will actually store, not a longer intermediate.
        sell_price = (avg_price + (realized / booked_qty)).quantize(PRICE_SCALE)
        if sell_price < 0:
            # A loss deep enough to imply a negative price means the sheet's
            # realized and booked columns disagree; surface rather than invent.
            raise ValueError(
                f"{name}: realized {realized} over {booked_qty} shares implies "
                f"a negative sale price ({sell_price})"
            )
        txns.append(
            Transaction(OPENING_SALE_DATE, TxnType.SELL, booked_qty, sell_price)
        )

    return SeededPosition(
        name=name,
        symbol=resolve_symbol(name),
        avg_price=avg_price,
        initial_qty=initial_qty,
        quantity=quantity,
        booked_qty=booked_qty,
        realized=realized,
        dividends=dividends,
        transactions=txns,
    )


def read_positions(path: Path) -> list[SeededPosition]:
    ws = load_workbook(path, data_only=True).active
    positions = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        position = build_position(row)
        if position is not None:
            positions.append(position)
    return positions


def reconcile(positions: list[SeededPosition]) -> list[str]:
    """Replay each seeded ledger and compare it with the sheet."""
    problems = []
    for p in positions:
        pos = weighted_average(p.transactions)

        if pos.quantity != p.quantity:
            problems.append(
                f"{p.name}: ledger quantity {pos.quantity} != sheet QTY {p.quantity}"
            )

        # Realized only exists where shares were booked.
        expected = p.realized if p.booked_qty > 0 else Decimal("0")
        if abs(pos.realized_gain - expected) > Decimal("0.05"):
            problems.append(
                f"{p.name}: ledger realized {pos.realized_gain:.2f} != "
                f"sheet REALIZED {expected:.2f}"
            )
    return problems


def sql_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, Decimal):
        return f"{value:f}"
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(positions: list[SeededPosition]) -> str:
    lines = [
        "-- Generated by scripts/seed_from_excel.py. Review before running.",
        "--",
        f"-- Opening trades dated {OPENING_TRADE_DATE} (real dates unknown).",
        f"-- Dividends before {MIGRATION_DATE} are carried as opening balances.",
        "",
        "begin;",
        "",
    ]

    for p in positions:
        lines.append(f"-- {p.name}")
        lines.append(
            "insert into instruments "
            "(symbol, name, status, opening_dividends, dividend_start_date)\n"
            f"values ({sql_literal(p.symbol)}, {sql_literal(p.name)}, "
            f"{sql_literal(p.status)}, {sql_literal(p.dividends)}, "
            f"{sql_literal(MIGRATION_DATE)})\n"
            "on conflict (symbol) do update set\n"
            "    name = excluded.name,\n"
            "    status = excluded.status,\n"
            "    opening_dividends = excluded.opening_dividends,\n"
            "    dividend_start_date = excluded.dividend_start_date;"
        )

        for txn in p.transactions:
            lines.append(
                "insert into transactions "
                "(instrument_id, txn_type, trade_date, quantity, price, note)\n"
                "select id, "
                f"{sql_literal(txn.txn_type.value)}, "
                f"{sql_literal(txn.trade_date)}, "
                f"{sql_literal(txn.quantity)}, "
                f"{sql_literal(txn.price)}, "
                "'seeded from Excel migration'\n"
                f"from instruments where symbol = {sql_literal(p.symbol)};"
            )
        lines.append("")

    lines.append("commit;")
    return "\n".join(lines)


def print_report(positions: list[SeededPosition], problems: list[str]) -> None:
    active = [p for p in positions if p.status == "active"]
    archived = [p for p in positions if p.status == "archived"]
    txn_count = sum(len(p.transactions) for p in positions)

    print(f"positions:    {len(positions)} ({len(active)} active, "
          f"{len(archived)} archived)")
    print(f"transactions: {txn_count}")
    print(f"opening dividends: {sum(p.dividends for p in positions):,.2f}")
    print(f"opening realized:  {sum(p.realized for p in positions):,.2f}")
    print()

    if problems:
        print(f"RECONCILIATION FAILED ({len(problems)} issue(s)):")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("reconciliation OK: every seeded ledger reproduces the sheet's "
              "QTY and REALIZED.")


def apply_to_database(positions: list[SeededPosition], database_url: str,
                      create_tables: bool = False) -> None:
    """Insert the seed through the ORM, so one path works on any backend.

    Preferred over piping the generated SQL, which is Postgres-flavoured. This
    is idempotent per symbol: re-running updates the instrument and skips
    transactions that are already present.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from portfolio.models import Base, Instrument
    from portfolio.models import Transaction as TxnRow
    from portfolio.service import PortfolioService

    engine = create_engine(database_url)
    if create_tables:
        Base.metadata.create_all(engine)

    with Session(engine) as session:
        service = PortfolioService(session)
        for p in positions:
            instrument = session.scalar(
                select(Instrument).where(Instrument.symbol == p.symbol)
            )
            if instrument is None:
                instrument = Instrument(symbol=p.symbol, name=p.name)
                session.add(instrument)
                session.flush()

            instrument.name = p.name
            instrument.status = p.status
            instrument.opening_dividends = p.dividends
            instrument.dividend_start_date = MIGRATION_DATE

            for txn in p.transactions:
                already = session.scalar(
                    select(TxnRow).where(
                        TxnRow.instrument_id == instrument.id,
                        TxnRow.txn_type == txn.txn_type.value,
                        TxnRow.trade_date == txn.trade_date,
                        TxnRow.quantity == txn.quantity,
                    )
                )
                if already is not None:
                    continue
                session.add(
                    TxnRow(
                        # Allocated one at a time because the loop skips rows
                        # already present; a batch reserved up front would
                        # leave gaps on a re-run.
                        reference=service.next_references(1)[0],
                        instrument_id=instrument.id,
                        txn_type=txn.txn_type.value,
                        trade_date=txn.trade_date,
                        quantity=txn.quantity,
                        price=txn.price,
                        note="seeded from Excel migration",
                    )
                )
                session.flush()
        session.commit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("-o", "--output", type=Path,
                        help="write seed SQL here (default: stdout)")
    parser.add_argument("--report-only", action="store_true",
                        help="reconcile without emitting SQL")
    parser.add_argument("--apply", metavar="DATABASE_URL",
                        help="write directly to this database instead of "
                             "emitting SQL")
    parser.add_argument("--create-tables", action="store_true",
                        help="create the schema before seeding (with --apply)")
    args = parser.parse_args(argv)

    if not args.workbook.is_file():
        parser.error(f"no such workbook: {args.workbook}")

    positions = read_positions(args.workbook)
    if not positions:
        print("no positions found in workbook", file=sys.stderr)
        return 1

    problems = reconcile(positions)
    print_report(positions, problems)

    if problems:
        print("\nrefusing to emit SQL while the seed disagrees with the sheet",
              file=sys.stderr)
        return 1

    if args.apply:
        apply_to_database(positions, args.apply, args.create_tables)
        print(f"\napplied {len(positions)} positions to the database")
        return 0

    if args.report_only:
        return 0

    sql = render_sql(positions)
    if args.output:
        args.output.write_text(sql)
        print(f"\nwrote {args.output}")
    else:
        print()
        print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
