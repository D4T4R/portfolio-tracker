"""Parsing and normalisation for bulk trade uploads.

Pure functions over a spreadsheet: no database, no network. Everything here
either produces a clean ``ParsedRow`` or attaches a reason the row cannot be
used. Nothing is rejected silently, because a row dropped without explanation
is how an import quietly loses a trade.

Symbol resolution deliberately does *not* live here. Guessing that "bajfin"
means BAJFINANCE.NS is a database question, and a wrong guess writes a trade
against the wrong company, so it is answered in the service where the tracked
instruments are known - and surfaced for confirmation rather than applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd


class ImportError_(Exception):
    """The file itself cannot be read. Safe to show the caller."""


# Spreadsheets are written by people, so accept the obvious synonyms rather
# than insisting on one spelling. Keys are the canonical field names.
COLUMN_ALIASES: dict[str, set[str]] = {
    "symbol": {"symbol", "ticker", "tickername", "stock", "scrip", "name"},
    "txn_type": {"type", "action", "side", "transactiontype", "buysell"},
    "quantity": {"quantity", "qty", "shares", "units", "noofshares"},
    "trade_date": {"date", "tradedate", "transactiondate", "dateoftrade"},
    "price": {"price", "rate", "pricepershare", "pricepershare", "tradeprice"},
    # Optional.
    "fees": {"fees", "fee", "charges", "brokerage", "cost", "costs"},
    "note": {"note", "notes", "remark", "remarks", "comment"},
    "reference": {"reference", "ref", "txnid", "transactionid", "tradeid"},
}

REQUIRED = ("symbol", "txn_type", "quantity", "trade_date", "price")

BUY_WORDS = {"buy", "b", "bought", "purchase", "purchased", "credit", "add"}
SELL_WORDS = {"sell", "s", "sold", "sale", "disposal", "debit", "exit"}


@dataclass
class ParsedRow:
    """One spreadsheet line, normalised as far as it can be without the db."""

    row_number: int          # 1-based as the user sees it in Excel
    raw_symbol: str = ""
    txn_type: str | None = None
    trade_date: date | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal = Decimal("0")
    note: str | None = None
    reference: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _normalise(header) -> str:
    """Fold a header to a comparison key: 'Price / Share' -> 'priceshare'."""
    return "".join(ch for ch in str(header).lower() if ch.isalnum())


def map_columns(headers) -> tuple[dict[str, str], list[str]]:
    """Match spreadsheet headers to canonical fields.

    Returns the mapping and the list of required fields that are missing.
    """
    resolved: dict[str, str] = {}
    for header in headers:
        key = _normalise(header)
        for canonical, aliases in COLUMN_ALIASES.items():
            # First header to claim a field wins, so a sheet carrying both
            # "Stock" and "Name" does not silently flip between them.
            if key in aliases and canonical not in resolved:
                resolved[canonical] = header
                break

    missing = [f for f in REQUIRED if f not in resolved]
    return resolved, missing


def coerce_date(value) -> date | None:
    """Accept what Excel and pandas actually produce, reject the ambiguous.

    Day-first and month-first strings cannot be told apart (03/04/2025 is two
    different days), so only unambiguous forms are taken.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
                "%d %B %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def coerce_decimal(value) -> Decimal | None:
    """Via str, so a float's binary artefacts never enter the ledger."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "").replace("₹", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def coerce_type(value) -> str | None:
    if value is None:
        return None
    word = "".join(ch for ch in str(value).lower() if ch.isalpha())
    if word in BUY_WORDS:
        return "BUY"
    if word in SELL_WORDS:
        return "SELL"
    return None


def read_rows(source) -> pd.DataFrame:
    """Load the first sheet of an .xlsx/.xls/.csv upload."""
    name = getattr(source, "filename", None) or getattr(source, "name", "") or ""
    try:
        if str(name).lower().endswith(".csv"):
            return pd.read_csv(source, dtype=object)
        return pd.read_excel(source, dtype=object)
    except Exception as exc:  # pandas raises a wide variety here
        raise ImportError_(f"could not read the file: {exc}") from exc


def parse(source) -> list[ParsedRow]:
    """Turn an uploaded sheet into normalised rows plus per-row problems."""
    frame = read_rows(source)
    if frame.empty:
        raise ImportError_("the sheet has no rows")

    mapping, missing = map_columns(frame.columns)
    if missing:
        raise ImportError_(
            "missing required column(s): "
            + ", ".join(missing)
            + f". Found: {', '.join(str(c) for c in frame.columns)}"
        )

    rows: list[ParsedRow] = []
    for offset, (_, record) in enumerate(frame.iterrows()):
        # +2: one for the header line, one because users count from 1.
        row = ParsedRow(row_number=offset + 2)

        raw_symbol = record.get(mapping["symbol"])
        row.raw_symbol = "" if raw_symbol is None else str(raw_symbol).strip()

        # A wholly blank line is padding, not an error.
        values = [record.get(mapping[f]) for f in REQUIRED]
        if all(v is None or str(v).strip() == "" or pd.isna(v) for v in values):
            continue

        if not row.raw_symbol:
            row.errors.append("ticker is blank")

        row.txn_type = coerce_type(record.get(mapping["txn_type"]))
        if row.txn_type is None:
            row.errors.append(
                f"type {record.get(mapping['txn_type'])!r} is not buy or sell"
            )

        row.trade_date = coerce_date(record.get(mapping["trade_date"]))
        if row.trade_date is None:
            row.errors.append(
                f"date {record.get(mapping['trade_date'])!r} is not a date "
                "the importer can read unambiguously; use YYYY-MM-DD"
            )
        elif row.trade_date > date.today():
            row.errors.append(f"date {row.trade_date.isoformat()} is in the future")

        row.quantity = coerce_decimal(record.get(mapping["quantity"]))
        if row.quantity is None:
            row.errors.append("quantity is not a number")
        elif row.quantity <= 0:
            row.errors.append("quantity must be greater than zero")

        row.price = coerce_decimal(record.get(mapping["price"]))
        if row.price is None:
            row.errors.append(
                "price is required - it is the price you bought or sold at, "
                "and without it cost basis and realised gain cannot be computed"
            )
        elif row.price < 0:
            row.errors.append("price cannot be negative")

        if "fees" in mapping:
            fees = coerce_decimal(record.get(mapping["fees"]))
            if fees is None:
                row.fees = Decimal("0")
            elif fees < 0:
                row.errors.append("fees cannot be negative")
            else:
                row.fees = fees

        if "note" in mapping:
            note = record.get(mapping["note"])
            if note is not None and str(note).strip() and not pd.isna(note):
                row.note = str(note).strip()

        if "reference" in mapping:
            ref = record.get(mapping["reference"])
            if ref is not None and str(ref).strip() and not pd.isna(ref):
                row.reference = str(ref).strip().upper()

        rows.append(row)

    if not rows:
        raise ImportError_("the sheet has a header but no trade rows")
    return rows
