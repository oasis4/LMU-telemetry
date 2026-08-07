<script setup>
/**
 * Two laps' worth of one channel, on the same distance axis as the delta.
 *
 * Two series, so a legend is always present - uPlot's live legend doubles as
 * the crosshair readout, which means identity is never carried by colour
 * alone. The reference lap wears chrome ink rather than a hue: it is the
 * baseline, and keeping it colourless is what holds the palette to three hues.
 *
 * One y-axis. Speed and pedal are separate charts precisely because putting
 * two scales on one plot invents a relationship that is not in the data.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { useChartSize } from './useChartSize.js'
import { SERIES, baseOptions } from './chart-theme.js'

const props = defineProps({
  distance: { type: Object, required: true },
  reference: { type: Object, required: true },
  other: { type: Object, required: true },
  referenceLabel: { type: String, default: 'reference' },
  otherLabel: { type: String, default: 'compared' },
  yLabel: { type: String, default: 'speed (km/h)' },
  format: { type: Function, default: (v) => (v == null ? '--' : v.toFixed(1)) },
  height: { type: Number, default: 190 },
})

const host = ref(null)
const chart = shallowRef(null)

function build() {
  if (!host.value) return
  chart.value?.destroy()
  chart.value = new uPlot(
    {
      ...baseOptions({
        width: host.value.clientWidth || 800,
        height: props.height,
        xLabel: 'distance (m)',
        yLabel: props.yLabel,
      }),
      series: [
        { label: 'distance' },
        {
          label: props.referenceLabel,
          stroke: SERIES.reference,
          width: 1.5,
          value: (_u, v) => props.format(v),
        },
        {
          label: props.otherLabel,
          stroke: SERIES.compared,
          width: 2,
          value: (_u, v) => props.format(v),
        },
      ],
    },
    [props.distance, props.reference, props.other],
    host.value,
  )
}

onMounted(build)
onBeforeUnmount(() => chart.value?.destroy())
useChartSize(host, chart, () => props.height, () => [
  props.distance,
  props.reference,
  props.other,
])

watch(
  () => [props.distance, props.reference, props.other, props.referenceLabel],
  ([distance, reference, other], [, , , previousLabel]) => {
    // A changed label means new series metadata, which setData cannot carry.
    if (!chart.value || previousLabel !== props.referenceLabel) return build()
    chart.value.setData([distance, reference, other])
  },
)
</script>

<template>
  <div ref="host" class="chart" />
</template>

<style scoped>
.chart { width: 100%; }
</style>
