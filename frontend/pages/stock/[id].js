import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import { useCallback, useEffect, useState } from 'react'

import FundamentalsPanel from '../../components/v2/FundamentalsPanel'
import PriceChart from '../../components/v2/PriceChart'
import TradeDialog from '../../components/v2/TradeDialog'
import { Badge, Button, Card, cn } from '../../components/v2/primitives'
import { api } from '../../lib/api'
import {
  money,
  percent,
  quantity,
  shortDate,
  signedMoney,
  toneClass,
  toneOf,
} from '../../lib/format'

/**
 * One holding in full: what it cost, what it is worth, what it did, and what
 * the screener makes of the company behind it.
 *
 * Keyed on the instrument id rather than the symbol, because with more than
 * one portfolio the same symbol can name two different positions.
 */
export default function StockDetail() {
  const router = useRouter()
  const { id } = router.query

  const [detail, setDetail] = useState(null)
  const [history, setHistory] = useState(null)
  const [range, setRange] = useState('1y')
  const [chartLoading, setChartLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tradeOpen, setTradeOpen] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    try {
      setError(null)
      setDetail(await api.instrumentDetail(id))
    } catch (err) {
      setError(err.message)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // Separate from the detail fetch: this one goes to the price feed, so the
  // rest of the page must not wait on it or fail with it.
  useEffect(() => {
    if (!id) return undefined
    let cancelled = false

    setChartLoading(true)
    api
      .instrumentHistory(id, range)
      .then((body) => !cancelled && setHistory(body))
      .catch((err) => !cancelled && setHistory({ error: err.message, candles: [] }))
      .finally(() => !cancelled && setChartLoading(false))

    return () => {
      cancelled = true
    }
  }, [id, range])

  const recordTrade = async (instrumentId, trade) => {
    await api.recordTrade(instrumentId, trade)
    await load()
  }

  if (error) {
    return (
      <Shell>
        <div className="rounded-md border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      </Shell>
    )
  }

  if (!detail) {
    return (
      <Shell>
        <p className="text-sm text-muted">Loading…</p>
      </Shell>
    )
  }

  const { instrument } = detail
  const held = Number(detail.quantity)
  const previous = history?.previousClose ? Number(history.previousClose) : null
  const latest = Number(detail.marketPrice ?? 0)
  const dayChange = previous && latest ? latest - previous : null
  const dayChangePct = dayChange !== null && previous ? (dayChange / previous) * 100 : null
  const vsCost = latest ? latest - Number(detail.averageCost) : null

  return (
    <Shell
      title={instrument.name}
      symbol={instrument.symbol}
      archived={instrument.status === 'archived'}
      asOf={detail.pricesAsOf}
      onTrade={() => setTradeOpen(true)}
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          <Card className="p-4">
            <SectionTitle>Holdings summary</SectionTitle>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <Figure label="Quantity" value={`${quantity(detail.quantity)} shares`} />
              <Figure label="Avg cost" value={money(detail.averageCost, { precise: true })} />
              <Figure label="Invested" value={money(detail.costBasis)} />
              <Figure label="Current value" value={money(detail.marketValue)} />
            </div>
            <p className="mt-3 border-t border-surface-border pt-2 text-[11px] text-muted">
              {detail.tradeCount} trade{detail.tradeCount === 1 ? '' : 's'}
              {detail.firstTradeDate
                ? ` since ${shortDate(detail.firstTradeDate)}`
                : ''}
              {/* Invested is what the open shares cost, not every rupee ever
                  put in - the difference is capital that has come back out. */}
              {Number(detail.totalInvested) !== Number(detail.costBasis)
                ? ` · ${money(detail.totalInvested)} deployed in total`
                : ''}
            </p>
          </Card>

          <Card className="p-4">
            <SectionTitle>Profit &amp; loss</SectionTitle>
            <div
              className={cn(
                'tabular text-2xl font-semibold',
                toneClass[toneOf(detail.totalProfit)]
              )}
            >
              {signedMoney(detail.totalProfit)}
            </div>
            <div className={cn('tabular text-sm', toneClass[toneOf(detail.totalReturnPct)])}>
              {percent(detail.totalReturnPct)}
            </div>

            <div className="mt-3 space-y-1.5 border-t border-surface-border pt-3 text-sm">
              <Line label="Unrealized" value={detail.unrealized} />
              <Line label="Realized" value={detail.realized} />
              <Line label="Dividends" value={detail.dividendIncome} neutral />
            </div>

            {detail.realizedSales?.length ? (
              <p className="mt-3 text-[11px] text-muted">
                Booked across {detail.realizedSales.length} disposal
                {detail.realizedSales.length === 1 ? '' : 's'};{' '}
                {detail.realizedSales.filter((s) => s.term === 'LTCG').length} long
                term.
              </p>
            ) : null}
          </Card>

          <Card className="p-4">
            <SectionTitle>Portfolio weight</SectionTitle>
            <div className="flex items-baseline justify-between">
              <span className="tabular text-lg font-semibold text-neutral-100">
                {percent(detail.weightPct).replace('+', '')}
              </span>
              <span className="text-xs text-muted">of market value</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-overlay">
              <div
                className="h-full rounded-full bg-neutral-400"
                style={{ width: `${Math.min(100, Number(detail.weightPct))}%` }}
              />
            </div>
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <SectionTitle>Market price</SectionTitle>
                <div className="tabular text-2xl font-semibold text-neutral-50">
                  {money(detail.marketPrice, { precise: true })}
                </div>
                {dayChange !== null ? (
                  <div className={cn('tabular text-sm', toneClass[toneOf(dayChange)])}>
                    {/* Precise, unlike the totals: a day's move on one share
                        is often under a rupee, and rounding it to whole
                        rupees prints "-₹0" beside a real -0.12%. */}
                    {dayChange >= 0 ? '+' : ''}
                    {money(dayChange, { precise: true })} ({percent(dayChangePct)})
                    since previous close
                  </div>
                ) : (
                  <div className="text-xs text-muted">
                    No previous close to compare against yet
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-6">
                <Figure
                  label="Vs avg cost"
                  value={vsCost === null ? '—' : signedMoney(vsCost)}
                  tone={vsCost === null ? undefined : toneOf(vsCost)}
                  hint={vsCost === null ? null : vsCost >= 0 ? 'above' : 'below'}
                />
                <Figure
                  label="Today's impact"
                  value={
                    dayChange === null ? '—' : signedMoney(dayChange * held)
                  }
                  tone={dayChange === null ? undefined : toneOf(dayChange)}
                  hint={dayChange === null ? null : `on ${quantity(detail.quantity)} shares`}
                />
              </div>
            </div>
          </Card>

          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <SectionTitle>Price history</SectionTitle>
              <a
                href={`https://www.tradingview.com/chart/?symbol=NSE%3A${instrument.symbol.replace(/\.(NS|BO)$/i, '')}`}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-muted hover:text-neutral-200"
              >
                Open in TradingView ↗
              </a>
            </div>
            <PriceChart
              data={history}
              range={range}
              onRangeChange={setRange}
              loading={chartLoading}
            />
          </Card>

          <FundamentalsPanel symbol={instrument.symbol} />
        </div>
      </div>

      <TradeDialog
        open={tradeOpen}
        holding={detail}
        onClose={() => setTradeOpen(false)}
        onSubmit={recordTrade}
      />
    </Shell>
  )
}

function Shell({ title, symbol, archived, asOf, onTrade, children }) {
  return (
    <div className="min-h-screen bg-surface text-neutral-200 antialiased">
      <Head>
        <title>{title ? `${title} · Portfolio` : 'Portfolio'}</title>
      </Head>

      <header className="border-b border-surface-border">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <Link href="/">
              <Button variant="ghost">← Back</Button>
            </Link>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold text-neutral-50">
                  {title || 'Loading…'}
                </h1>
                {symbol ? <Badge>{symbol}</Badge> : null}
                {archived ? <Badge tone="warn">archived</Badge> : null}
              </div>
              <p className="mt-0.5 text-xs text-muted tabular">
                {asOf ? `Prices as of ${shortDate(asOf)}` : 'No prices stored yet'}
              </p>
            </div>
          </div>

          {onTrade ? (
            <div className="flex flex-wrap items-center gap-2">
              <Link href="/transactions">
                <Button variant="ghost">Trade history</Button>
              </Link>
              <Button variant="primary" onClick={onTrade}>
                Record trade
              </Button>
            </div>
          ) : null}
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6">{children}</main>
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted">
      {children}
    </h2>
  )
}

function Figure({ label, value, hint, tone }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={cn('mt-0.5 tabular text-sm font-medium', tone ? toneClass[tone] : 'text-neutral-100')}>
        {value}
      </div>
      {hint ? <div className="text-[11px] text-muted">{hint}</div> : null}
    </div>
  )
}

function Line({ label, value, neutral }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span
        className={cn(
          'tabular',
          neutral ? 'text-neutral-200' : toneClass[toneOf(value)]
        )}
      >
        {neutral ? money(value) : signedMoney(value)}
      </span>
    </div>
  )
}
