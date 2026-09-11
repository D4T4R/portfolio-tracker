/** @type {import('next').NextConfig} */

// Both APIs are proxied through this server rather than called from the
// browser. The dashboard only ever fetches its own origin, which keeps the
// backend URL out of the client bundle, keeps CORS out of the picture, and is
// what lets the page work from a phone - an absolute "localhost" in the client
// would mean the phone itself.
//
// Deliberately not NEXT_PUBLIC_: these are read here, on the server, and must
// not be inlined into client JavaScript.
function origin(name, fallback) {
  const value = (process.env[name] || fallback).trim()
  // A trailing slash would become a double slash in every destination below,
  // which some hosts answer with a redirect and others with a 404.
  return value.replace(/\/+$/, '')
}

const LEDGER_ORIGIN = origin('LEDGER_ORIGIN', 'http://localhost:5000')
const MCFINEX_ORIGIN = origin('MCFINEX_ORIGIN', 'http://127.0.0.1:8000')

// Once deployed, the localhost fallback resolves to the server running this
// build, where nothing is listening. Left to default, the site would go live
// looking healthy and fail every request with nothing in the UI to explain
// why. Refusing to build says it once, at the only moment it is cheap to fix.
if (process.env.VERCEL && !process.env.LEDGER_ORIGIN) {
  throw new Error(
    'LEDGER_ORIGIN is not set. Point it at the hosted backend, e.g. ' +
      'https://portfolio-api.example.com. Without it every /api request ' +
      'would be proxied to localhost inside the deployment.'
  )
}

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      // Ahead of the catch-all below, since the first match wins. MCFinEx is a
      // separate service with its own database.
      //
      // This entry stays in the list even when MCFINEX_ORIGIN is unset, rather
      // than being dropped: without it these calls fall through to the ledger,
      // which answers an unknown path with 404 - and the panel reads 404 as
      // "this company was never screened". An unreachable origin fails with a
      // 5xx instead, which is what the "MCFinEx is not running" message is
      // keyed on.
      {
        source: '/api/mcfinex/:path*',
        destination: `${MCFINEX_ORIGIN}/:path*`
      },
      {
        source: '/api/:path*',
        destination: `${LEDGER_ORIGIN}/api/:path*`
      }
    ]
  }
}

module.exports = nextConfig
