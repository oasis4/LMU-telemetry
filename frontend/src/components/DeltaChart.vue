<script setup>
/**
 * The delta over distance, with the corners marked behind it.
 *
 * One series, so no legend box - the card's heading names it. The data's job
 * is polarity: above the zero rule the compared lap is losing, below it is
 * gaining, and the line is filled towards zero in the matching hue so the
 * sign is readable without tracing the curve.
 *
 * uPlot draws it. The old app's slowness was never the renderer - it was the
 * payload and the reactive proxies around it - so uPlot stays, and the arrays
 * arrive here as Float64Arrays that nothing has wrapped.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { useChartSize } from './useChartSize.js'
import { SERIES, baseOptions, zeroLine } from './chart-theme.js'

const props = defineProps({
  distance: { type: Object, required: true },
  delta: { type: Object, required: true },
  corners: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  height: { type: Number, default: 220 },
})

const host = ref(null)
const chart = shallowRef(null)

/** Faint bands behind the plot showing where each corner is. */
function cornerBands(u) {
  const { ctx } = u
  ctx.save()
  for (const corner of props.corners) {
    const spans =
      corner.start_m <= corner.end_m
        ? [[corner.start_m, corner.end_m]]
        : [[corner.start_m, u.scales.x.max], [u.scales.x.min, corner.end_m]]
    ctx.fillStyle =
      corner.index === props.selected ? 'rgba(200, 255, 0, 0.13)' : 'rgba(255, 255, 255, 0.035)'
    for (const [from, to] of spans) {
      const left = u.valToPos(from, 'x', true)
      const right = u.valToPos(to, 'x', true)
      ctx.fillRect(left, u.bbox.top, right - left, u.bbox.height)
    }
  }
  ctx.restore()
  zeroLine(u)
}

/** Fill between the line and zero, in the hue of the side it is on. */
function signedFill(u, seriesIndex) {
  const { ctx } = u
  const values = u.data[seriesIndex]
  const zero = u.valToPos(0, 'y', true)
  for (const [sign, colour] of [[1, SERIES.loss], [-1, SERIES.gain]]) {
    ctx.save()
    ctx.beginPath()
    ctx.globalAlpha = 0.22
    ctx.fillStyle = colour
    ctx.moveTo(u.valToPos(u.data[0][0], 'x', true), zero)
    for (let i = 0; i < values.length; i += 1) {
      const value = sign > 0 ? Math.max(values[i], 0) : Math.min(values[i], 0)
      ctx.lineTo(u.valToPos(u.data[0][i], 'x', true), u.valToPos(value, 'y', true))
    }
    ctx.lineTo(u.valToPos(u.data[0][values.length - 1], 'x', true), zero)
    ctx.closePath()
    ctx.fill()
    ctx.restore()
  }
}

function build() {
  if (!host.value) return
  chart.value?.destroy()
  chart.value = new uPlot(
    {
      ...baseOptions({
        width: host.value.clientWidth || 800,
        height: props.height,
        xLabel: 'distance (m)',
        yLabel: 'delta (s)',
      }),
      series: [
        { label: 'distance' },
        {
          label: 'delta',
          stroke: '#d7dbe2',
          width: 1.75,
          value: (_u, v) => (v == null ? '--' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(3)} s`),
        },
      ],
      hooks: {
        drawClear: [cornerBands],
        draw: [(u) => signedFill(u, 1)],
      },
    },
    [props.distance, props.delta],
    host.value,
  )
}

onMounted(build)
onBeforeUnmount(() => chart.value?.destroy())
useChartSize(host, chart, () => props.height, () => [props.distance, props.delta])

watch(
  () => [props.distance, props.delta],
  ([distance, delta]) => {
    if (!chart.value) return build()
    chart.value.setData([distance, delta])
  },
)
watch(() => [props.corners, props.selected], () => chart.value?.redraw())
</script>

<template>
  <div ref="host" class="chart" />
</template>

<style scoped>
.chart { width: 100%; }
</style>
