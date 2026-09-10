import { useCallback, useEffect, useState } from 'react'

import { api, setActivePortfolio } from '../../lib/api'
import { Button, Field, Input, Modal } from './primitives'

// Remembered per browser so a reload lands back on the book you were reading.
// Deliberately not stored server-side: two tabs on different portfolios would
// otherwise overwrite each other's idea of which is current.
const STORAGE_KEY = 'portfolio-tracker.activePortfolio'

/**
 * Resolves which portfolio is active and keeps the API client in step.
 *
 * `ready` stays false until an id is settled, so a page can hold off loading
 * rather than firing a request against the default and then a second against
 * the real one - which would briefly show the wrong book's numbers.
 */
export function usePortfolio() {
  const [portfolios, setPortfolios] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async (preferred) => {
    try {
      const body = await api.portfolios()
      setPortfolios(body.portfolios)

      const remembered =
        preferred ||
        (typeof window !== 'undefined'
          ? window.localStorage.getItem(STORAGE_KEY)
          : null)
      // A remembered id can name a portfolio since deleted, so fall back
      // rather than leaving every request scoped to something gone.
      const exists = body.portfolios.some((p) => p.id === remembered)
      const chosen = exists ? remembered : body.activeId

      setActivePortfolio(chosen)
      setActiveId(chosen)
      setReady(true)
      return chosen
    } catch (err) {
      setError(err.message)
      setReady(true)
      return null
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const select = useCallback((id) => {
    setActivePortfolio(id)
    setActiveId(id)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, id)
    }
  }, [])

  return { portfolios, activeId, ready, error, select, reload: load }
}

export default function PortfolioSwitcher({ portfolios, activeId, onSelect, onChanged }) {
  const [creating, setCreating] = useState(false)

  if (!portfolios.length) return null

  const selectClass =
    'min-w-0 max-w-[45vw] rounded-md border border-surface-border bg-surface ' +
    'px-3 py-1.5 text-sm text-neutral-100 focus:border-neutral-500 focus:outline-none'

  return (
    <>
      <select
        value={activeId || ''}
        onChange={(e) => onSelect(e.target.value)}
        aria-label="Active portfolio"
        className={selectClass}
      >
        {portfolios.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <Button variant="ghost" onClick={() => setCreating(true)}>
        New portfolio
      </Button>

      <NewPortfolioDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={async (id) => {
          await onChanged(id)
          onSelect(id)
        }}
      />
    </>
  )
}

function NewPortfolioDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const created = await api.createPortfolio(name)
      setName('')
      onClose()
      await onCreated(created.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New portfolio">
      <form onSubmit={submit} className="space-y-3">
        <Field
          label="Name"
          hint="Holdings, trades and dividends are tracked separately per portfolio."
        >
          <Input
            required
            autoFocus
            placeholder="Long term"
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
            {busy ? 'Creating…' : 'Create'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
