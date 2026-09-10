/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      // Ahead of the catch-all below, since the first match wins. MCFinEx is a
      // separate service on its own port; proxying it rather than calling it
      // directly keeps the dashboard working from a phone, where an absolute
      // "127.0.0.1:8000" would mean the phone itself.
      {
        source: '/api/mcfinex/:path*',
        destination: 'http://127.0.0.1:8000/:path*'
      },
      {
        source: '/api/:path*',
        destination: 'http://localhost:5000/api/:path*'
      }
    ]
  }
}

module.exports = nextConfig
