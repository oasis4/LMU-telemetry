<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  distanceRange: { type: Object, default: null },
  showRef: { type: Boolean, default: false },
})

const emit = defineEmits(['corner-click'])

const store = useTelemetryStore()
const svgRef = ref(null)
const containerRef = ref(null)
const width = ref(800)
const height = ref(300)

// When zoomed (distanceRange set), find index range for the visible portion
function getVisibleRange(telemetry) {
  if (!telemetry?.distance?.length || !props.distanceRange) return null
  const { min, max } = props.distanceRange
  const si = telemetry.distance.findIndex(d => d >= min)
  const ei = telemetry.distance.findIndex(d => d > max)
  return {
    start: Math.max(0, si),
    end: ei > 0 ? ei : telemetry.distance.length,
  }
}

// Build projection — zooms into distanceRange when set
function buildProjection(w, h, padding = 20) {
  const t = store.activeTelemetry
  if (!t?.lat?.length) return null

  let latMin = Infinity, latMax = -Infinity, lonMin = Infinity, lonMax = -Infinity

  // Determine which points to use for bounds
  const range = getVisibleRange(t)
  const iStart = range ? range.start : 0
  const iEnd = range ? range.end : t.lat.length

  for (let i = iStart; i < iEnd; i++) {
    const la = t.lat[i], lo = t.lon[i]
    if (la < latMin) latMin = la
    if (la > latMax) latMax = la
    if (lo < lonMin) lonMin = lo
    if (lo > lonMax) lonMax = lo
  }

  // Also include ref telemetry bounds when showRef + zoomed
  if (props.showRef && store.refTelemetry?.lat?.length) {
    const rRange = getVisibleRange(store.refTelemetry)
    const rStart = rRange ? rRange.start : 0
    const rEnd = rRange ? rRange.end : store.refTelemetry.lat.length
    for (let i = rStart; i < rEnd; i++) {
      const la = store.refTelemetry.lat[i], lo = store.refTelemetry.lon[i]
      if (la < latMin) latMin = la
      if (la > latMax) latMax = la
      if (lo < lonMin) lonMin = lo
      if (lo > lonMax) lonMax = lo
    }
  }

  const midLat = (latMin + latMax) / 2
  const cosLat = Math.cos(midLat * Math.PI / 180)

  const latRange = latMax - latMin || 1e-6
  const lonRange = (lonMax - lonMin) * cosLat || 1e-6

  const drawW = w - 2 * padding
  const drawH = h - 2 * padding
  const scale = Math.min(drawW / lonRange, drawH / latRange)

  const projW = lonRange * scale
  const projH = latRange * scale
  const offsetX = padding + (drawW - projW) / 2
  const offsetY = padding + (drawH - projH) / 2

  return {
    project(lon, lat) {
      const x = offsetX + (lon - lonMin) * cosLat * scale
      const y = offsetY + (latMax - lat) * scale
      return { x, y }
    }
  }
}

function buildPath(telemetry, proj, range) {
  if (!telemetry?.lat?.length || !proj) return ''
  const parts = []
  const iStart = range ? range.start : 0
  const iEnd = range ? range.end : telemetry.lat.length
  for (let i = iStart; i < iEnd; i++) {
    const { x, y } = proj.project(telemetry.lon[i], telemetry.lat[i])
    parts.push(`${i === iStart ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return parts.join(' ')
}

const isZoomed = computed(() => !!props.distanceRange)

const projection = computed(() => buildProjection(width.value, height.value))

const activeRange = computed(() => getVisibleRange(store.activeTelemetry))
const refRange = computed(() => getVisibleRange(store.refTelemetry))

const activePath = computed(() => buildPath(store.activeTelemetry, projection.value, isZoomed.value ? activeRange.value : null))
const refPath = computed(() => {
  if (!props.showRef) return ''
  return buildPath(store.refTelemetry, projection.value, isZoomed.value ? refRange.value : null)
})

// Corner markers with per-corner delta values
const cornerMarkers = computed(() => {
  const t = store.activeTelemetry
  const proj = projection.value
  if (!t || !t.distance?.length || !t.lat?.length || !proj) return []
  const d = store.delta
  return store.corners.map(c => {
    // When zoomed, only show corners in range
    if (isZoomed.value && props.distanceRange) {
      if (c.distance_apex < props.distanceRange.min || c.distance_apex > props.distanceRange.max) return null
    }
    const idx = t.distance.findIndex(dd => dd >= c.distance_apex)
    if (idx < 0) return null
    const { x, y } = proj.project(t.lon[idx], t.lat[idx])
    let cornerDelta = null
    if (d?.distance?.length) {
      const si = d.distance.findIndex(dd => dd >= c.distance_start)
      const ei = d.distance.findIndex(dd => dd >= c.distance_end)
      if (si >= 0 && ei >= 0) cornerDelta = d.delta[ei] - d.delta[si]
    }
    const deltaColor = cornerDelta == null ? '#888'
      : cornerDelta > 0.005 ? '#ef4444'
      : cornerDelta < -0.005 ? '#22c55e' : '#888'
    const deltaMs = cornerDelta == null ? ''
      : cornerDelta > 0 ? `+${cornerDelta.toFixed(3)}s`
      : `${cornerDelta.toFixed(3)}s`
    return { ...c, x, y, deltaAtApex: cornerDelta, deltaColor, deltaLabel: deltaMs }
  }).filter(Boolean)
})

// Delta-colored segments for active path
const deltaSegments = computed(() => {
  const t = store.activeTelemetry
  const d = store.delta
  const proj = projection.value
  if (!t || !t.lat?.length || !d || !d.delta?.length || !proj) return []

  const range = isZoomed.value ? activeRange.value : null
  const iStart = range ? range.start : 0
  const iEnd = range ? range.end : t.distance.length

  const segments = []
  const totalPts = iEnd - iStart
  const step = Math.max(1, Math.floor(totalPts / 300))
  for (let i = iStart; i < iEnd - step; i += step) {
    const dist = t.distance[i]
    const deltaIdx = d.distance.findIndex(dd => dd >= dist)
    const deltaVal = deltaIdx >= 0 ? d.delta[deltaIdx] : 0
    let color = '#666'
    if (deltaVal < -0.01) color = '#22c55e'
    else if (deltaVal > 0.01) color = '#ef4444'
    const p1 = proj.project(t.lon[i], t.lat[i])
    const j = Math.min(i + step, iEnd - 1)
    const p2 = proj.project(t.lon[j], t.lat[j])
    segments.push({ x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, color })
  }
  return segments
})

// Cursor dot on track map
const cursorDot = computed(() => {
  const t = store.activeTelemetry
  const proj = projection.value
  if (!t || !t.distance?.length || store.cursorDistance == null || !proj) return null
  const idx = t.distance.findIndex(d => d >= store.cursorDistance)
  if (idx < 0) return null
  return proj.project(t.lon[idx], t.lat[idx])
})

// Legend info
const hasRef = computed(() => props.showRef && !!store.refTelemetry?.lat?.length)
const hasDelta = computed(() => !!store.delta?.distance?.length)
const activeLapLabel = computed(() => store.activeLap ? `Lap ${store.activeLap.lap_number}` : 'Your Lap')
const refLapLabel = computed(() => store.refLap ? `Lap ${store.refLap.lap_number}` : 'Reference')

// Resize observer
let observer = null
onMounted(() => {
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    width.value = rect.width
    height.value = rect.height
    observer = new ResizeObserver(entries => {
      const r = entries[0].contentRect
      width.value = r.width
      height.value = r.height
    })
    observer.observe(containerRef.value)
  }
})
onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

function onCornerClick(c) {
  emit('corner-click', c)
}
</script>

<template>
  <div ref="containerRef" class="track-map">
    <svg
      ref="svgRef"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
    >
      <!-- Reference path (when showRef) -->
      <path
        v-if="refPath"
        :d="refPath"
        fill="none"
        stroke="#f97316"
        stroke-width="2"
        opacity="0.7"
        stroke-dasharray="6 3"
      />

      <!-- Delta colored segments -->
      <line
        v-for="(seg, i) in deltaSegments"
        :key="'seg-' + i"
        :x1="seg.x1" :y1="seg.y1"
        :x2="seg.x2" :y2="seg.y2"
        :stroke="seg.color"
        stroke-width="3"
        stroke-linecap="round"
      />

      <!-- Active lap path (if no delta data yet) -->
      <path
        v-if="activePath && !deltaSegments.length"
        :d="activePath"
        fill="none"
        stroke="#3b82f6"
        stroke-width="2.5"
      />

      <!-- Corner markers with delta labels -->
      <g
        v-for="m in cornerMarkers"
        :key="'corner-' + m.id"
        class="corner-marker"
        @click="onCornerClick(m)"
      >
        <circle
          :cx="m.x" :cy="m.y" r="13"
          :fill="store.activeCorner?.id === m.id ? '#f97316' : m.deltaColor || '#e63946'"
          :stroke="store.activeCorner?.id === m.id ? '#fff' : 'rgba(0,0,0,0.5)'"
          stroke-width="1.5"
        />
        <text
          :x="m.x" :y="m.y"
          text-anchor="middle"
          dominant-baseline="central"
          fill="#fff"
          font-size="10"
          font-family="Inter, sans-serif"
          font-weight="700"
        >
          {{ m.id }}
        </text>
        <!-- Delta label -->
        <text
          v-if="m.deltaLabel"
          :x="m.x + 18" :y="m.y - 2"
          text-anchor="start"
          dominant-baseline="central"
          :fill="m.deltaColor"
          font-size="11"
          font-family="'JetBrains Mono', monospace"
          font-weight="600"
        >
          {{ m.deltaLabel }}
        </text>
      </g>

      <!-- Cursor dot -->
      <circle
        v-if="cursorDot"
        :cx="cursorDot.x" :cy="cursorDot.y"
        r="5"
        fill="#fff"
        stroke="#3b82f6"
        stroke-width="2"
      />
    </svg>

    <!-- Legend -->
    <div class="map-legend" v-if="hasDelta || hasRef">
      <div class="legend-item" v-if="hasDelta">
        <span class="legend-line" style="background: #22c55e;"></span>
        <span class="legend-text">{{ activeLapLabel }} (schneller)</span>
      </div>
      <div class="legend-item" v-if="hasDelta">
        <span class="legend-line" style="background: #ef4444;"></span>
        <span class="legend-text">{{ activeLapLabel }} (langsamer)</span>
      </div>
      <div class="legend-item" v-if="!hasDelta">
        <span class="legend-line" style="background: #3b82f6;"></span>
        <span class="legend-text">{{ activeLapLabel }}</span>
      </div>
      <div class="legend-item" v-if="hasRef">
        <span class="legend-line dashed" style="background: #f97316;"></span>
        <span class="legend-text">{{ refLapLabel }} (Referenz)</span>
      </div>
    </div>

    <div v-if="!activePath" class="no-data">No track data available</div>
  </div>
</template>

<style scoped>
.track-map {
  width: 100%;
  height: 100%;
  background: var(--bg-secondary);
  position: relative;
}
.track-map svg {
  display: block;
}
.corner-marker {
  cursor: pointer;
}
.corner-marker:hover circle {
  fill: #3b82f6;
}
.no-data {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
}
.map-legend {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(15, 15, 20, 0.85);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  pointer-events: none;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.legend-line {
  width: 16px;
  height: 3px;
  border-radius: 1px;
  flex-shrink: 0;
}
.legend-line.dashed {
  background: repeating-linear-gradient(
    90deg,
    #f97316 0px, #f97316 4px,
    transparent 4px, transparent 7px
  ) !important;
}
.legend-text {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}
</style>
