// The API sends money as strings to avoid float drift. These helpers format
// for display only; nothing here should be used to compute with.

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

const INR_PRECISE = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function money(value, { precise = false } = {}) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return precise ? INR_PRECISE.format(n) : INR.format(n)
}

export function signedMoney(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return `${n >= 0 ? '+' : '-'}${INR.format(Math.abs(n))}`
}

export function percent(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

export function quantity(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  // Whole shares are the norm; only show decimals when they exist.
  return n % 1 === 0 ? n.toLocaleString('en-IN') : n.toLocaleString('en-IN', {
    maximumFractionDigits: 6,
  })
}

export function toneOf(value) {
  const n = Number(value)
  if (Number.isNaN(n) || n === 0) return 'flat'
  return n > 0 ? 'gain' : 'loss'
}

export const toneClass = {
  gain: 'text-gain',
  loss: 'text-loss',
  flat: 'text-muted',
}

export function shortDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}
