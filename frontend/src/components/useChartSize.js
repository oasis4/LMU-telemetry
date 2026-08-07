import { onBeforeUnmount, onMounted, watch } from 'vue'

/**
 * Keep a uPlot instance the width of its host element.
 *
 * Three triggers, because no single one covers every case:
 *
 *  - `window.resize` catches the viewport changing, and is the one mechanism
 *    that works everywhere.
 *  - a `ResizeObserver` catches the layout reflowing without the window
 *    changing - a sidebar collapsing, a panel opening. It is the better
 *    mechanism where it runs, but it was observed never firing in one
 *    embedded browser, so it is an addition rather than the foundation.
 *  - a fit after every data change, because a chart built while its card was
 *    hidden or narrow keeps that width until something else nudges it.
 *
 * All three call one function that measures `host.clientWidth`. That is only
 * trustworthy because `.card` sets `min-width: 0`: without it a flex or grid
 * item will not shrink below its content, an oversized canvas holds the card
 * open, and the measurement reads the stale width straight back.
 */
export function useChartSize(host, chart, height, watchSource) {
  let observer = null

  function fit() {
    if (!chart.value || !host.value) return
    const width = Math.floor(host.value.clientWidth)
    // A one-pixel difference is a rounding artefact, not a resize; acting on
    // it can make an observer fire again and never settle.
    if (width > 0 && Math.abs(chart.value.width - width) > 1) {
      chart.value.setSize({ width, height: height() })
    }
  }

  onMounted(() => {
    fit()
    window.addEventListener('resize', fit)
    if (typeof ResizeObserver !== 'undefined' && host.value) {
      observer = new ResizeObserver(fit)
      observer.observe(host.value)
    }
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', fit)
    observer?.disconnect()
    observer = null
  })

  if (watchSource) watch(watchSource, () => fit(), { flush: 'post' })

  return fit
}
