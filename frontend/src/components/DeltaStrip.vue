<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  distanceRange: { type: Object, default: null },
})

const store = useTelemetryStore()
const containerRef = ref(null)
const containerWidth = ref(800)
const selectedCorner = ref(null)
const hoveredCorner = ref(null)
const popupCorner = ref(null)
let observer = null

// Compute bar data (red/green segments between corners)
const barHeight = 60

function getDistAndDelta() {
  const d = store.delta
  if (!d || !d.distance?.length) return { dist: [], delta: [] }
  let dist = d.distance
  let delta = d.delta
  if (props.distanceRange) {
    const { min, max } = props.distanceRange
    const si = dist.findIndex(dd => dd >= min)
    const ei = dist.findIndex(dd => dd > max)
    const startI = Math.max(0, si)
    const endI = ei > 0 ? ei : dist.length
    dist = dist.slice(startI, endI)
    delta = delta.slice(startI, endI)
  }
  return { dist, delta }
}

// Corner markers with positions
const cornerMarkers = computed(() => {
  const { dist } = getDistAndDelta()
  if (!dist.length || !store.corners?.length) return []
  const dMin = dist[0], dMax = dist[dist.length - 1], dRange = dMax - dMin || 1
  const w = containerWidth.value

  return store.corners.map(c => {
    const pos = ((c.distance_apex - dMin) / dRange) * w
    if (pos < 0 || pos > w) return null

    // Per-corner delta: difference between corner exit and entry
    const dd = store.delta
    let deltaAtCorner = 0
    if (dd?.distance?.length) {
      const si = dd.distance.findIndex(d => d >= c.distance_start)
      const ei = dd.distance.findIndex(d => d >= c.distance_end)
      if (si >= 0 && ei >= 0 && ei < dd.delta.length) {
        deltaAtCorner = dd.delta[ei] - dd.delta[si]
      }
    }

    return {
      ...c,
      x: pos,
      delta: deltaAtCorner,
      color: deltaAtCorner > 0.01 ? '#ef4444' : deltaAtCorner < -0.01 ? '#22c55e' : '#666',
    }
  }).filter(Boolean)
})

// Bar segments for the delta visualization
const barSegments = computed(() => {
  const { dist, delta } = getDistAndDelta()
  if (!dist.length) return []
  const dMin = dist[0], dMax = dist[dist.length - 1], dRange = dMax - dMin || 1
  // Fixed scale: ±5 seconds — bars reach full height at 5s delta
  const maxDelta = 5.0
  const w = containerWidth.value
  const halfH = barHeight / 2
  const segments = []
  const step = Math.max(1, Math.floor(dist.length / w))

  for (let i = 0; i < dist.length - step; i += step) {
    const x = ((dist[i] - dMin) / dRange) * w
    const xNext = ((dist[Math.min(i + step, dist.length - 1)] - dMin) / dRange) * w
    const val = delta[i]
    const h = Math.min(1, Math.abs(val) / maxDelta) * halfH * 0.85

    segments.push({
      x,
      width: Math.max(1, xNext - x),
      y: val > 0 ? halfH : halfH - h,
      height: h,
      fill: val > 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)',
    })
  }
  return segments
})

// Popup data for selected corner
const popupData = computed(() => {
  const c = popupCorner.value
  if (!c) return null

  const tel = store.activeTelemetry
  const ref = store.refTelemetry
  if (!tel?.distance?.length) return null

  const findIdx = (arr, d) => {
    let lo = 0, hi = arr.length - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (arr[mid] <= d) lo = mid; else hi = mid
    }
    return lo
  }

  const apexIdx = findIdx(tel.distance, c.distance_apex)
  const startIdx = findIdx(tel.distance, c.distance_start)
  const endIdx = findIdx(tel.distance, c.distance_end)

  const active = {
    entrySpeed: tel.speed?.[startIdx]?.toFixed(0) || '—',
    apexSpeed: tel.speed?.[apexIdx]?.toFixed(0) || '—',
    exitSpeed: tel.speed?.[endIdx]?.toFixed(0) || '—',
    throttle: (tel.throttle?.[apexIdx] || 0).toFixed(0),
    brake: (tel.brake?.[apexIdx] || 0).toFixed(0),
    gear: tel.gear?.[apexIdx] || '—',
  }

  let reference = null
  if (ref?.distance?.length) {
    const rApex = findIdx(ref.distance, c.distance_apex)
    const rStart = findIdx(ref.distance, c.distance_start)
    const rEnd = findIdx(ref.distance, c.distance_end)
    reference = {
      entrySpeed: ref.speed?.[rStart]?.toFixed(0) || '—',
      apexSpeed: ref.speed?.[rApex]?.toFixed(0) || '—',
      exitSpeed: ref.speed?.[rEnd]?.toFixed(0) || '—',
      throttle: (ref.throttle?.[rApex] || 0).toFixed(0),
      brake: (ref.brake?.[rApex] || 0).toFixed(0),
      gear: ref.gear?.[rApex] || '—',
    }
  }

  // Position the popup
  const { dist } = getDistAndDelta()
  const dMin = dist[0] || 0, dMax = dist[dist.length - 1] || 1, dRange = dMax - dMin || 1
  const x = ((c.distance_apex - dMin) / dRange) * containerWidth.value

  return { corner: c, active, reference, x }
})

function formatDelta(d) {
  if (Math.abs(d) < 0.001) return '0.000'
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(3)}`
}

function clickCorner(corner) {
  if (popupCorner.value?.id === corner.id) {
    popupCorner.value = null
  } else {
    popupCorner.value = corner
    store.setActiveCorner(corner)
  }
}

function onHover(corner) {
  hoveredCorner.value = corner
}

function onLeave() {
  hoveredCorner.value = null
}

onMounted(() => {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.getBoundingClientRect().width
    observer = new ResizeObserver(entries => {
      containerWidth.value = entries[0].contentRect.width
    })
    observer.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

watch(() => [store.delta, props.distanceRange], () => {
  popupCorner.value = null
}, { deep: true })
</script>

<template>
  <div class="delta-strip-v2" ref="containerRef">
    <!-- Header row -->
    <div class="strip-header">
      <span class="strip-title">Corner Delta</span>
      <span class="strip-hint text-muted" v-if="!store.delta?.distance?.length">Select a reference lap</span>
      <span class="strip-legend" v-else>
        <span class="legend-dot gain"></span> Gaining
        <span class="legend-dot loss"></span> Losing
      </span>
    </div>

    <!-- SVG delta bars + corner markers -->
    <div class="strip-chart" :style="{ height: barHeight + 'px' }">
      <svg :width="containerWidth" :height="barHeight" class="delta-svg">
        <!-- Center line -->
        <line x1="0" :y1="barHeight/2" :x2="containerWidth" :y2="barHeight/2" stroke="#333" stroke-width="0.5" />

        <!-- Delta bars -->
        <rect
          v-for="(seg, i) in barSegments"
          :key="i"
          :x="seg.x"
          :y="seg.y"
          :width="seg.width"
          :height="seg.height"
          :fill="seg.fill"
        />

        <!-- Corner markers -->
        <g
          v-for="c in cornerMarkers"
          :key="'cm-' + c.id"
          class="corner-marker"
          :class="{ active: popupCorner?.id === c.id, hovered: hoveredCorner?.id === c.id }"
          @click.stop="clickCorner(c)"
          @mouseenter="onHover(c)"
          @mouseleave="onLeave"
          style="cursor: pointer"
        >
          <!-- Vertical line -->
          <line
            :x1="c.x" y1="2"
            :x2="c.x" :y2="barHeight - 2"
            :stroke="c.color"
            stroke-width="1.5"
            :opacity="popupCorner?.id === c.id ? 1 : 0.5"
          />
          <!-- Corner circle -->
          <circle
            :cx="c.x"
            :cy="barHeight / 2"
            :r="popupCorner?.id === c.id ? 10 : 8"
            :fill="c.color"
            :fill-opacity="popupCorner?.id === c.id ? 0.3 : 0.15"
            :stroke="c.color"
            stroke-width="1.5"
          />
          <!-- Corner label -->
          <text
            :x="c.x"
            :y="barHeight / 2 + 1"
            text-anchor="middle"
            dominant-baseline="central"
            :fill="c.color"
            font-size="9"
            font-weight="700"
            font-family="Inter, sans-serif"
            pointer-events="none"
          >
            {{ c.name }}
          </text>
        </g>
      </svg>
    </div>

    <!-- Corner delta labels row -->
    <div class="corner-labels" v-if="cornerMarkers.length">
      <div
        v-for="c in cornerMarkers"
        :key="'lbl-' + c.id"
        class="corner-label"
        :style="{ left: c.x + 'px', color: c.color }"
        @click.stop="clickCorner(c)"
      >
        {{ formatDelta(c.delta) }}
      </div>
    </div>

    <!-- Popup for clicked corner -->
    <Transition name="popup">
      <div
        v-if="popupData"
        class="corner-popup"
        :style="{ left: Math.min(Math.max(popupData.x, 140), containerWidth - 140) + 'px' }"
        @click.stop
      >
        <div class="popup-header">
          <span class="popup-name">{{ popupData.corner.name }}</span>
          <span class="popup-delta" :style="{ color: popupData.corner.delta > 0 ? '#ef4444' : '#22c55e' }">
            {{ formatDelta(popupData.corner.delta) }}s
          </span>
          <button class="popup-close" @click="popupCorner = null">&times;</button>
        </div>
        <div class="popup-body">
          <table class="popup-table">
            <thead>
              <tr>
                <th></th>
                <th>You</th>
                <th v-if="popupData.reference">Ref</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="metric-label">Entry</td>
                <td>{{ popupData.active.entrySpeed }} <span class="unit">km/h</span></td>
                <td v-if="popupData.reference">{{ popupData.reference.entrySpeed }} <span class="unit">km/h</span></td>
              </tr>
              <tr>
                <td class="metric-label">Apex</td>
                <td>{{ popupData.active.apexSpeed }} <span class="unit">km/h</span></td>
                <td v-if="popupData.reference">{{ popupData.reference.apexSpeed }} <span class="unit">km/h</span></td>
              </tr>
              <tr>
                <td class="metric-label">Exit</td>
                <td>{{ popupData.active.exitSpeed }} <span class="unit">km/h</span></td>
                <td v-if="popupData.reference">{{ popupData.reference.exitSpeed }} <span class="unit">km/h</span></td>
              </tr>
              <tr>
                <td class="metric-label">Throttle</td>
                <td>{{ popupData.active.throttle }}<span class="unit">%</span></td>
                <td v-if="popupData.reference">{{ popupData.reference.throttle }}<span class="unit">%</span></td>
              </tr>
              <tr>
                <td class="metric-label">Brake</td>
                <td>{{ popupData.active.brake }}<span class="unit">%</span></td>
                <td v-if="popupData.reference">{{ popupData.reference.brake }}<span class="unit">%</span></td>
              </tr>
              <tr>
                <td class="metric-label">Gear</td>
                <td>{{ popupData.active.gear }}</td>
                <td v-if="popupData.reference">{{ popupData.reference.gear }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.delta-strip-v2 {
  position: relative;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.strip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px 4px;
}
.strip-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.strip-hint {
  font-size: 11px;
}
.strip-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--text-muted);
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.legend-dot.gain {
  background: #22c55e;
}
.legend-dot.loss {
  background: #ef4444;
  margin-left: 8px;
}

.strip-chart {
  position: relative;
}
.delta-svg {
  display: block;
}

/* Corner labels row */
.corner-labels {
  position: relative;
  height: 18px;
}
.corner-label {
  position: absolute;
  transform: translateX(-50%);
  font-size: 9px;
  font-family: var(--font-mono);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  line-height: 18px;
}

/* Popup */
.corner-popup {
  position: absolute;
  bottom: calc(100% + 8px);
  transform: translateX(-50%);
  background: #1a1a20;
  border: 1px solid #2a2a3a;
  border-radius: 8px;
  min-width: 220px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  z-index: 20;
  overflow: hidden;
}
.popup-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #2a2a3a;
  background: #15151a;
}
.popup-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  flex: 1;
}
.popup-delta {
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.popup-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
}
.popup-close:hover {
  color: var(--text-primary);
}
.popup-body {
  padding: 8px 12px 10px;
}
.popup-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 12px;
}
.popup-table th {
  text-align: right;
  font-size: 10px;
  color: var(--text-muted);
  font-weight: 600;
  padding: 2px 4px;
  text-transform: uppercase;
}
.popup-table td {
  padding: 3px 4px;
  text-align: right;
  color: var(--text-primary);
  border: none;
}
.popup-table .metric-label {
  text-align: left;
  color: var(--text-muted);
  font-size: 11px;
  font-family: var(--font-sans);
  font-weight: 500;
}
.popup-table .unit {
  color: var(--text-muted);
  font-size: 10px;
}

/* Transitions */
.popup-enter-active, .popup-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.popup-enter-from, .popup-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(4px);
}

/* Marker hover */
.corner-marker:hover line { opacity: 1 !important; }
.corner-marker:hover circle { fill-opacity: 0.35 !important; }
</style>
