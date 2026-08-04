<script setup>
/**
 * The delta over distance, with the corners marked.
 *
 * uPlot draws it. The old app's slowness was never the renderer - it was the
 * payload size and the reactive proxies around it - so uPlot stays and the
 * data arrives here as `Float64Array`s that nothing has wrapped.
 *
 * The chart is created once and fed with `setData`. Recreating it per update
 * throws away its canvas and its scales, which is what makes a chart flicker
 * when the selection changes.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

const props = defineProps({
  distance: { type: Object, required: true },   // Float64Array, metres
  delta: { type: Object, required: true },      // Float64Array, seconds
  corners: { type: Array, default: () => [] },
  height: { type: Number, default: 260 },
})
const emit = defineEmits(['pick'])

const host = ref(null)
const chart = shallowRef(null)

function cornerBands(u) {
  const { ctx } = u
  ctx.save()
  for (const corner of props.corners) {
    // A corner that contains the start/finish line has start_m > end_m, so it
    // is drawn as its two pieces rather than as an empty band.
    const spans = corner.start_m <= corner.end_m
      ? [[corner.start_m, corner.end_m]]
      : [[corner.start_m, u.scales.x.max], [u.scales.x.min, corner.end_m]]
    for (const [from, to] of spans) {
      const left = u.valToPos(from, 'x', true)
      const right = u.valToPos(to, 'x', true)
      ctx.fillStyle = corner.lost_s > 0
        ? 'rgba(220, 68, 68, 0.10)'
        : 'rgba(60, 170, 110, 0.10)'
      ctx.fillRect(left, u.bbox.top, right - left, u.bbox.height)
    }
  }
  ctx.restore()
}

function build() {
  if (!host.value) return
  chart.value?.destroy()
  chart.value = new uPlot(
    {
      width: host.value.clientWidth || 800,
      height: props.height,
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: false } },
      axes: [
        { label: 'distance (m)' },
        { label: 'delta (s)' },
      ],
      series: [
        { label: 'distance' },
        {
          label: 'delta',
          stroke: '#e8552d',
          width: 2,
          value: (_u, v) => (v == null ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(3)} s`),
        },
      ],
      hooks: {
        drawClear: [cornerBands],
        setCursor: [
          (u) => {
            if (u.cursor.idx == null) return
            emit('pick', props.distance[u.cursor.idx])
          },
        ],
      },
    },
    [props.distance, props.delta],
    host.value,
  )
}

function resize() {
  if (chart.value && host.value) {
    chart.value.setSize({ width: host.value.clientWidth, height: props.height })
  }
}

onMounted(() => {
  build()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart.value?.destroy()
})

watch(
  () => [props.distance, props.delta],
  ([distance, delta]) => {
    if (!chart.value) return build()
    chart.value.setData([distance, delta])
  },
)
watch(() => props.corners, () => chart.value?.redraw())
</script>

<template>
  <div ref="host" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
