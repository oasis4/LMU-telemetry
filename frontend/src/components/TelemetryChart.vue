<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

const props = defineProps({
  channel: { type: String, default: 'speed' },
  distanceRange: { type: Object, default: null },
})

const store = useTelemetryStore()
const chartRef = ref(null)
let plot = null
let resizeObserver = null

const CHANNEL_CONFIG = {
  speed: { label: 'Speed (km/h)', unit: 'km/h', fill: false },
  throttle: { label: 'Throttle (%)', unit: '%', fill: true, scale: 100, fillColor: 'rgba(59,130,246,0.15)' },
  brake: { label: 'Brake (%)', unit: '%', fill: true, scale: 100, fillColor: 'rgba(239,68,68,0.15)' },
  steering: { label: 'Steering', unit: '', fill: false, yRange: [-1, 1] },
  gear: { label: 'Gear', unit: '', fill: false, stepped: true },
  rpm: { label: 'RPM', unit: 'rpm', fill: false },
}

function buildData() {
  const active = store.activeTelemetry
  const reference = store.refTelemetry
  if (!active || !active.distance?.length) return null

  let dist = active.distance
  let activeValues = getChannelValues(active)
  let refValues = reference ? getChannelValues(reference) : null

  // Apply distance range filter
  if (props.distanceRange) {
    const { min, max } = props.distanceRange
    const startIdx = dist.findIndex(d => d >= min)
    const endIdx = dist.findIndex(d => d > max)
    const si = Math.max(0, startIdx)
    const ei = endIdx > 0 ? endIdx : dist.length

    dist = dist.slice(si, ei)
    activeValues = activeValues.slice(si, ei)
    if (refValues && reference) {
      // Ref telemetry may have different length — interpolate to active distance grid
      const refDist = reference.distance
      const refVals = getChannelValues(reference)
      refValues = dist.map(d => {
        const idx = refDist.findIndex(rd => rd >= d)
        return idx >= 0 ? refVals[idx] : null
      })
    }
  }

  const cfg = CHANNEL_CONFIG[props.channel] || {}
  const scale = cfg.scale || 1

  const series = [dist]
  series.push(activeValues.map(v => v != null ? v * scale : null))
  if (refValues) {
    series.push(refValues.map(v => v != null ? v * scale : null))
  }

  return series
}

function getChannelValues(telemetry) {
  const ch = props.channel
  if (ch === 'gear') return telemetry.gear || []
  return telemetry[ch] || []
}

function createChart() {
  if (!chartRef.value) return
  const data = buildData()
  if (!data) return

  if (plot) {
    plot.destroy()
    plot = null
  }

  const rect = chartRef.value.getBoundingClientRect()
  const cfg = CHANNEL_CONFIG[props.channel] || {}
  const hasRef = data.length > 2

  const opts = {
    width: rect.width,
    height: rect.height,
    cursor: {
      sync: { key: 'telemetry' },
      drag: { x: true, y: false },
    },
    hooks: {
      setCursor: [
        (u) => {
          const idx = u.cursor.idx
          if (idx != null && data[0][idx] != null) {
            store.setCursorDistance(data[0][idx])
          }
        },
      ],
    },
    scales: {
      x: { time: false },
    },
    axes: [
      {
        stroke: '#555',
        grid: { stroke: 'rgba(255,255,255,0.04)', width: 1 },
        ticks: { stroke: '#333', width: 1 },
        font: '10px JetBrains Mono',
        label: 'Distance (m)',
        labelFont: '10px Inter',
        labelSize: 20,
      },
      {
        stroke: '#555',
        grid: { stroke: 'rgba(255,255,255,0.04)', width: 1 },
        ticks: { stroke: '#333', width: 1 },
        font: '10px JetBrains Mono',
        label: cfg.label || props.channel,
        labelFont: '10px Inter',
        labelSize: 20,
      },
    ],
    series: [
      { label: 'Distance' },
      {
        label: 'Your Lap',
        stroke: '#3b82f6',
        width: 1.5,
        fill: cfg.fill ? (cfg.fillColor || 'rgba(59,130,246,0.1)') : undefined,
        paths: cfg.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined,
      },
      ...(hasRef ? [{
        label: 'Ref Lap',
        stroke: '#f97316',
        width: 1.5,
        fill: cfg.fill ? 'rgba(249,115,22,0.1)' : undefined,
        paths: cfg.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined,
        dash: [4, 2],
      }] : []),
    ],
  }

  // Y range for steering
  if (cfg.yRange) {
    opts.scales.y = { range: cfg.yRange }
  }

  plot = new uPlot(opts, data, chartRef.value)
}

function handleResize() {
  if (!plot || !chartRef.value) return
  const rect = chartRef.value.getBoundingClientRect()
  plot.setSize({ width: rect.width, height: rect.height })
}

watch(() => [props.channel, props.distanceRange, store.activeTelemetry, store.refTelemetry], () => {
  nextTick(createChart)
}, { deep: true })

onMounted(() => {
  nextTick(createChart)
  resizeObserver = new ResizeObserver(handleResize)
  if (chartRef.value) resizeObserver.observe(chartRef.value)
})

onBeforeUnmount(() => {
  if (plot) plot.destroy()
  if (resizeObserver) resizeObserver.disconnect()
})
</script>

<template>
  <div ref="chartRef" class="telemetry-chart"></div>
</template>

<style scoped>
.telemetry-chart {
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
}
.telemetry-chart :deep(.u-wrap) {
  background: var(--bg-primary);
}
.telemetry-chart :deep(.u-legend) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-secondary);
}
</style>
