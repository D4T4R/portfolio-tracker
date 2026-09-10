import Head from 'next/head'
import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'

import PortfolioSwitcher, { usePortfolio } from '../components/v2/PortfolioSwitcher'
import TradeDialog from '../components/v2/TradeDialog'
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  cn,
} from '../components/v2/primitives'
import { api } from '../lib/api'
import {
  money,
  percent,
  quantity,
  shortDate,
  signedMoney,
  toneClass,
  toneOf,
} from '../lib/format'

const COLUMNS = [
  { key: 'name', label: 'Holding', align: 'left' },
  { key: 'quantity', label: 'Qty', align: 'right' },
  { key: 'averageCost', label: 'Avg cost', align: 'right' },
  { key: 'marketPrice', label: 'Price', align: 'right' },
  { key: 'marketValue', label: 'Value', align: 'right' },
  { key: 'unrealized', label: 'Unrealized', align: 'right' },
  { key: 'realized', label: 'Realized', align: 'right' },
  { key: 'dividendIncome', label: 'Dividends', align: 'right' },
  { key: 'totalProfit', label: 'Total P&L', align: 'right' },
  { key: 'totalReturnPct', label: 'Return', align: 'right' },
]

export default function LedgerDashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [priceState, setPriceState] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [sort, setSort] = useState({ key: 'marketValue', dir: 'desc' })
  const [showArchived, setShowArchived] = useState(false)
  const [tradeFor, setTradeFor] = useState(null)
  const [addOpen, setAddOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncingActions, setSyncingActions] = useState(false)
  const [syncNote, setSyncNote] = useState(null)

  const {
    portfolios,
    activeId,
    ready: portfolioReady,
    select: selectPortfolio,
    reload: reloadPortfolios,
  } = usePortfolio()

  const load = useCallback(async () => {
    // Held until the active portfolio is settled, so the first request is not
    // fired against the default and then repeated against the real one.
    if (!portfolioReady) return
    try {
      setError(null)
      setData(await api.portfolio(showArchived))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [showArchived, portfolioReady, activeId])

  useEffect(() => {
    load()
  }, [load])

  const refresh = async () => {
    setRefreshing(true)
    try {
      const result = await api.refreshPrices(true)
      setPriceState(result)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setRefreshing(false)
    }
  }

  const holdings = useMemo(() => {
    if (!data) return []
    const rows = [...data.holdings]
    const { key, dir } = sort
    rows.sort((a, b) => {
      const av = key === 'name' ? a.instrument.name : Number(a[key] ?? 0)
      const bv = key === 'name' ? b.instrument.name : Number(b[key] ?? 0)
      if (av === bv) return 0
      const cmp = av > bv ? 1 : -1
      return dir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [data, sort])

  const toggleSort = (key) =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'name' ? 'asc' : 'desc' }
    )

  const syncActions = async () => {
    setSyncingActions(true)
    setSyncNote(null)
    try {
      const r = await api.syncCorporateActions()
      const suspects = r.suspects?.length
        ? ` Still unexplained: ${r.suspects
            .map((s) => `${s.symbol} down ${s.dropPct}% (looks like ${s.impliedRatio}:1)`)
            .join('; ')}.`
        : ''
      setSyncNote(
        r.error
          ? `Split check failed: ${r.error}`
          : `${r.added ? `Applied ${r.added} split(s).` : 'No new splits found.'}${suspects}`
      )
      await load()
    } catch (err) {
      setSyncNote(`Split check failed: ${err.message}`)
    } finally {
      setSyncingActions(false)
    }
  }

  const syncDividends = async () => {
    setSyncing(true)
    setSyncNote(null)
    try {
      const result = await api.syncDividends()
      setSyncNote(
        result.error
          ? `Dividend sync failed: ${result.error}`
          : result.added || result.updated
            ? `Imported ${result.added} new and updated ${result.updated} payments across ${result.symbols} stocks.`
            : 'Dividends already up to date.'
      )
      await load()
    } catch (err) {
      setSyncNote(`Dividend sync failed: ${err.message}`)
    } finally {
      setSyncing(false)
    }
  }

  const recordTrade = async (id, trade) => {
    await api.recordTrade(id, trade)
    await load()
  }

  const archive = async (holding) => {
    try {
      await api.archive(holding.instrument.id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const summary = data?.summary

  return (
    <div className="min-h-screen bg-surface text-neutral-200 antialiased">
      <Head>
        <title>Portfolio</title>
      </Head>

      <header className="border-b border-surface-border">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-neutral-50">Portfolio</h1>
            <p className="mt-0.5 text-xs text-muted tabular">
              {data?.pricesAsOf
                ? `Prices as of ${shortDate(data.pricesAsOf)}`
                : 'No prices stored yet'}
              {priceState ? ` · ${priceState.reason}` : ''}
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <PortfolioSwitcher
              portfolios={portfolios}
              activeId={activeId}
              onSelect={(id) => {
                selectPortfolio(id)
                setLoading(true)
                setData(null)
                setPriceState(null)
              }}
              onChanged={reloadPortfolios}
            />
            {priceState?.marketStatus ? (
              <Badge tone={priceState.marketStatus === 'open' ? 'gain' : 'neutral'}>
                Market {priceState.marketStatus}
              </Badge>
            ) : null}
            <Button onClick={() => setShowArchived((v) => !v)} variant="ghost">
              {showArchived ? 'Hide archived' : 'Show archived'}
            </Button>
            <Link href="/transactions">
              <Button variant="ghost">Trade history</Button>
            </Link>
            <Button onClick={syncDividends} disabled={syncing}>
              {syncing ? 'Syncing…' : 'Sync dividends'}
            </Button>
            <Button onClick={syncActions} disabled={syncingActions}>
              {syncingActions ? 'Checking…' : 'Check splits'}
            </Button>
            <Button onClick={() => setAddOpen(true)}>Add stock</Button>
            <Button onClick={refresh} disabled={refreshing} variant="primary">
              {refreshing ? 'Refreshing…' : 'Refresh prices'}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6">
        {error ? (
          <div className="mb-4 rounded-md border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">
            {error}
          </div>
        ) : null}

        {syncNote ? (
          <div className="mb-4 flex items-start justify-between gap-4 rounded-md border border-surface-border bg-surface-raised px-4 py-3 text-sm text-neutral-300">
            <span>{syncNote}</span>
            <button
              onClick={() => setSyncNote(null)}
              className="text-muted hover:text-neutral-100"
            >
              ✕
            </button>
          </div>
        ) : null}

        {priceState && !priceState.live ? (
          <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            Showing stored closes — {priceState.reason}
            {priceState.error ? ` (${priceState.error})` : ''}
          </div>
        ) : null}

        {summary ? <SummaryCard summary={summary} /> : null}

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
                {loading ? (
                  <tr>
                    <td
                      colSpan={COLUMNS.length + 1}
                      className="px-3 py-10 text-center text-muted"
                    >
                      Loading…
                    </td>
                  </tr>
                ) : holdings.length === 0 ? (
                  <tr>
                    <td
                      colSpan={COLUMNS.length + 1}
                      className="px-3 py-10 text-center text-muted"
                    >
                      Nothing tracked yet. Add a stock to begin.
                    </td>
                  </tr>
                ) : (
                  holdings.map((h) => (
                    <tr
                      key={h.instrument.id}
                      className="border-b border-surface-border/60 last:border-0 hover:bg-surface-raised/70"
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-neutral-100">
                            {h.instrument.name}
                          </span>
                          {h.instrument.status === 'archived' ? (
                            <Badge>archived</Badge>
                          ) : null}
                        </div>
                        <div className="text-xs text-muted">
                          {h.instrument.symbol}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right tabular">
                        {quantity(h.quantity)}
                      </td>
                      <td className="px-3 py-2 text-right tabular text-muted">
                        {money(h.averageCost, { precise: true })}
                      </td>
                      <td className="px-3 py-2 text-right tabular">
                        {money(h.marketPrice, { precise: true })}
                      </td>
                      <td className="px-3 py-2 text-right tabular">
                        {money(h.marketValue)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right tabular',
                          toneClass[toneOf(h.unrealized)]
                        )}
                      >
                        {signedMoney(h.unrealized)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right tabular',
                          toneClass[toneOf(h.realized)]
                        )}
                      >
                        {Number(h.realized) === 0
                          ? '—'
                          : signedMoney(h.realized)}
                      </td>
                      <td className="px-3 py-2 text-right tabular text-muted">
                        {Number(h.dividendIncome) === 0
                          ? '—'
                          : money(h.dividendIncome)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right tabular font-medium',
                          toneClass[toneOf(h.totalProfit)]
                        )}
                      >
                        {signedMoney(h.totalProfit)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right tabular',
                          toneClass[toneOf(h.totalReturnPct)]
                        )}
                      >
                        {percent(h.totalReturnPct)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        <Button variant="ghost" onClick={() => setTradeFor(h)}>
                          Trade
                        </Button>
                        {Number(h.quantity) === 0 &&
                        h.instrument.status === 'active' ? (
                          <Button variant="ghost" onClick={() => archive(h)}>
                            Archive
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </main>

      <TradeDialog
        open={Boolean(tradeFor)}
        holding={tradeFor}
        onClose={() => setTradeFor(null)}
        onSubmit={recordTrade}
      />

      <AddInstrumentDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdded={load}
      />
    </div>
  )
}

// The total is deliberately the headline, with the three things that make it
// up beneath. An earlier version put capital-ever-invested next to current
// market value, which reads as a loss: the invested figure still counts shares
// that have since been sold, while the value figure no longer does. The only
// honest comparison is cost of what is still held against what it is worth,
// and that pairing now lives inside a single row.
function SummaryCard({ summary }) {
  const contributions = [
    {
      key: 'holdings',
      label: 'Holdings',
      detail: `${money(summary.marketValue)} now vs ${money(summary.costBasis)} cost`,
      amount: summary.unrealized,
      bar: 'bg-gain',
    },
    {
      key: 'sold',
      label: 'Sold',
      detail: 'booked on shares exited',
      amount: summary.realized,
      bar: 'bg-emerald-700',
    },
    {
      key: 'dividends',
      label: 'Dividends',
      detail: 'paid out to you',
      amount: summary.dividends,
      bar: 'bg-sky-700',
    },
  ]

  // Shares of the total, by magnitude so a losing component still occupies
  // width rather than silently vanishing from the bar.
  const magnitude = contributions.reduce(
    (acc, c) => acc + Math.abs(Number(c.amount)),
    0
  )

  const holdingsPct =
    Number(summary.costBasis) > 0
      ? (Number(summary.unrealized) * 100) / Number(summary.costBasis)
      : 0

  return (
    <Card className="mb-6 overflow-hidden">
      <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] md:divide-x md:divide-surface-border">
        <div className="px-5 py-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted">
            Total return
          </div>
          <div
            className={cn(
              'mt-1 text-3xl font-semibold tabular',
              toneClass[toneOf(summary.totalProfit)]
            )}
          >
            {signedMoney(summary.totalProfit)}
          </div>
          <div
            className={cn(
              'mt-0.5 text-sm font-medium tabular',
              toneClass[toneOf(summary.totalReturnPct)]
            )}
          >
            {percent(summary.totalReturnPct)}
          </div>
          <div className="mt-2 text-xs text-muted tabular">
            on {money(summary.capitalDeployed)} invested across every purchase
          </div>

          <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-overlay">
            {magnitude > 0
              ? contributions.map((c) => (
                  <div
                    key={c.key}
                    className={cn(
                      Number(c.amount) < 0 ? 'bg-loss' : c.bar
                    )}
                    style={{
                      width: `${(Math.abs(Number(c.amount)) * 100) / magnitude}%`,
                    }}
                  />
                ))
              : null}
          </div>
        </div>

        <div className="divide-y divide-surface-border border-t border-surface-border md:border-t-0">
          {contributions.map((c) => (
            <div
              key={c.key}
              className="flex items-center justify-between gap-3 px-5 py-[13px]"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'h-2 w-2 shrink-0 rounded-full',
                      Number(c.amount) < 0 ? 'bg-loss' : c.bar
                    )}
                  />
                  <span className="text-sm font-medium text-neutral-100">
                    {c.label}
                  </span>
                  {c.key === 'holdings' ? (
                    <span
                      className={cn(
                        'text-xs tabular',
                        toneClass[toneOf(holdingsPct)]
                      )}
                    >
                      {percent(holdingsPct)}
                    </span>
                  ) : null}
                </div>
                {/* Wraps rather than truncates: on a phone this is the line
                    that explains where the number came from, so losing its
                    tail is worse than taking a second line. */}
                <div className="mt-0.5 pl-4 text-xs text-muted tabular">
                  {c.detail}
                </div>
              </div>
              <div
                className={cn(
                  'shrink-0 text-base font-semibold tabular',
                  c.key === 'dividends'
                    ? 'text-sky-300'
                    : toneClass[toneOf(c.amount)]
                )}
              >
                {c.key === 'dividends'
                  ? money(c.amount)
                  : signedMoney(c.amount)}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-surface-border px-5 py-2 text-[11px] text-muted">
        {summary.positions} open positions · gains already booked and dividends
        received are no longer part of what the holdings are worth, which is why
        the total exceeds the value on screen
      </div>
    </Card>
  )
}

function AddInstrumentDialog({ open, onClose, onAdded }) {
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.addInstrument(symbol, name)
      setSymbol('')
      setName('')
      onClose()
      await onAdded()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Track a new stock">
      <form onSubmit={submit} className="space-y-3">
        <Field
          label="Yahoo symbol"
          hint="NSE tickers carry the .NS suffix, e.g. ITC.NS"
        >
          <Input
            required
            placeholder="ITC.NS"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          />
        </Field>
        <Field label="Display name">
          <Input
            required
            placeholder="ITC"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        {error ? (
          <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
            {error}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add stock'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
