import { useState } from 'react'

import { Button, Field, Input, Modal } from './primitives'
import { money, quantity as fmtQty } from '../../lib/format'

const today = () => new Date().toISOString().slice(0, 10)

/**
 * Registers a purchase or sale against one instrument (point 2).
 *
 * Server-side validation is authoritative - it replays the whole ledger and
 * will reject a back-dated sell that strands a later trade - so errors are
 * surfaced verbatim rather than reimplemented here.
 */
export default function TradeDialog({ open, onClose, holding, onSubmit }) {
  const [type, setType] = useState('BUY')
  const [tradeDate, setTradeDate] = useState(today())
  const [qty, setQty] = useState('')
  const [price, setPrice] = useState('')
  const [fees, setFees] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (!holding) return null

  const held = Number(holding.quantity)

  const reset = () => {
    setType('BUY')
    setTradeDate(today())
    setQty('')
    setPrice('')
    setFees('')
    setNote('')
    setError(null)
  }

  const close = () => {
    reset()
    onClose()
  }

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await onSubmit(holding.instrument.id, {
        type,
        tradeDate,
        quantity: qty,
        price,
        fees: fees || '0',
        note: note || null,
      })
      close()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const estimate =
    qty && price ? money(Number(qty) * Number(price) + Number(fees || 0)) : null

  return (
    <Modal
      open={open}
      onClose={close}
      title={`${holding.instrument.name} · ${holding.instrument.symbol}`}
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          {['BUY', 'SELL'].map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setType(option)}
              className={
                'rounded-md border px-3 py-2 text-sm font-medium transition-colors ' +
                (type === option
                  ? option === 'BUY'
                    ? 'border-gain/50 bg-gain/10 text-gain'
                    : 'border-loss/50 bg-loss/10 text-loss'
                  : 'border-surface-border text-muted hover:text-neutral-200')
              }
            >
              {option === 'BUY' ? 'Buy / add on' : 'Sell'}
            </button>
          ))}
        </div>

        <div className="text-xs text-muted tabular">
          Currently holding {fmtQty(holding.quantity)} at avg{' '}
          {money(holding.averageCost, { precise: true })}
        </div>

        <Field label="Trade date">
          <Input
            type="date"
            required
            max={today()}
            value={tradeDate}
            onChange={(e) => setTradeDate(e.target.value)}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity">
            <Input
              type="number"
              step="any"
              min="0"
              required
              placeholder="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </Field>
          <Field label="Price per share">
            <Input
              type="number"
              step="any"
              min="0"
              required
              placeholder="0.00"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Fees" hint="Brokerage, STT and stamp duty combined.">
          <Input
            type="number"
            step="any"
            min="0"
            placeholder="0.00"
            value={fees}
            onChange={(e) => setFees(e.target.value)}
          />
        </Field>

        <Field label="Note">
          <Input
            placeholder="optional"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>

        {type === 'SELL' && qty && Number(qty) > held ? (
          <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
            Selling {fmtQty(qty)} but only {fmtQty(held)} held on the books.
          </div>
        ) : null}

        {estimate ? (
          <div className="flex justify-between rounded-md bg-surface px-3 py-2 text-xs">
            <span className="text-muted">
              {type === 'BUY' ? 'Total cost' : 'Gross proceeds'}
            </span>
            <span className="tabular text-neutral-100">{estimate}</span>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2 text-xs text-loss">
            {error}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Saving…' : `Record ${type.toLowerCase()}`}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
