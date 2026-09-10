import Head from 'next/head'
import Link from 'next/link'
import { useMemo, useRef, useState } from 'react'

import PortfolioSwitcher, { usePortfolio } from '../components/v2/PortfolioSwitcher'
import { Badge, Button, Card, Stat, cn } from '../components/v2/primitives'
import { api } from '../lib/api'
import { money, quantity, shortDate } from '../lib/format'

const STATUS_TONE = {
  ok: 'gain',
  new: 'warn',
  duplicate: 'neutral',
  error: 'loss',
}

const STATUS_LABEL = {
  ok: 'Ready',
  new: 'New stock',
  duplicate: 'Already applied',
  error: 'Blocked',
}

export default function ImportTrades() {
  const [plan, setPlan] = useState(null)
  const [fileName, setFileName] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [excluded, setExcluded] = useState(new Set())
  const fileInput = useRef(null)

  const {
    portfolios,
    activeId,
    select: selectPortfolio,
    reload: reloadPortfolios,
  } = usePortfolio()

  const activeName =
    portfolios.find((p) => p.id === activeId)?.name || 'the active portfolio'

  const toggleRow = (rowNumber) =>
    setExcluded((prev) => {
      const next = new Set(prev)
      next.has(rowNumber) ? next.delete(rowNumber) : next.add(rowNumber)
      return next
    })

  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    setPlan(null)
    setFileName(file.name)
    try {
      const next = await api.previewImport(file)
      // A ticker that nearly matches something already tracked is far more
      // often a typo than a new holding, so it starts unchecked: creating
      // BAJFIN.NS alongside BAJFINANCE.NS should take a deliberate click.
      setExcluded(
        new Set(
          next.rows
            .filter((r) => r.suggestions?.length)
            .map((r) => r.rowNumber)
        )
      )
      setPlan(next)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!plan) return
    const rows = plan.rows.filter(
      (r) => (r.status === 'ok' || r.status === 'new') && !excluded.has(r.rowNumber)
    )
    setBusy(true)
    setError(null)
    try {
      const res = await api.applyImport(rows)
      setResult(res)
      setPlan(null)
      setFileName(null)
      if (fileInput.current) fileInput.current.value = ''
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const counts = plan?.counts
  const applicable = plan
    ? plan.rows.filter(
        (r) =>
          (r.status === 'ok' || r.status === 'new') && !excluded.has(r.rowNumber)
      ).length
    : 0

  const willCreate = plan
    ? [
        ...new Set(
          plan.rows
            .filter((r) => r.status === 'new' && !excluded.has(r.rowNumber))
            .map((r) => r.symbol)
        ),
      ]
    : []

  const rows = useMemo(() => {
    if (!plan) return []
    // Problems first: they are the only thing needing a decision.
    const rank = { error: 0, new: 1, duplicate: 2, ok: 3 }
    return [...plan.rows].sort(
      (a, b) => rank[a.status] - rank[b.status] || a.rowNumber - b.rowNumber
    )
  }, [plan])

  return (
    <div className="min-h-screen bg-surface text-neutral-200 antialiased">
      <Head>
        <title>Import trades</title>
      </Head>

      <header className="border-b border-surface-border">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-neutral-50">
              Import trades
            </h1>
            <p className="mt-0.5 text-xs text-muted">
              {fileName || 'Upload a spreadsheet to review before anything is saved'}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <PortfolioSwitcher
              portfolios={portfolios}
              activeId={activeId}
              onSelect={(id) => {
                selectPortfolio(id)
                // A plan resolved against one portfolio means nothing in
                // another: the same ticker may be tracked in one and not the
                // other, and the timeline it was validated against differs.
                setPlan(null)
                setFileName(null)
                setResult(null)
                if (fileInput.current) fileInput.current.value = ''
              }}
              onChanged={reloadPortfolios}
            />
            <Link href="/transactions">
              <Button variant="ghost">Trade history</Button>
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

        {result ? (
          <div className="mb-4 rounded-md border border-gain/30 bg-gain/10 px-4 py-3 text-sm text-gain">
            Applied {result.applied} trades
            {result.instrumentsCreated
              ? `, created ${result.instrumentsCreated} new stock${result.instrumentsCreated === 1 ? '' : 's'}`
              : ''}
            {result.skipped ? `, skipped ${result.skipped}` : ''}.{' '}
            <Link href="/transactions" className="underline">
              View them in trade history
            </Link>
            .
          </div>
        ) : null}

        {!plan ? (
          <Card className="p-6">
            <h2 className="text-sm font-semibold text-neutral-100">
              Choose a file
            </h2>
            <p className="mt-1 text-sm text-muted">
              .xlsx, .xls or .csv. Trades will be added to{' '}
              <strong className="text-neutral-300">{activeName}</strong>. Nothing
              is written until you review and confirm.
            </p>

            <input
              ref={fileInput}
              type="file"
              accept=".xlsx,.xls,.csv"
              disabled={busy}
              onChange={(e) => upload(e.target.files?.[0])}
              className={cn(
                'mt-4 block w-full text-sm text-muted',
                'file:mr-3 file:rounded-md file:border-0 file:bg-white file:px-3 file:py-1.5',
                'file:text-sm file:font-medium file:text-surface hover:file:bg-neutral-200'
              )}
            />
            {busy ? (
              <p className="mt-3 text-sm text-muted">Reading the sheet…</p>
            ) : null}

            <div className="mt-6 border-t border-surface-border pt-4">
              <h3 className="text-xs font-medium uppercase tracking-wider text-muted">
                Required columns
              </h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {['Ticker', 'Type', 'Quantity', 'Date', 'Price'].map((c) => (
                  <Badge key={c}>{c}</Badge>
                ))}
              </div>
              <h3 className="mt-4 text-xs font-medium uppercase tracking-wider text-muted">
                Optional
              </h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {['Fees', 'Note', 'Reference'].map((c) => (
                  <Badge key={c}>{c}</Badge>
                ))}
              </div>
              <ul className="mt-4 space-y-1.5 text-xs text-muted">
                <li>
                  <strong className="text-neutral-300">Price</strong> is what you
                  actually bought or sold at. Without it cost basis and realised
                  gain cannot be computed, so it is not optional and never
                  guessed.
                </li>
                <li>
                  <strong className="text-neutral-300">Date</strong> must be
                  unambiguous — <code>2025-09-15</code> or{' '}
                  <code>15-Sep-2025</code>. A form like 03/04/2025 is two
                  different days depending on locale and is rejected rather than
                  assumed.
                </li>
                <li>
                  <strong className="text-neutral-300">Reference</strong> lets
                  the same sheet be uploaded twice safely: rows whose reference
                  is already recorded are skipped instead of duplicated.
                </li>
                <li>
                  Header names are flexible — Qty, Shares, Rate, Action, Symbol
                  and similar are all understood.
                </li>
              </ul>
            </div>
          </Card>
        ) : (
          <>
            <Card className="mb-6">
              <div className="grid grid-cols-2 divide-x divide-surface-border md:grid-cols-4">
                <Stat
                  label="Rows"
                  value={String(counts.total)}
                  hint={`from ${fileName}`}
                />
                <Stat
                  label="Ready to apply"
                  value={String(applicable)}
                  tone={applicable ? 'gain' : 'flat'}
                  hint={counts.new ? `${counts.new} on new stocks` : undefined}
                />
                <Stat
                  label="Blocked"
                  value={String(counts.error)}
                  tone={counts.error ? 'loss' : 'flat'}
                />
                <Stat
                  label="Already applied"
                  value={String(counts.duplicate)}
                />
              </div>
            </Card>

            {willCreate.length ? (
              <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                Will create {willCreate.length} new stock
                {willCreate.length === 1 ? '' : 's'}: {willCreate.join(', ')}.
                Prices for these are fetched on the next refresh, so they show
                no market value until then.
              </div>
            ) : null}

            {counts.error ? (
              <div className="mb-4 rounded-md border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">
                {counts.error} row{counts.error === 1 ? '' : 's'} cannot be
                applied and will be left out. Fix them in the sheet and upload
                again if they matter.
              </div>
            ) : null}

            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-border">
                      <th className="w-8 px-3 py-2" />
                      {['Row', 'Status', 'Ticker', 'Resolved', 'Type', 'Date',
                        'Qty', 'Price', 'Notes'].map((h) => (
                        <th
                          key={h}
                          className={cn(
                            'px-3 py-2 text-[11px] font-medium uppercase tracking-wider text-muted',
                            ['Qty', 'Price'].includes(h)
                              ? 'text-right'
                              : 'text-left'
                          )}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr
                        key={r.rowNumber}
                        className={cn(
                          'border-b border-surface-border/60 last:border-0',
                          excluded.has(r.rowNumber) && 'opacity-45'
                        )}
                      >
                        <td className="px-3 py-2">
                          {r.status === 'ok' || r.status === 'new' ? (
                            <input
                              type="checkbox"
                              checked={!excluded.has(r.rowNumber)}
                              onChange={() => toggleRow(r.rowNumber)}
                              aria-label={`Include row ${r.rowNumber}`}
                              className="h-3.5 w-3.5 accent-white"
                            />
                          ) : null}
                        </td>
                        <td className="px-3 py-2 tabular text-muted">
                          {r.rowNumber}
                        </td>
                        <td className="px-3 py-2">
                          <Badge tone={STATUS_TONE[r.status]}>
                            {STATUS_LABEL[r.status]}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-neutral-100">
                          {r.rawSymbol || '—'}
                        </td>
                        <td className="px-3 py-2 text-muted">
                          {r.symbol || '—'}
                        </td>
                        <td className="px-3 py-2">{r.type || '—'}</td>
                        <td className="whitespace-nowrap px-3 py-2 tabular">
                          {r.tradeDate ? shortDate(r.tradeDate) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right tabular">
                          {r.quantity ? quantity(r.quantity) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right tabular">
                          {r.price ? money(r.price, { precise: true }) : '—'}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {r.errors.map((e, i) => (
                            <div key={`e${i}`} className="text-loss">
                              {e}
                            </div>
                          ))}
                          {r.warnings.map((w, i) => (
                            <div key={`w${i}`} className="text-amber-400">
                              {w}
                            </div>
                          ))}
                          {!r.errors.length && !r.warnings.length ? (
                            <span className="text-muted">—</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <div className="mt-4 flex items-center justify-between gap-4">
              <p className="text-xs text-muted">
                Sells are checked against the whole timeline, including trades
                already recorded. If a stock&apos;s rows would ever overdraw the
                position, all of that stock&apos;s rows are held back rather
                than applying an arbitrary subset.
              </p>
              <div className="flex shrink-0 gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setPlan(null)
                    setFileName(null)
                    if (fileInput.current) fileInput.current.value = ''
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={busy || applicable === 0}
                  onClick={apply}
                >
                  {busy
                    ? 'Applying…'
                    : `Apply ${applicable} trade${applicable === 1 ? '' : 's'}`}
                </Button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
