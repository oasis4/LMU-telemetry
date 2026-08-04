<script setup>
/** Both drivers' speed over distance, on the same x scale as the delta. */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

const props = defineProps({
  distance: { type: Object, required: true },
  reference: { type: Object, required: true },
  other: { type: Object, required: true },
  referenceLabel: { type: String, default: 'reference' },
  otherLabel: { type: String, default: 'compared' },
  height: { type: Number, default: 200 },
})

const host = ref(null)
const chart = shallowRef(null)

function build() {
  if (!host.value) return
  chart.value?.destroy()
  chart.value = new uPlot(
    {
      width: host.value.clientWidth || 800,
      height: props.height,
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: false } },
      axes: [{ label: 'distance (m)' }, { label: 'speed (km/h)' }],
      series: [
        { label: 'distance' },
        { label: props.referenceLabel, stroke: '#2f6fd0', width: 1.6 },
        { label: props.otherLabel, stroke: '#c58a1a', width: 1.6 },
      ],
    },
    [props.distance, props.reference, props.other],
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
  () => [props.distance, props.reference, props.other],
  ([distance, reference, other]) => {
    if (!chart.value) return build()
    chart.value.setData([distance, reference, other])
  },
)
</script>

<template>
  <div ref="host" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
