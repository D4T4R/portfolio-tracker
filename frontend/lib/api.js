// Client for the ledger API. Kept free of formatting concerns: every numeric
// field stays a string exactly as the server sent it.

// Relative by default so the API is whatever origin served the page. Next
// rewrites /api/* to the Flask port (see next.config.js), which keeps this
// working when the dashboard is opened from another device on the network —
// an absolute localhost URL would resolve to that device, not this machine.
const BASE = process.env.NEXT_PUBLIC_LEDGER_API || '/api/v2'

// The portfolio every scoped call is made against. Held here rather than
// threaded through each caller, and sent explicitly on the wire so the server
// keeps no "current portfolio" state - two tabs on different books would
// otherwise overwrite each other's idea of which is current.
let activePortfolioId = null

export function setActivePortfolio(id) {
  activePortfolioId = id || null
}

export function getActivePortfolio() {
  return activePortfolioId
}

function scoped(path) {
  if (!activePortfolioId) return path
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}portfolioId=${encodeURIComponent(activePortfolioId)}`
}

async function request(path, options = {}) {
  // A FormData body must set its own Content-Type: the browser appends the
  // multipart boundary, and overriding it leaves the server unable to split
  // the parts.
  const isUpload = options.body instanceof FormData
  const response = await fetch(`${BASE}${path}`, {
    headers: isUpload ? undefined : { 'Content-Type': 'application/json' },
    ...options,
  })

  if (response.status === 204) return null

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    // The API returns {error} for anything it rejected deliberately.
    throw new Error(body?.error || `Request failed (${response.status})`)
  }
  return body
}

export const api = {
  // Portfolio management. These are deliberately unscoped: they are how the
  // caller discovers and changes which portfolio the rest operate on.
  portfolios: () => request('/portfolios'),

  createPortfolio: (name) =>
    request('/portfolios', { method: 'POST', body: JSON.stringify({ name }) }),

  renamePortfolio: (id, name) =>
    request(`/portfolios/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),

  deletePortfolio: (id) => request(`/portfolios/${id}`, { method: 'DELETE' }),

  portfolio: (includeArchived = false) =>
    request(scoped(`/portfolio?includeArchived=${includeArchived}`)),

  instruments: (includeArchived = false) =>
    request(scoped(`/instruments?includeArchived=${includeArchived}`)),

  addInstrument: (symbol, name) =>
    request(scoped('/instruments'), {
      method: 'POST',
      body: JSON.stringify({ symbol, name }),
    }),

  archive: (id) =>
    request(scoped(`/instruments/${id}/archive`), { method: 'POST' }),
  unarchive: (id) =>
    request(scoped(`/instruments/${id}/unarchive`), { method: 'POST' }),

  transactions: (id) => request(scoped(`/instruments/${id}/transactions`)),

  // Split in two deliberately: detail answers from the local database, while
  // history reaches the price feed and can be rate limited. One call would
  // mean a 429 upstream leaving the page with no holdings either.
  instrumentDetail: (id) => request(scoped(`/instruments/${id}/detail`)),

  instrumentHistory: (id, range = '1y') =>
    request(scoped(`/instruments/${id}/history?range=${encodeURIComponent(range)}`)),

  allTransactions: () => request(scoped('/transactions')),

  recordTrade: (id, trade) =>
    request(scoped(`/instruments/${id}/transactions`), {
      method: 'POST',
      body: JSON.stringify(trade),
    }),

  deleteTrade: (txnId) =>
    request(scoped(`/transactions/${txnId}`), { method: 'DELETE' }),

  refreshPrices: (force = false) =>
    request(scoped('/prices/refresh'), {
      method: 'POST',
      body: JSON.stringify({ force }),
    }),

  syncDividends: () => request(scoped('/dividends/sync'), { method: 'POST' }),

  syncCorporateActions: () =>
    request(scoped('/corporate-actions/sync'), { method: 'POST' }),

  corporateActionSuspects: () => request(scoped('/corporate-actions/suspects')),

  // costRetained is the fraction of the cost basis staying with the parent, as
  // published by the company. No feed carries it, hence the argument.
  //
  // With preview set the server computes and rolls back, so the figures shown
  // before applying are the ones that will be stored rather than a second,
  // floating-point approximation of them.
  recordDemerger: ({ parentId, childId, exDate, costRetained, preview = false }) =>
    request(scoped('/corporate-actions/demerger'), {
      method: 'POST',
      body: JSON.stringify({ parentId, childId, exDate, costRetained, preview }),
    }),

  dividends: (id) => request(scoped(`/instruments/${id}/dividends`)),

  capitalGains: () => request(scoped('/capital-gains')),

  priceAnomalies: () => request(scoped('/price-anomalies')),

  previewImport: (file) => {
    const form = new FormData()
    form.append('file', file)
    // Scoped on the query string: a multipart body has nowhere to put it.
    return request(scoped('/imports/preview'), { method: 'POST', body: form })
  },

  applyImport: (rows) =>
    request(scoped('/imports/apply'), {
      method: 'POST',
      body: JSON.stringify({ rows }),
    }),

  fundamentals: (symbol) => fundamentals(symbol),
}

// MCFinEx is a separate service with its own database, reached through a Next
// rewrite. Not part of `request` above because it does not live under the
// ledger's base path and is never scoped to a portfolio - the screening of a
// company is the same fact whoever holds it.
const MCFINEX_BASE = process.env.NEXT_PUBLIC_MCFINEX_API || '/api/mcfinex'

export class FundamentalsUnavailable extends Error {}
export class NotScreened extends Error {}

async function fundamentals(symbol) {
  // Screener names companies without an exchange suffix.
  const ticker = String(symbol).replace(/\.(NS|BO)$/i, '')

  let response
  try {
    response = await fetch(`${MCFINEX_BASE}/company/${encodeURIComponent(ticker)}`)
  } catch (err) {
    // The service being down is the ordinary case, not a fault: it is started
    // on demand. Distinguished from "not covered" so the panel can say which.
    throw new FundamentalsUnavailable(err.message)
  }

  if (response.status === 404) {
    throw new NotScreened(`${ticker} is not in the screened universe`)
  }
  // Any 5xx, not just the gateway codes: proxying to a port with nothing
  // behind it surfaces as a plain 500, and the reader's next step is the same
  // either way - check that MCFinEx is up.
  if (response.status >= 500) {
    throw new FundamentalsUnavailable(`MCFinEx did not answer (${response.status})`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `Fundamentals request failed (${response.status})`)
  }
  return response.json()
}
