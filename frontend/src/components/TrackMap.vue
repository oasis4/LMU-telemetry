<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  distanceRange: { type: Object, default: null },
})

const store = useTelemetryStore()
const svgRef = ref(null)
const containerRef = ref(null)
const width = ref(800)
const height = ref(300)

// Normalise lat/lon to SVG viewport
function normalise(arr, size, padding = 20) {
  if (!arr || arr.length === 0) return []
  const min = Math.min(...arr)
  const max = Math.max(...arr)
  const range = max - min || 1
  return arr.map(v => padding + ((v - min) / range) * (size - 2 * padding))
}

const activePath = computed(() => {
  const t = store.activeTelemetry
  if (!t || !t.lat?.length) return ''
  const xs = normalise(t.lat, width.value)
  const ys = normalise(t.lon, height.value)
  return xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x},${ys[i]}`).join(' ')
})

const refPath = computed(() => {
  const t = store.refTelemetry
  if (!t || !t.lat?.length) return ''
  const xs = normalise(t.lat, width.value)
  const ys = normalise(t.lon, height.value)
  return xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x},${ys[i]}`).join(' ')
})

// Corner markers with delta values
const cornerMarkers = computed(() => {
  const t = store.activeTelemetry
  if (!t || !t.distance?.length || !t.lat?.length) return []
  const xs = normalise(t.lat, width.value)
  const ys = normalise(t.lon, height.value)
  const d = store.delta
  return store.corners.map(c => {
    const idx = t.distance.findIndex(dd => dd >= c.distance_apex)
    if (idx < 0) return null
    let deltaAtApex = null
    if (d?.distance?.length) {
      const di = d.distance.findIndex(dd => dd >= c.distance_apex)
      if (di >= 0) deltaAtApex = d.delta[di]
    }
    const deltaColor = deltaAtApex == null ? '#888'
      : deltaAtApex > 0.01 ? '#ef4444'
      : deltaAtApex < -0.01 ? '#22c55e' : '#888'
    const deltaLabel = deltaAtApex == null ? ''
      : deltaAtApex > 0 ? `+${deltaAtApex.toFixed(3)}`
      : deltaAtApex.toFixed(3)
    return { ...c, x: xs[idx], y: ys[idx], deltaAtApex, deltaColor, deltaLabel }
  }).filter(Boolean)
})

// Delta-colored segments for active path
const deltaSegments = computed(() => {
  const t = store.activeTelemetry
  const d = store.delta
  if (!t || !t.lat?.length || !d || !d.delta?.length) return []

  const xs = normalise(t.lat, width.value)
  const ys = normalise(t.lon, height.value)

  const segments = []
  const step = Math.max(1, Math.floor(t.distance.length / 200))
  for (let i = 0; i < t.distance.length - step; i += step) {
    const dist = t.distance[i]
    const deltaIdx = d.distance.findIndex(dd => dd >= dist)
    const deltaVal = deltaIdx >= 0 ? d.delta[deltaIdx] : 0
    let color = '#666'
    if (deltaVal < -0.01) color = '#22c55e' // gaining
    else if (deltaVal > 0.01) color = '#ef4444' // losing
    segments.push({
      x1: xs[i], y1: ys[i],
      x2: xs[Math.min(i + step, xs.length - 1)],
      y2: ys[Math.min(i + step, ys.length - 1)],
      color,
    })
  }
  return segments
})

// Cursor dot on track map
const cursorDot = computed(() => {
  const t = store.activeTelemetry
  if (!t || !t.distance?.length || store.cursorDistance == null) return null
  const xs = normalise(t.lat, width.value)
  const ys = normalise(t.lon, height.value)
  const idx = t.distance.findIndex(d => d >= store.cursorDistance)
  if (idx < 0) return null
  return { x: xs[idx], y: ys[idx] }
})

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
  store.setActiveCorner(c)
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

      <!-- Reference lap path -->
      <path
        v-if="refPath"
        :d="refPath"
        fill="none"
        stroke="#f97316"
        stroke-width="2.5"
        opacity="0.7"
      />

      <!-- Active lap path (drawn on top if no delta) -->
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
</style>
