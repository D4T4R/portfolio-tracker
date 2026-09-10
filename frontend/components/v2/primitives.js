// Small shadcn-style primitives. Hand-written rather than generated, because
// the generator assumes the app router and this project is on pages.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}

const BUTTON_VARIANTS = {
  primary:
    'bg-white text-surface hover:bg-neutral-200 disabled:hover:bg-white',
  secondary:
    'bg-surface-overlay text-neutral-200 border border-surface-border hover:bg-surface-border',
  ghost: 'text-muted hover:text-neutral-100 hover:bg-surface-overlay',
  danger:
    'bg-transparent text-loss border border-loss/40 hover:bg-loss/10',
}

export function Button({
  variant = 'secondary',
  className,
  disabled,
  children,
  ...props
}) {
  return (
    <button
      disabled={disabled}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5',
        'text-sm font-medium transition-colors',
        'focus:outline-none focus:ring-2 focus:ring-neutral-500 focus:ring-offset-2 focus:ring-offset-surface',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        BUTTON_VARIANTS[variant],
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
}

export function Card({ className, children }) {
  return (
    <div
      className={cn(
        'rounded-lg border border-surface-border bg-surface-raised',
        className
      )}
    >
      {children}
    </div>
  )
}

export function Stat({ label, value, tone = 'flat', hint }) {
  const toneClass = {
    gain: 'text-gain',
    loss: 'text-loss',
    flat: 'text-neutral-100',
  }[tone]

  return (
    <div className="px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">
        {label}
      </div>
      <div className={cn('mt-1 text-xl font-semibold tabular', toneClass)}>
        {value}
      </div>
      {hint ? (
        <div className="mt-0.5 text-xs text-muted tabular">{hint}</div>
      ) : null}
    </div>
  )
}

export function Input({ className, ...props }) {
  return (
    <input
      className={cn(
        'w-full rounded-md border border-surface-border bg-surface px-3 py-1.5',
        'text-sm text-neutral-100 placeholder:text-muted',
        'focus:border-neutral-500 focus:outline-none',
        className
      )}
      {...props}
    />
  )
}

export function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  )
}

export function Badge({ tone = 'neutral', children }) {
  const tones = {
    neutral: 'bg-surface-overlay text-muted border-surface-border',
    gain: 'bg-gain/10 text-gain border-gain/30',
    loss: 'bg-loss/10 text-loss border-loss/30',
    warn: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5',
        'text-[11px] font-medium',
        tones[tone]
      )}
    >
      {children}
    </span>
  )
}

/**
 * A button that opens a list of actions.
 *
 * Positioned absolutely rather than fixed, so it stays anchored to its button
 * inside the animated wrapper _app.js puts around every page - the same
 * transformed ancestor that forces Modal below into a portal.
 */
export function Menu({ label, busyLabel, items, disabled, align = 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    // mousedown rather than click: a click listener fires after the button's
    // own handler has already toggled the menu back open.
    const onPointer = (e) => {
      if (!ref.current?.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <Button
        variant="primary"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {busyLabel || label}
        <span aria-hidden className="text-[10px] opacity-60">
          ▾
        </span>
      </Button>

      {open ? (
        <div
          role="menu"
          className={cn(
            'absolute z-40 mt-1 w-64 overflow-hidden rounded-md',
            'border border-surface-border bg-surface-raised shadow-2xl',
            align === 'right' ? 'right-0' : 'left-0'
          )}
        >
          {items.map((item) => (
            <button
              key={item.key}
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false)
                item.onSelect()
              }}
              className={cn(
                'block w-full border-b border-surface-border/60 px-3 py-2 text-left',
                'last:border-0 hover:bg-surface-overlay',
                'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
              )}
            >
              <span className="block text-sm font-medium text-neutral-100">
                {item.label}
              </span>
              {item.hint ? (
                <span className="mt-0.5 block text-xs text-muted">
                  {item.hint}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function Modal({ open, onClose, title, children }) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !mounted) return null

  // Rendered into <body> rather than in place. _app.js wraps every page in a
  // framer-motion element that animates transform and filter, and either of
  // those makes an ancestor the containing block for position:fixed - which
  // pins the dialog to the page instead of the viewport, far below the fold.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-surface-border bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-100">{title}</h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-neutral-100"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>,
    document.body
  )
}
