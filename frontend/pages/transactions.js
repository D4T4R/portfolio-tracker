import Head from 'next/head'
import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'

import PortfolioSwitcher, { usePortfolio } from '../components/v2/PortfolioSwitcher'
import { Badge, Button, Card, Stat, cn } from '../components/v2/primitives'
import { api } from '../lib/api'
import { money, quantity, shortDate } from '../lib/format'

const COLUMNS = [
  { key: 'reference', label: 'Ref', align: 'left' },
  { key: 'tradeDate', label: 'Date', align: 'left' },
  { key: 'name', label: 'Stock', align: 'left' },
  { key: 'type', label: 'Type', align: 'left' },
  { key: 'quantity', label: 'Qty', align: 'right' },
  { key: 'price', label: 'Price', align: 'right' },
  { key: 'grossValue', label: 'Gross', align: 'right' },
  { key: 'fees', label: 'Fees', align: 'right' },
  { key: 'netValue', label: 'Net cash', align: 'right' },
]

// Sorting by a money string would compare lexically, so numeric columns are
// coerced; dates and text sort as they read.
const TEXT_KEYS = new Set(['reference', 'tradeDate', 'name', 'type'])

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

export default function TradeHistory() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [symbol, setSymbol] = useState('all')
  const [type, setType] = useState('all')
  const [sort, setSort] = useState({ key: 'tradeDate', dir: 'desc' })
  const [deleting, setDeleting] = useState(null)

  const {
    portfolios,
    activeId,
    ready: portfolioReady,
    select: selectPortfolio,
    reload: reloadPortfolios,
  } = usePortfolio()

  const load = useCallback(async () => {
    if (!portfolioReady) return
    try {
      setError(null)
      const body = await api.allTransactions()
      setRows(body.transactions)
    } catch (err) {
      setError(err.message)
    }
  }, [portfolioReady, activeId])

  useEffect(() => {
    load()
  }, [load])

  const symbols = useMemo(() => {
    if (!rows) return []
    const seen = new Map()
    rows.forEach((r) => seen.set(r.symbol, r.name))
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])

  const visible = useMemo(() => {
    if (!rows) return []
    const filtered = rows.filter(
      (r) =>
        (symbol === 'all' || r.symbol === symbol) &&
        (type === 'all' || r.type === type)
    )
    const { key, dir } = sort
    return filtered.sort((a, b) => {
      const av = TEXT_KEYS.has(key) ? a[key] : Number(a[key] ?? 0)
      const bv = TEXT_KEYS.has(key) ? b[key] : Number(b[key] ?? 0)
      if (av === bv) return 0
      const cmp = av > bv ? 1 : -1
      return dir === 'asc' ? cmp : -cmp
    })
  }, [rows, symbol, type, sort])

  // Totals follow the filters, so narrowing to one stock answers "what did I
  // put into this name" without a separate view.
  const totals = useMemo(() => {
    const sum = (pred) =>
      visible
        .filter(pred)
        .reduce((acc, r) => acc + Number(r.netValue), 0)
    const invested = sum((r) => r.type === 'BUY')
    const returned = sum((r) => r.type === 'SELL')
    return {
      trades: visible.length,
      buys: visible.filter((r) => r.type === 'BUY').length,
      sells: visible.filter((r) => r.type === 'SELL').length,
      invested,
      returned,
      fees: visible.reduce((acc, r) => acc + Number(r.fees), 0),
    }
  }, [visible])

  const remove = async (row) => {
    const label = `${row.type} ${quantity(row.quantity)} ${row.symbol} on ${shortDate(row.tradeDate)}`
    if (!window.confirm(`Delete this trade?\n\n${label}\n\nThis cannot be undone.`)) {
      return
    }
    setDeleting(row.id)
    try {
      await api.deleteTrade(row.id)
      await load()
    } catch (err) {
      // The ledger refuses a delete that would leave a later sell unmatched.
      setError(err.message)
    } finally {
      setDeleting(null)
    }
  }

  const toggleSort = (key) =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: TEXT_KEYS.has(key) ? 'asc' : 'desc' }
    )

  // min-w-0 so a long stock name in the options cannot widen the control past
  // the viewport, which is what pushed the whole page sideways on a phone.
  const selectClass =
    'min-w-0 max-w-[45vw] rounded-md border border-surface-border bg-surface px-3 py-1.5 text-sm text-neutral-100 focus:border-neutral-500 focus:outline-none'

  return (
    <div className="min-h-screen bg-surface text-neutral-200 antialiased">
      <Head>
        <title>Trade history</title>
      </Head>

      <header className="border-b border-surface-border">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-neutral-50">
              Trade history
            </h1>
            <p className="mt-0.5 text-xs text-muted tabular">
              {rows === null
                ? 'Loading…'
                : `${rows.length} trades across ${symbols.length} stocks`}
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <PortfolioSwitcher
              portfolios={portfolios}
              activeId={activeId}
              onSelect={(id) => {
                selectPortfolio(id)
                setRows(null)
                setSymbol('all')
              }}
              onChanged={reloadPortfolios}
            />
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className={selectClass}
            >
              <option value="all">All stocks</option>
              {symbols.map(([sym, name]) => (
                <option key={sym} value={sym}>
                  {name}
                </option>
              ))}
            </select>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className={selectClass}
            >
              <option value="all">Buys and sells</option>
              <option value="BUY">Buys only</option>
              <option value="SELL">Sells only</option>
            </select>
            <Link href="/import">
              <Button>Import</Button>
            </Link>
            <Link href="/">
              <Button variant="primary">Back to portfolio</Button>
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6">
        {error ? (
          <div className="mb-4 rounded-md border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">
            {error}
          </div>
        ) : null}

        <Card className="mb-6">
          <div className="grid grid-cols-2 divide-x divide-surface-border md:grid-cols-4">
            <Stat
              label="Trades"
              value={totals.trades.toLocaleString('en-IN')}
              hint={`${plural(totals.buys, 'buy')} · ${plural(totals.sells, 'sell')}`}
            />
            <Stat label="Cash invested" value={money(totals.invested)} />
            <Stat label="Cash returned" value={money(totals.returned)} />
            <Stat
              label="Fees"
              value={money(totals.fees)}
              hint="brokerage, STT, stamp duty"
            />
          </div>
        </Card>

        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border">
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className={cn(
                        'cursor-pointer select-none px-3 py-2 text-[11px] font-medium uppercase tracking-wider',
                        'text-muted hover:text-neutral-200',
                        col.align === 'right' ? 'text-right' : 'text-left'
                      )}
                    >
                      {col.label}
                      {sort.key === col.key ? (
                        <span className="ml-1">
                          {sort.dir === 'asc' ? '▲' : '▼'}
                        </span>
                      ) : null}
                    </th>
                  ))}
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows === null ? (
                  <tr>
                    <td
                      colSpan={COLUMNS.length + 1}
                      className="px-3 py-10 text-center text-muted"
                    >
                      Loading…
                    </td>
                  </tr>
                ) : visible.length === 0 ? (
                  <tr>
                    <td
                      colSpan={COLUMNS.length + 1}
                      className="px-3 py-10 text-center text-muted"
                    >
                      {rows.length === 0
                        ? 'No trades recorded yet.'
                        : 'No trades match these filters.'}
                    </td>
                  </tr>
                ) : (
                  visible.map((r) => (
                    <tr
                      key={r.id}
                      className="border-b border-surface-border/60 last:border-0 hover:bg-surface-raised/70"
                    >
                      <td className="whitespace-nowrap px-3 py-2 tabular text-xs text-muted">
                        {r.reference}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 tabular">
                        {shortDate(r.tradeDate)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-neutral-100">
                            {r.name}
                          </span>
                          {r.status === 'archived' ? (
                            <Badge>archived</Badge>
                          ) : null}
                        </div>
                        <div className="text-xs text-muted">{r.symbol}</div>
                      </td>
                      <td className="px-3 py-2">
                        <Badge tone={r.type === 'BUY' ? 'gain' : 'loss'}>
                          {r.type}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right tabular">
                        {quantity(r.quantity)}
                      </td>
                      <td className="px-3 py-2 text-right tabular text-muted">
                        {money(r.price, { precise: true })}
                      </td>
                      <td className="px-3 py-2 text-right tabular">
                        {money(r.grossValue)}
                      </td>
                      <td className="px-3 py-2 text-right tabular text-muted">
                        {Number(r.fees) === 0 ? '—' : money(r.fees)}
                      </td>
                      <td className="px-3 py-2 text-right tabular font-medium">
                        {money(r.netValue)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        <Button
                          variant="ghost"
                          disabled={deleting === r.id}
                          onClick={() => remove(r)}
                        >
                          {deleting === r.id ? 'Deleting…' : 'Delete'}
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {rows?.length ? (
          <p className="mt-3 text-xs text-muted">
            Deleting a trade replays the whole ledger. One that would leave a
            later sell without shares to match is refused rather than applied.
          </p>
        ) : null}
      </main>
    </div>
  )
}
