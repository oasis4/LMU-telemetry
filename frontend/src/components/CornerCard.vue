<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import uPlot from 'uplot'

const props = defineProps({
  corner: { type: Object, required: true },
  activeTelemetry: { type: Object, default: null },
  refTelemetry: { type: Object, default: null },
  delta: { type: Object, default: null },
})

const speedChartEl = ref(null)
const inputsChartEl = ref(null)
let speedPlot = null
let inputsPlot = null
let resizeObs = null

// ---- Corner delta ----
const deltaAtApex = computed(() => {
  if (!props.delta?.distance?.length) return null
  const idx = props.delta.distance.findIndex(d => d >= props.corner.distance_apex)
  return idx >= 0 ? props.delta.delta[idx] : null
})

const deltaMs = computed(() => deltaAtApex.value != null ? deltaAtApex.value * 1000 : null)

const deltaLabel = computed(() => {
  if (deltaMs.value == null) return '—'
  const sign = deltaMs.value > 0 ? '+' : ''
  return `${sign}${deltaMs.value.toFixed(0)}ms`
})

const deltaClass = computed(() => {
  if (deltaMs.value == null) return ''
  return deltaMs.value > 10 ? 'delta-losing' : deltaMs.value < -10 ? 'delta-gaining' : 'delta-neutral'
})

// ---- Sliced data for this corner ----
const PADDING_M = 80 // meters before/after corner

function sliceChannel(telemetry, channel) {
  if (!telemetry?.distance?.length) return { dist: [], vals: [] }
  const start = props.corner.distance_start - PADDING_M
  const end = props.corner.distance_end + PADDING_M
  const dist = telemetry.distance
  const si = Math.max(0, dist.findIndex(d => d >= start))
  let ei = dist.findIndex(d => d > end)
  if (ei < 0) ei = dist.length
  return {
    dist: dist.slice(si, ei),
    vals: (telemetry[channel] || []).slice(si, ei),
  }
}

// ---- Per-corner metrics ----
const metrics = computed(() => {
  const active = props.activeTelemetry
  const reference = props.refTelemetry
  if (!active?.distance?.length || !reference?.distance?.length) return null

  const c = props.corner
  const findIdx = (tel, dist) => {
    const idx = tel.distance.findIndex(d => d >= dist)
    return idx >= 0 ? idx : tel.distance.length - 1
  }

  // Active lap metrics
  const aEntryI = findIdx(active, c.distance_start)
  const aApexI = findIdx(active, c.distance_apex)
  const aExitI = findIdx(active, c.distance_end)
  // Ref lap metrics
  const rEntryI = findIdx(reference, c.distance_start)
  const rApexI = findIdx(reference, c.distance_apex)
  const rExitI = findIdx(reference, c.distance_end)

  // Brake point: first where brake > 0.1 in approach zone
  function findBrakePoint(tel, startDist, apexIdx) {
    const searchStart = Math.max(0, tel.distance.findIndex(d => d >= startDist - 50))
    for (let i = searchStart; i < apexIdx; i++) {
      if (tel.brake[i] > 0.1) return tel.distance[i]
    }
    return null
  }

  // Throttle point: first where throttle > 0.5 after apex
  function findThrottlePoint(tel, apexIdx, endIdx) {
    for (let i = apexIdx; i < Math.min(endIdx + 50, tel.throttle.length); i++) {
      if (tel.throttle[i] > 0.5) return tel.distance[i]
    }
    return null
  }

  const aBrake = findBrakePoint(active, c.distance_start, aApexI)
  const rBrake = findBrakePoint(reference, c.distance_start, rApexI)
  const aThrottle = findThrottlePoint(active, aApexI, aExitI)
  const rThrottle = findThrottlePoint(reference, rApexI, rExitI)

  const aApexSpeed = active.speed[aApexI]
  const rApexSpeed = reference.speed[rApexI]
  const aEntrySpeed = active.speed[aEntryI]
  const rEntrySpeed = reference.speed[rEntryI]
  const aExitSpeed = active.speed[aExitI]
  const rExitSpeed = reference.speed[rExitI]

  return {
    brakeDiff: (aBrake != null && rBrake != null) ? aBrake - rBrake : null,
    apexSpeedDiff: aApexSpeed - rApexSpeed,
    entrySpeedDiff: aEntrySpeed - rEntrySpeed,
    exitSpeedDiff: aExitSpeed - rExitSpeed,
    throttleDiff: (aThrottle != null && rThrottle != null) ? aThrottle - rThrottle : null,
    aApexSpeed,
    rApexSpeed,
  }
})

// ---- Coaching tip ----
const coachingTip = computed(() => {
  const m = metrics.value
  const d = deltaMs.value
  if (!m || d == null) return null
  if (Math.abs(d) < 30) return null

  const tips = []
  if (m.brakeDiff != null && m.brakeDiff < -5) {
    tips.push(`Bremspunkt ${Math.abs(m.brakeDiff).toFixed(0)}m früher als Referenz. Später bremsen!`)
  } else if (m.brakeDiff != null && m.brakeDiff > 5) {
    tips.push(`Bremspunkt ${m.brakeDiff.toFixed(0)}m später als Referenz. Vorsicht Apex!`)
  }
  if (m.apexSpeedDiff < -3) {
    tips.push(`Apex-Speed ${Math.abs(m.apexSpeedDiff).toFixed(0)} km/h langsamer.`)
  }
  if (m.throttleDiff != null && m.throttleDiff > 5) {
    tips.push(`Gas ${m.throttleDiff.toFixed(0)}m später. Früher ans Gas!`)
  }
  if (m.exitSpeedDiff < -3) {
    tips.push(`Exit-Speed ${Math.abs(m.exitSpeedDiff).toFixed(0)} km/h langsamer.`)
  }

  if (tips.length === 0 && d > 30) {
    tips.push(`${d.toFixed(0)}ms verloren. Linie und Inputs überprüfen.`)
  } else if (tips.length === 0 && d < -30) {
    tips.push(`${Math.abs(d).toFixed(0)}ms gewonnen. Gut gemacht!`)
  }
  return tips.join(' ')
})

// ---- Chart rendering ----
function buildSpeedChart() {
  if (!speedChartEl.value) return
  const active = sliceChannel(props.activeTelemetry, 'speed')
  const ref = sliceChannel(props.refTelemetry, 'speed')
  if (!active.dist.length) return

  if (speedPlot) { speedPlot.destroy(); speedPlot = null }

  const rect = speedChartEl.value.getBoundingClientRect()
  // Align ref to active distance grid
  const refAligned = active.dist.map(d => {
    const idx = ref.dist.findIndex(rd => rd >= d)
    return idx >= 0 ? ref.vals[idx] : null
  })

  const data = [active.dist, active.vals, refAligned]

  speedPlot = new uPlot({
    width: rect.width,
    height: 100,
    cursor: { show: false },
    legend: { show: false },
    scales: { x: { time: false } },
    axes: [
      { show: false },
      {
        show: true,
        stroke: '#444',
        grid: { stroke: 'rgba(255,255,255,0.03)', width: 1 },
        font: '9px JetBrains Mono',
        size: 36,
        gap: 2,
        ticks: { show: false },
      },
    ],
    series: [
      {},
      { label: 'You', stroke: '#3b82f6', width: 1.5 },
      { label: 'Best', stroke: '#f97316', width: 1.5, dash: [4, 2] },
    ],
  }, data, speedChartEl.value)
}

function buildInputsChart() {
  if (!inputsChartEl.value) return
  const aThrottle = sliceChannel(props.activeTelemetry, 'throttle')
  const aBrake = sliceChannel(props.activeTelemetry, 'brake')
  const rThrottle = sliceChannel(props.refTelemetry, 'throttle')
  const rBrake = sliceChannel(props.refTelemetry, 'brake')
  if (!aThrottle.dist.length) return

  if (inputsPlot) { inputsPlot.destroy(); inputsPlot = null }

  const rect = inputsChartEl.value.getBoundingClientRect()
  const dist = aThrottle.dist

  // Align ref to active distance grid
  const align = (refData) => dist.map(d => {
    const idx = refData.dist.findIndex(rd => rd >= d)
    return idx >= 0 ? refData.vals[idx] * 100 : null
  })

  const data = [
    dist,
    aThrottle.vals.map(v => v * 100),
    align(rThrottle),
    aBrake.vals.map(v => v * 100),
    align(rBrake),
  ]

  inputsPlot = new uPlot({
    width: rect.width,
    height: 80,
    cursor: { show: false },
    legend: { show: false },
    scales: {
      x: { time: false },
      y: { range: [0, 105] },
    },
    axes: [
      { show: false },
      {
        show: true,
        stroke: '#444',
        grid: { stroke: 'rgba(255,255,255,0.03)', width: 1 },
        font: '9px JetBrains Mono',
        size: 36,
        gap: 2,
        ticks: { show: false },
        values: (u, vals) => vals.map(v => v + '%'),
      },
    ],
    series: [
      {},
      { label: 'Throttle', stroke: '#22c55e', width: 1.5, fill: 'rgba(34,197,94,0.12)' },
      { label: 'Throttle (ref)', stroke: '#22c55e', width: 1, dash: [3, 2], alpha: 0.5 },
      { label: 'Brake', stroke: '#ef4444', width: 1.5, fill: 'rgba(239,68,68,0.12)' },
      { label: 'Brake (ref)', stroke: '#ef4444', width: 1, dash: [3, 2], alpha: 0.5 },
    ],
  }, data, inputsChartEl.value)
}

function rebuildCharts() {
  nextTick(() => {
    buildSpeedChart()
    buildInputsChart()
  })
}

function handleResize() {
  if (speedPlot && speedChartEl.value) {
    speedPlot.setSize({ width: speedChartEl.value.getBoundingClientRect().width, height: 100 })
  }
  if (inputsPlot && inputsChartEl.value) {
    inputsPlot.setSize({ width: inputsChartEl.value.getBoundingClientRect().width, height: 80 })
  }
}

watch(() => [props.activeTelemetry, props.refTelemetry, props.corner], rebuildCharts, { deep: true })

onMounted(() => {
  rebuildCharts()
  resizeObs = new ResizeObserver(handleResize)
  if (speedChartEl.value) resizeObs.observe(speedChartEl.value)
})

onBeforeUnmount(() => {
  if (speedPlot) speedPlot.destroy()
  if (inputsPlot) inputsPlot.destroy()
  if (resizeObs) resizeObs.disconnect()
})

function formatMetric(val, unit) {
  if (val == null) return '—'
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(0)}${unit}`
}

function metricClass(val, inverted = false) {
  if (val == null) return ''
  const v = inverted ? -val : val
  if (v > 3) return 'metric-bad'
  if (v < -3) return 'metric-good'
  return ''
}
</script>

<template>
  <div class="corner-card" :class="deltaClass">
    <!-- Header -->
    <div class="card-header">
      <div class="card-title">
        <span class="corner-number">{{ corner.name }}</span>
        <span class="corner-speed">{{ corner.min_speed.toFixed(0) }} km/h</span>
      </div>
      <div class="card-delta" :class="deltaClass">{{ deltaLabel }}</div>
    </div>

    <!-- Charts -->
    <div class="card-charts">
      <div class="chart-section">
        <div class="chart-label">Speed</div>
        <div ref="speedChartEl" class="mini-chart"></div>
      </div>
      <div class="chart-section">
        <div class="chart-label">Inputs</div>
        <div ref="inputsChartEl" class="mini-chart mini-chart-small"></div>
      </div>
    </div>

    <!-- Metrics -->
    <div class="card-metrics" v-if="metrics">
      <div class="metric" :class="metricClass(metrics.brakeDiff)">
        <span class="metric-label">Bremspunkt</span>
        <span class="metric-value">{{ formatMetric(metrics.brakeDiff, 'm') }}</span>
      </div>
      <div class="metric" :class="metricClass(metrics.apexSpeedDiff, true)">
        <span class="metric-label">Apex</span>
        <span class="metric-value">{{ formatMetric(metrics.apexSpeedDiff, ' km/h') }}</span>
      </div>
      <div class="metric" :class="metricClass(metrics.throttleDiff)">
        <span class="metric-label">Gas</span>
        <span class="metric-value">{{ formatMetric(metrics.throttleDiff, 'm') }}</span>
      </div>
      <div class="metric" :class="metricClass(metrics.exitSpeedDiff, true)">
        <span class="metric-label">Exit</span>
        <span class="metric-value">{{ formatMetric(metrics.exitSpeedDiff, ' km/h') }}</span>
      </div>
    </div>

    <!-- Coaching tip -->
    <div class="card-tip" v-if="coachingTip">
      <span class="tip-icon">💡</span>
      <span class="tip-text">{{ coachingTip }}</span>
    </div>
  </div>
</template>

<style scoped>
.corner-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.corner-card.delta-losing {
  border-left: 3px solid var(--negative);
}
.corner-card.delta-gaining {
  border-left: 3px solid var(--positive);
}
.corner-card.delta-neutral {
  border-left: 3px solid var(--text-muted);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.card-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.corner-number {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-primary);
}
.corner-speed {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.card-delta {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
}
.card-delta.delta-losing { color: var(--negative); }
.card-delta.delta-gaining { color: var(--positive); }
.card-delta.delta-neutral { color: var(--text-muted); }

.card-charts {
  padding: 8px 0;
}
.chart-section {
  position: relative;
}
.chart-label {
  position: absolute;
  top: 4px;
  left: 12px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  z-index: 1;
  pointer-events: none;
}
.mini-chart {
  width: 100%;
  height: 100px;
  background: var(--bg-primary);
}
.mini-chart-small {
  height: 80px;
}

.card-metrics {
  display: flex;
  gap: 0;
  border-top: 1px solid var(--border);
}
.metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  border-right: 1px solid var(--border);
}
.metric:last-child { border-right: none; }
.metric-label {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.metric-value {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.metric-good .metric-value { color: var(--positive); }
.metric-bad .metric-value { color: var(--negative); }

.card-tip {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  background: rgba(249, 115, 22, 0.04);
  font-size: 11px;
  line-height: 1.5;
  color: var(--accent-orange);
}
.tip-icon { flex-shrink: 0; }
.tip-text { flex: 1; }
</style>
