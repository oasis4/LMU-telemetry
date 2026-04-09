<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

const props = defineProps({
  channel: { type: String, default: 'speed' },
  channels: { type: Array, default: null },
  distanceRange: { type: Object, default: null },
})

const store = useTelemetryStore()
const chartRef = ref(null)
let plot = null
let resizeObserver = null

const CHANNEL_CONFIG = {
  speed: { label: 'Speed (km/h)', unit: 'km/h', fill: false },
  throttle: { label: 'Throttle (%)', unit: '%', fill: true },
  brake: { label: 'Brake (%)', unit: '%', fill: true },
  steering: { label: 'Steering', unit: '', fill: false, yRange: [-1, 1] },
  gear: { label: 'Gear', unit: '', fill: false, stepped: true },
  rpm: { label: 'RPM', unit: 'rpm', fill: false },
}

const CHANNEL_COLORS = {
  speed:    { active: '#3b82f6', ref: '#f97316', fill: 'rgba(59,130,246,0.08)' },
  throttle: { active: '#22c55e', ref: '#4ade80', fill: 'rgba(34,197,94,0.12)' },
  brake:    { active: '#ef4444', ref: '#f87171', fill: 'rgba(239,68,68,0.12)' },
  steering: { active: '#a855f7', ref: '#c084fc', fill: null },
  gear:     { active: '#14b8a6', ref: '#2dd4bf', fill: null },
  rpm:      { active: '#eab308', ref: '#facc15', fill: null },
}

function getChannelList() {
  return props.channels || [props.channel]
}

function buildData() {
  const active = store.activeTelemetry
  const reference = store.refTelemetry
  if (!active || !active.distance?.length) return null

  const channelList = getChannelList()
  let dist = active.distance
  let sliceStart = 0
  let sliceEnd = dist.length

  if (props.distanceRange) {
    const { min, max } = props.distanceRange
    sliceStart = Math.max(0, dist.findIndex(d => d >= min))
    const endIdx = dist.findIndex(d => d > max)
    sliceEnd = endIdx > 0 ? endIdx : dist.length
    dist = dist.slice(sliceStart, sliceEnd)
  }

  const series = [dist]

  for (const ch of channelList) {
    const cfg = CHANNEL_CONFIG[ch] || {}
    const scale = cfg.scale || 1
    const activeRaw = active[ch] || []
    series.push(activeRaw.slice(sliceStart, sliceEnd).map(v => v != null ? v * scale : null))

    if (reference?.distance?.length) {
      const refDist = reference.distance
      const refRaw = reference[ch] || []
      if (props.distanceRange) {
        series.push(dist.map(d => {
          const idx = refDist.findIndex(rd => rd >= d)
          return idx >= 0 && refRaw[idx] != null ? refRaw[idx] * scale : null
        }))
      } else {
        series.push(refRaw.slice(sliceStart, sliceEnd).map(v => v != null ? v * scale : null))
      }
    }
  }

  return series
}

function createChart() {
  if (!chartRef.value) return
  const data = buildData()
  if (!data) return

  if (plot) { plot.destroy(); plot = null }

  const rect = chartRef.value.getBoundingClientRect()
  if (rect.width < 10 || rect.height < 10) return

  const channelList = getChannelList()
  const hasRef = !!store.refTelemetry?.distance?.length
  const isMulti = channelList.length > 1

  const seriesConfig = [{ label: 'Distance' }]
  for (const ch of channelList) {
    const colors = CHANNEL_COLORS[ch] || CHANNEL_COLORS.speed
    const cfg = CHANNEL_CONFIG[ch] || {}
    const shortLabel = cfg.label ? cfg.label.split(' (')[0] : ch

    const activeLapNum = store.activeLap?.lap_number
    const refLapNum = store.refLap?.lap_number
    seriesConfig.push({
      label: isMulti ? shortLabel : `Runde ${activeLapNum ?? '?'} (Deine)`,
      stroke: colors.active,
      width: 1.5,
      fill: cfg.fill && colors.fill ? colors.fill : undefined,
      paths: cfg.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined,
    })
    if (hasRef) {
      seriesConfig.push({
        label: isMulti ? `${shortLabel} Ref` : `Runde ${refLapNum ?? '?'} (Referenz)`,
        stroke: colors.ref,
        width: 1,
        dash: [4, 2],
        paths: cfg.stepped ? uPlot.paths.stepped({ align: 1 }) : undefined,
      })
    }
  }

  let yLabel = ''
  if (channelList.length === 1) {
    yLabel = CHANNEL_CONFIG[channelList[0]]?.label || channelList[0]
  } else {
    yLabel = channelList.map(ch => (CHANNEL_CONFIG[ch]?.label || ch).split(' (')[0]).join(' / ')
  }

  const opts = {
    width: rect.width,
    height: rect.height,
    cursor: {
      sync: { key: 'telemetry' },
      drag: { x: true, y: false },
    },
    hooks: {
      setCursor: [(u) => {
        const idx = u.cursor.idx
        if (idx != null && data[0][idx] != null) store.setCursorDistance(data[0][idx])
      }],
    },
    scales: { x: { time: false } },
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
        label: yLabel,
        labelFont: '10px Inter',
        labelSize: 20,
      },
    ],
    series: seriesConfig,
  }

  const firstCfg = CHANNEL_CONFIG[channelList[0]]
  if (firstCfg?.yRange) opts.scales.y = { range: firstCfg.yRange }

  plot = new uPlot(opts, data, chartRef.value)
}

function handleResize() {
  if (!plot || !chartRef.value) return
  const rect = chartRef.value.getBoundingClientRect()
  if (rect.width < 10 || rect.height < 10) return
  plot.setSize({ width: rect.width, height: rect.height })
}

watch(
  () => [props.channel, props.channels, props.distanceRange, store.activeTelemetry, store.refTelemetry],
  () => nextTick(createChart),
  { deep: true },
)

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
