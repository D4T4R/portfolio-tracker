import { useEffect, useRef, useState } from 'react'

import { cn } from './primitives'

// Matched to tailwind.config.js rather than guessed, so the chart does not
// read as a component borrowed from somewhere else.
const THEME = {
  background: '#12161b',
  grid: '#232a33',
  text: '#8b949e',
  gain: '#3fb950',
  loss: '#f85149',
  cost: '#8b949e',
}

const RANGES = ['1mo', '3mo', '6mo', '1y', '2y', '5y', 'max']
const RANGE_LABELS = { '1mo': '1M', '3mo': '3M', '6mo': '6M', '1y': '1Y', '2y': '2Y', '5y': '5Y', max: 'Max' }

/**
 * Candles with this book's own trades marked on them.
 *
 * The library is loaded on the client only: it measures the container to lay
 * out, and there is nothing to measure while rendering to a string on the
 * server.
 */
export default function PriceChart({ data, range, onRangeChange, loading }) {
  const container = useRef(null)
  const [failed, setFailed] = useState(null)

  useEffect(() => {
    if (!container.current || !data?.candles?.length) return undefined

    let chart = null
    let disposed = false
    let observer = null

    ;(async () => {
      try {
        const {
          createChart,
          CandlestickSeries,
          createSeriesMarkers,
          LineStyle,
          CrosshairMode,
        } = await import('lightweight-charts')
        if (disposed || !container.current) return

        chart = createChart(container.current, {
          layout: {
            background: { color: THEME.background },
            textColor: THEME.text,
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: THEME.grid },
            horzLines: { color: THEME.grid },
          },
          crosshair: { mode: CrosshairMode.Normal },
          rightPriceScale: { borderColor: THEME.grid },
          timeScale: { borderColor: THEME.grid, timeVisible: false },
          width: container.current.clientWidth,
          height: container.current.clientHeight,
          localization: {
            // Indian grouping, and no currency symbol: the axis is narrow and
            // the page has already said what currency this is.
            priceFormatter: (price) =>
              new Intl.NumberFormat('en-IN', {
                maximumFractionDigits: 2,
              }).format(price),
          },
        })

        const series = chart.addSeries(CandlestickSeries, {
          upColor: THEME.gain,
          downColor: THEME.loss,
          borderUpColor: THEME.gain,
          borderDownColor: THEME.loss,
          wickUpColor: THEME.gain,
          wickDownColor: THEME.loss,
        })

        // Strings on the wire, numbers here: the API sends money as strings so
        // Decimal never round trips through a float, but a canvas needs
        // numbers to scale. Converted once, not per frame.
        series.setData(
          data.candles.map((c) => ({
            time: c.date,
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
          }))
        )

        if (data.markers?.length) {
          createSeriesMarkers(
            series,
            data.markers.map((m) => ({
              time: m.date,
              position: m.type === 'BUY' ? 'belowBar' : 'aboveBar',
              color: m.type === 'BUY' ? THEME.gain : THEME.loss,
              shape: m.type === 'BUY' ? 'arrowUp' : 'arrowDown',
              text: `${m.type === 'BUY' ? '+' : '-'}${Number(m.quantity).toLocaleString('en-IN')} @ ${Number(m.price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`,
            }))
          )
        }

        const averageCost = Number(data.averageCost)
        if (averageCost > 0) {
          series.createPriceLine({
            price: averageCost,
            color: THEME.cost,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'avg cost',
          })
        }

        chart.timeScale().fitContent()

        // Watching the element rather than the window: the container also
        // changes width when the grid reflows at a breakpoint or a sibling
        // panel appears, neither of which fires a window resize. It fires
        // once immediately too, which settles the width the canvas was
        // created with before the layout had finished.
        observer = new ResizeObserver(([entry]) => {
          const width = Math.floor(entry.contentRect.width)
          if (width > 0) {
            chart.applyOptions({ width })
            chart.timeScale().fitContent()
          }
        })
        observer.observe(container.current)
      } catch (err) {
        setFailed(err.message)
      }
    })()

    return () => {
      disposed = true
      if (observer) observer.disconnect()
      if (chart) chart.remove()
    }
  }, [data])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-gain" />
            Buy
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-loss" />
            Sell
          </span>
          {/* The value is printed here, not only drawn. The price scale fits
              the candles and does not stretch to reach a price line, so a
              holding up fourfold has its cost line below the visible range -
              correct for the chart, useless as the only place it appears. */}
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-px w-3 bg-muted" />
            Avg cost{' '}
            {Number(data?.averageCost) > 0
              ? `₹${Number(data.averageCost).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
              : ''}
          </span>
        </div>

        <div className="flex flex-wrap gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => onRangeChange(r)}
              className={cn(
                'rounded px-2 py-1 text-xs font-medium transition-colors',
                r === range
                  ? 'bg-surface-overlay text-neutral-100'
                  : 'text-muted hover:text-neutral-200'
              )}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      <div className="relative h-[360px] w-full overflow-hidden rounded-md">
        <div ref={container} className="h-full w-full" />

        {loading || failed || data?.error || !data?.candles?.length ? (
          <div className="absolute inset-0 flex items-center justify-center rounded-md bg-surface-raised px-6 text-center text-sm text-muted">
            {loading
              ? 'Loading prices…'
              : failed || data?.error
                ? // The feed rate limits hard; saying so beats an empty frame.
                  `Chart unavailable — ${failed || data.error}`
                : 'No price history for this range.'}
          </div>
        ) : null}
      </div>
    </div>
  )
}
