import { useEffect, useState } from 'react'

import { FundamentalsUnavailable, NotScreened, api } from '../../lib/api'
import { money, percent } from '../../lib/format'
import { Badge, Card, cn } from './primitives'

const VERDICT_TONE = { BUY: 'gain', SELL: 'loss', HOLD: 'neutral', UNKNOWN: 'neutral' }

const TIER_TONE = {
  'High conviction': 'gain',
  'Below entry price': 'gain',
  'Re-rating': 'warn',
}

/**
 * Screening from MCFinEx, alongside the position.
 *
 * These are signals for a human to weigh, not a recommendation - the same
 * stance MCFinEx itself takes. The panel says so, carries the disclaimer the
 * API sends, and never colours a whole company green.
 *
 * The service is started on demand, so being unable to reach it is an ordinary
 * state to render rather than an error to shout about.
 */
export default function FundamentalsPanel({ symbol }) {
  const [data, setData] = useState(null)
  const [state, setState] = useState('loading')

  useEffect(() => {
    if (!symbol) return undefined
    let cancelled = false

    setState('loading')
    api
      .fundamentals(symbol)
      .then((body) => {
        if (cancelled) return
        setData(body)
        setState('ready')
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof NotScreened) setState('not-screened')
        else if (err instanceof FundamentalsUnavailable) setState('offline')
        else setState('error')
        setData({ message: err.message })
      })

    return () => {
      cancelled = true
    }
  }, [symbol])

  if (state !== 'ready') {
    return (
      <Card className="p-4">
        <Header />
        <p className="mt-2 text-xs text-muted">
          {state === 'loading'
            ? 'Loading screening…'
            : state === 'not-screened'
              ? `${symbol.replace(/\.(NS|BO)$/i, '')} is not in the screened universe. Scrape it in MCFinEx to see it here.`
              : state === 'offline'
                ? 'MCFinEx is not running. Start it with `mcfinex-api` and reload — nothing else on this page depends on it.'
                : data?.message}
        </p>
      </Card>
    )
  }

  const trends = data.trends || []
  const signals = (data.signals || []).filter((s) => s.available)
  const unavailable = (data.signals || []).length - signals.length

  return (
    <Card className="p-4">
      <Header sector={data.sector} tier={data.tier} />

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure label="Screened price" value={money(data.price)} />
        <Figure
          label="Target"
          value={money(data.target)}
          hint={data.upside_pct != null ? `${percent(data.upside_pct)} upside` : null}
        />
        <Figure label="Entry ¾" value={money(data.entry_3by4)} />
        <Figure label="Entry ⅔" value={money(data.entry_2by3)} />
      </div>

      {trends.length ? (
        <div className="mt-4">
          <SectionLabel>Last eight quarters</SectionLabel>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-muted">
                <th className="py-1 text-left font-medium">Line</th>
                <th className="py-1 text-right font-medium">TTM</th>
                <th className="py-1 text-right font-medium">vs prior</th>
                <th className="py-1 text-right font-medium">Next</th>
              </tr>
            </thead>
            <tbody>
              {trends.map((t) => (
                <tr key={t.label} className="border-t border-surface-border/60">
                  <td className="py-1.5">
                    <span className="text-neutral-200">{t.label}</span>
                    <Sparkline values={t.values} />
                  </td>
                  <td className="py-1.5 text-right tabular">{money(t.ttm)}</td>
                  <td
                    className={cn(
                      'py-1.5 text-right tabular',
                      Number(t.ttm_growth_pct) >= 0 ? 'text-gain' : 'text-loss'
                    )}
                  >
                    {percent(t.ttm_growth_pct)}
                  </td>
                  <td className="py-1.5 text-right tabular text-muted">
                    {money(t.forecast)}
                    {/* A forecast without its confidence invites more weight
                        than an eight-point extrapolation can carry. */}
                    <span className="ml-1 text-[10px] uppercase">
                      {t.confidence}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {signals.length ? (
        <div className="mt-4">
          {/* Worded as what it actually counts. MCFinEx scores the business
              screens only, so a bare "4 buy" above a list where eight rows
              read BUY looks like a broken tally - the other four are about
              the price, and are deliberately outside the score. */}
          <SectionLabel>
            {data.buy_signals} of {data.scored} business screens say buy,{' '}
            {data.sell_signals} say sell
          </SectionLabel>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {signals.map((s) => (
              <div
                key={s.key}
                className="flex items-start justify-between gap-2 rounded border border-surface-border bg-surface px-2 py-1.5"
              >
                <div className="min-w-0">
                  <div className="truncate text-xs text-neutral-200">{s.label}</div>
                  <div className="truncate text-[11px] text-muted">{s.rule}</div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="tabular text-xs text-neutral-300">{s.value}</span>
                  <Badge tone={VERDICT_TONE[s.verdict]}>{s.verdict}</Badge>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-muted">
            Valuation signals are listed too but sit outside that count: they
            describe the price, which moves daily, rather than the business.
            {unavailable
              ? ` ${unavailable} more had no data to score and were left out rather than read as neutral.`
              : ''}
          </p>
        </div>
      ) : null}

      {data.disclaimer ? (
        <p className="mt-4 border-t border-surface-border pt-3 text-[11px] leading-relaxed text-muted">
          {data.disclaimer}
        </p>
      ) : null}
    </Card>
  )
}

function Header({ sector, tier }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-neutral-100">Fundamentals</h2>
        <span className="text-[11px] text-muted">MCFinEx screening</span>
      </div>
      <div className="flex items-center gap-2">
        {sector ? <span className="text-xs text-muted">{sector}</span> : null}
        {/* MCFinEx spells "did not qualify" as the tier "None". Rendered as a
            badge it reads like a missing value rather than a verdict, so it
            gets words instead. */}
        {tier === 'None' ? (
          <span className="text-xs text-muted">Did not qualify</span>
        ) : tier ? (
          <Badge tone={TIER_TONE[tier] || 'neutral'}>{tier}</Badge>
        ) : null}
      </div>
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
      {children}
    </div>
  )
}

function Figure({ label, value, hint }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5 tabular text-sm text-neutral-100">{value}</div>
      {hint ? <div className="text-[11px] text-muted">{hint}</div> : null}
    </div>
  )
}

/**
 * Eight bars, drawn against the largest value in the series.
 *
 * Deliberately unlabelled and small: it shows shape, and any reading finer
 * than "rising or not" belongs in the numbers beside it.
 */
function Sparkline({ values }) {
  const numbers = (values || []).map(Number).filter((n) => !Number.isNaN(n))
  if (numbers.length < 2) return null

  const peak = Math.max(...numbers.map(Math.abs))
  if (peak === 0) return null

  return (
    <span className="mt-1 flex h-4 items-end gap-px">
      {numbers.map((n, i) => (
        <span
          key={i}
          style={{ height: `${Math.max(8, (Math.abs(n) / peak) * 100)}%` }}
          className={cn('w-1.5 rounded-sm', n < 0 ? 'bg-loss/60' : 'bg-muted/50')}
        />
      ))}
    </span>
  )
}
