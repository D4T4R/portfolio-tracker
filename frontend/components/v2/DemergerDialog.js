import { useEffect, useMemo, useState } from 'react'

import { api } from '../../lib/api'
import { money, quantity } from '../../lib/format'
import { Button, Field, Input, Modal } from './primitives'

/**
 * Records a demerger: the parent keeps part of its cost basis and the rest
 * moves to the company spun out of it.
 *
 * There is no feed to sync this from - the apportionment is published by the
 * company and cannot be recovered from prices - so it is typed in, and the
 * figures it will produce are shown before anything is written.
 */
export default function DemergerDialog({ open, onClose, holdings, onApplied }) {
  const [parentId, setParentId] = useState('')
  const [childId, setChildId] = useState('')
  const [exDate, setExDate] = useState('')
  const [retained, setRetained] = useState('')
  const [suspects, setSuspects] = useState([])
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setError(null)
    // Advisory: the unexplained falls only hint at which holding to pick, so
    // failing to fetch them should not stop the form being usable.
    api
      .corporateActionSuspects()
      .then((body) => setSuspects(body.suspects))
      .catch(() => setSuspects([]))
  }, [open])

  const options = useMemo(
    () =>
      [...(holdings || [])].sort((a, b) =>
        a.instrument.name.localeCompare(b.instrument.name)
      ),
    [holdings]
  )

  const parent = options.find((h) => h.instrument.id === parentId)
  const child = options.find((h) => h.instrument.id === childId)
  const fraction = Number(retained) / 100

  // Computed by the server and rolled back, rather than derived here. The
  // parent's cost may already carry an earlier recording of this same
  // demerger, and reproducing when to unwind that - in floating point - is how
  // the preview ends up disagreeing with what gets stored.
  useEffect(() => {
    if (!parentId || !childId || !exDate || !(fraction > 0 && fraction < 1)) {
      setPreview(null)
      return undefined
    }

    let cancelled = false
    const timer = setTimeout(() => {
      api
        .recordDemerger({
          parentId,
          childId,
          exDate,
          costRetained: String(fraction),
          preview: true,
        })
        .then((r) => !cancelled && (setPreview(r), setError(null)))
        .catch((e) => !cancelled && (setPreview(null), setError(e.message)))
    }, 250)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [parentId, childId, exDate, fraction])

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result = await api.recordDemerger({
        parentId,
        childId,
        exDate,
        // Sent as a fraction: the field asks for a percentage because that is
        // how companies publish it, but the API takes 0..1.
        costRetained: String(fraction),
      })
      onClose()
      onApplied(
        `${parent.instrument.symbol} kept ${money(result.parentCostAfter)} of ` +
          `${money(result.parentCostBefore)}; ${money(result.childCost)} moved to ` +
          `${child.instrument.symbol} at ${money(result.childPerShare, { precise: true })} ` +
          `per share across ${quantity(result.sharesReceived)} shares.`
      )
      setParentId('')
      setChildId('')
      setExDate('')
      setRetained('')
      setPreview(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const selectClass =
    'w-full rounded-md border border-surface-border bg-surface px-3 py-1.5 ' +
    'text-sm text-neutral-100 focus:border-neutral-500 focus:outline-none'

  return (
    <Modal open={open} onClose={onClose} title="Record a demerger">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-xs text-muted">
          A demerger hands you shares without taking more money, so the parent
          and the new company must together cost what the parent alone cost
          before. Booking the new shares as a purchase invents capital and
          drags down every return figure.
        </p>

        {suspects.length ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            <div className="mb-1 font-medium">Unexplained falls</div>
            {suspects.map((s) => (
              <button
                key={s.instrumentId}
                type="button"
                onClick={() => setParentId(s.instrumentId)}
                className="block text-left underline-offset-2 hover:underline"
              >
                {s.name} — down {s.dropPct}% on cost
              </button>
            ))}
            <div className="mt-1 text-amber-300/70">
              Click one to set it as the parent. A genuine decline looks exactly
              the same from here, so only pick a name you know demerged.
            </div>
          </div>
        ) : null}

        <Field label="Parent (the company that demerged)">
          <select
            required
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            className={selectClass}
          >
            <option value="">Select a holding…</option>
            {options.map((h) => (
              <option key={h.instrument.id} value={h.instrument.id}>
                {h.instrument.name} · {money(h.costBasis)} cost
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Demerged company (the shares you received)"
          hint="Must already be a holding. Add it and record the shares received first."
        >
          <select
            required
            value={childId}
            onChange={(e) => setChildId(e.target.value)}
            className={selectClass}
          >
            <option value="">Select a holding…</option>
            {options
              .filter((h) => h.instrument.id !== parentId)
              .map((h) => (
                <option key={h.instrument.id} value={h.instrument.id}>
                  {h.instrument.name} · {quantity(h.quantity)} shares
                </option>
              ))}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Ex-date">
            <Input
              required
              type="date"
              value={exDate}
              onChange={(e) => setExDate(e.target.value)}
            />
          </Field>
          <Field label="Cost kept by parent (%)">
            <Input
              required
              type="number"
              step="0.01"
              min="0.01"
              max="99.99"
              placeholder="89.66"
              value={retained}
              onChange={(e) => setRetained(e.target.value)}
            />
          </Field>
        </div>

        {preview ? (
          <div className="rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-neutral-300">
            <div className="flex justify-between">
              <span>{parent.instrument.symbol} cost before</span>
              <span className="tabular">{money(preview.parentCostBefore)}</span>
            </div>
            <div className="flex justify-between">
              <span>{parent.instrument.symbol} keeps</span>
              <span className="tabular">{money(preview.parentCostAfter)}</span>
            </div>
            <div className="flex justify-between">
              <span>{child.instrument.symbol} receives</span>
              <span className="tabular">{money(preview.childCost)}</span>
            </div>
            <div className="mt-1 flex justify-between border-t border-surface-border pt-1 text-muted">
              <span>{quantity(preview.sharesReceived)} shares at</span>
              <span className="tabular">
                {money(preview.childPerShare, { precise: true })}
              </span>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
            {error}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !preview}>
            {busy ? 'Applying…' : 'Apply'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
