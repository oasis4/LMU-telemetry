<script setup>
/**
 * One row of the corner overlay: a channel over distance, with the corner
 * shaded and the pedal points marked.
 *
 * Several of these are stacked on one distance axis, which is the whole point
 * - the brake point, the minimum speed and the delta that follows from them
 * are one event, and reading them as one event means they have to sit on the
 * same x. They share a cursor through uPlot's sync, so the crosshair is in
 * the same place in every row.
 *
 * A marker is drawn only where the metric exists. A lap with no brake point
 * in the corner gets no line rather than one at zero, because "did not brake"
 * and "braked at the start of the window" are different facts.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { useChartSize } from './useChartSize.js'
import { baseOptions, zeroLine } from './chart-theme.js'
import { showData } from './overlay-data.js'

const props = defineProps({
  distance: { type: Object, required: true },
  /** [{ values, label, stroke, width?, format? }] - drawn in order. */
  series: { type: Array, required: true },
  /** [{ from, to }] in metres, shaded behind the data. */
  bands: { type: Array, default: () => [] },
  /** [{ at, stroke, label? }] in metres, drawn as vertical rules on top. */
  markers: { type: Array, default: () => [] },
  yLabel: { type: String, required: true },
  yRange: { type: Array, default: null },
  zero: { type: Boolean, default: false },
  syncKey: { type: String, default: null },
  height: { type: Number, default: 130 },
  showAxis: { type: Boolean, default: true },
})

const host = ref(null)
const chart = shallowRef(null)

function bands(u) {
  const { ctx } = u
  ctx.save()
  ctx.fillStyle = 'rgba(200, 255, 0, 0.10)'
  for (const band of props.bands) {
    const left = u.valToPos(band.from, 'x', true)
    const right = u.valToPos(band.to, 'x', true)
    ctx.fillRect(left, u.bbox.top, right - left, u.bbox.height)
  }
  ctx.restore()
  if (props.zero) zeroLine(u)
}

function markers(u) {
  const { ctx } = u
  ctx.save()
  ctx.lineWidth = 1.5
  ctx.font = '10px system-ui, sans-serif'
  ctx.textBaseline = 'top'
  for (const marker of props.markers) {
    if (marker.at === null || marker.at === undefined) continue
    if (marker.at < u.scales.x.min || marker.at > u.scales.x.max) continue
    const x = Math.round(u.valToPos(marker.at, 'x', true)) + 0.5
    ctx.strokeStyle = marker.stroke
    ctx.beginPath()
    ctx.moveTo(x, u.bbox.top)
    ctx.lineTo(x, u.bbox.top + u.bbox.height)
    ctx.stroke()
    if (marker.label) {
      ctx.fillStyle = marker.stroke
      ctx.fillText(marker.label, x + 3, u.bbox.top + 2)
    }
  }
  ctx.restore()
}

function options() {
  const base = baseOptions({
    width: host.value.clientWidth || 800,
    height: props.height,
    xLabel: props.showAxis ? 'distance (m)' : '',
    yLabel: props.yLabel,
  })
  if (!props.showAxis) {
    // The stack shares one x, so only the bottom row spends 20 px naming it.
    base.axes[0] = { ...base.axes[0], values: () => [], labelSize: 0, size: 14 }
  }
  return {
    ...base,
    cursor: props.syncKey
      ? { ...base.cursor, sync: { key: props.syncKey, setSeries: false, scales: ['x', null] } }
      : base.cursor,
    scales: {
      x: { time: false },
      ...(props.yRange
        ? { y: { range: () => [props.yRange[0], props.yRange[1]] } }
        : {}),
    },
    series: [
      { label: 'distance' },
      ...props.series.map((s) => ({
        label: s.label,
        stroke: s.stroke,
        width: s.width ?? 1.75,
        value: (_u, v) => (s.format ? s.format(v) : v == null ? '--' : v.toFixed(1)),
      })),
    ],
    hooks: { drawClear: [bands], draw: [markers] },
  }
}

function data() {
  return [props.distance, ...props.series.map((s) => s.values)]
}

function build() {
  if (!host.value) return
  chart.value?.destroy()
  chart.value = new uPlot(options(), data(), host.value)
  // Stated on the freshly built chart too: with a synced cursor uPlot leaves
  // the x scale out of auto-ranging from the start, so a chart built while
  // another row already published a range would adopt that one.
  showData(chart.value, data())
}

onMounted(build)
onBeforeUnmount(() => chart.value?.destroy())
useChartSize(host, chart, () => props.height, () => [props.distance, props.series])

// One watcher for everything the chart draws, because two of them fought.
//
// The bands and markers had their own watcher calling `redraw()`. uPlot's
// `redraw` re-commits the scale values the chart currently holds - and a
// `setScale` from the same tick is still pending at that moment, so the
// re-commit put the old range back. The result was an axis exactly one corner
// behind the data, and after a couple of steps the data was outside the drawn
// range entirely and the rows were blank.
//
// `showData` redraws as part of setting the data, so the hooks that draw the
// band and the pedal-point rules run from here too.
watch(
  () => [props.distance, props.series, props.bands, props.markers],
  ([, series], [, previous]) => {
    // A different number of series, or differently named ones, is new series
    // metadata - which setData cannot carry.
    const sameShape =
      previous &&
      previous.length === series.length &&
      previous.every((s, i) => s.label === series[i].label)
    if (!chart.value || !sameShape) return build()
    showData(chart.value, data())
  },
)
</script>

<template>
  <div ref="host" class="chart" />
</template>

<style scoped>
.chart { width: 100%; }
</style>
