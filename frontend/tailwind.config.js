/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,jsx}',
    './components/**/*.{js,jsx}',
    './lib/**/*.{js,jsx}',
  ],
  // Chakra still ships its own CSS reset from _app.js while the old pages
  // exist. Two competing resets fight, so Tailwind's is off until Chakra goes.
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#0b0d10',
          raised: '#12161b',
          overlay: '#171c23',
          border: '#232a33',
        },
        gain: '#3fb950',
        loss: '#f85149',
        muted: '#8b949e',
      },
      fontFamily: {
        // Tabular figures matter: columns of money should align vertically.
        numeric: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
