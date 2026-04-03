<script setup>
import { computed, onMounted, watch, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import CornerCard from '../components/CornerCard.vue'

const props = defineProps({ sessionId: String })
const store = useTelemetryStore()
const router = useRouter()
const selectedLapNumber = ref(null)

// Auto-setup: best lap = reference, pick another lap for comparison
onMounted(async () => {
  if (!store.laps.length && store.sessionId) {
    await store.fetchLaps()
  }
  autoSetup()
})

watch(() => store.laps, () => autoSetup(), { deep: true })

function autoSetup() {
  if (!store.laps.length) return

  const best = store.fastestLap
  if (!best) return

  // If no ref lap set, or ref is not the best, set best as ref
  if (!store.refLap || store.refLap.lap_number !== best.lap_number) {
    store.selectRefLap(best.lap_number)
  }

  // Auto-select a comparison lap (second best, or any other than best)
  if (!store.activeLap || store.activeLap.lap_number === best.lap_number) {
    const sorted = [...store.laps].sort((a, b) => a.lap_time_ms - b.lap_time_ms)
    const secondBest = sorted.find(l => l.lap_number !== best.lap_number)
    if (secondBest) {
      store.selectActiveLap(secondBest.lap_number)
      selectedLapNumber.value = secondBest.lap_number
    } else {
      // Only one lap, compare to itself
      store.selectActiveLap(best.lap_number)
      selectedLapNumber.value = best.lap_number
    }
  } else {
    selectedLapNumber.value = store.activeLap.lap_number
  }
}

function onLapChange(e) {
  const lapNum = Number(e.target.value)
  selectedLapNumber.value = lapNum
  store.selectActiveLap(lapNum).then(() => {
    // Re-compute delta against best lap
    if (store.fastestLap) {
      store.selectRefLap(store.fastestLap.lap_number)
    }
  })
}

// Lap options: all laps except the best (reference)
const lapOptions = computed(() => {
  return store.laps.filter(l => !store.fastestLap || l.lap_number !== store.fastestLap.lap_number)
})

// Session info
const sessionInfo = computed(() => store.currentSession)

// Format time helpers
function formatTime(ms) {
  if (ms == null || ms === 0) return '—'
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(3)
  return minutes > 0 ? `${minutes}:${seconds.padStart(6, '0')}` : `${seconds}`
}

function formatGap(ms) {
  if (ms == null || ms === 0) return '—'
  const sign = ms > 0 ? '+' : ''
  return `${sign}${(ms / 1000).toFixed(3)}s`
}

// Distance range for track map (full lap)
const distanceRange = computed(() => null)

// Per-corner delta summary
const cornerDeltas = computed(() => {
  if (!store.corners.length || !store.delta?.distance?.length) return []
  return store.corners.map((c, i) => {
    // Delta at this corner's apex
    const idx = store.delta.distance.findIndex(d => d >= c.distance_apex)
    const cumDelta = idx >= 0 ? store.delta.delta[idx] : 0
    // Delta at previous corner's apex (or start)
    let prevCumDelta = 0
    if (i > 0) {
      const prevApex = store.corners[i - 1].distance_apex
      const prevIdx = store.delta.distance.findIndex(d => d >= prevApex)
      prevCumDelta = prevIdx >= 0 ? store.delta.delta[prevIdx] : 0
    }
    const segmentDelta = (cumDelta - prevCumDelta) * 1000 // ms
    return {
      ...c,
      segmentDeltaMs: segmentDelta,
      cumDeltaMs: cumDelta * 1000,
    }
  })
})

// Total delta
const totalDeltaMs = computed(() => {
  if (!store.activeLap || !store.fastestLap) return null
  return store.activeLap.lap_time_ms - store.fastestLap.lap_time_ms
})

function goToDetailAnalysis() {
  router.push({ name: 'analysis', params: { sessionId: props.sessionId } })
}
</script>

<template>
  <div class="report-layout">
    <!-- Header bar -->
    <div class="report-header">
      <div class="header-left">
        <h2>Session Report</h2>
        <div class="session-meta" v-if="sessionInfo">
          <span class="meta-track">{{ sessionInfo.track }}</span>
          <span class="meta-car">{{ sessionInfo.car }}</span>
        </div>
      </div>
      <div class="header-right">
        <div class="lap-selector">
          <span class="selector-label">Deine Runde:</span>
          <select class="lap-select" :value="selectedLapNumber" @change="onLapChange">
            <option v-for="l in lapOptions" :key="l.lap_number" :value="l.lap_number">
              Runde {{ l.lap_number }} — {{ formatTime(l.lap_time_ms) }}
            </option>
          </select>
        </div>
        <div class="ref-info" v-if="store.fastestLap">
          <span class="ref-label">vs Beste:</span>
          <span class="ref-time mono">Runde {{ store.fastestLap.lap_number }} — {{ formatTime(store.fastestLap.lap_time_ms) }}</span>
        </div>
        <button class="btn" @click="goToDetailAnalysis">Detail-Analyse →</button>
      </div>
    </div>

    <!-- Summary strip -->
    <div class="summary-strip" v-if="store.activeLap && store.fastestLap">
      <div class="summary-times">
        <div class="time-block">
          <span class="time-label">Deine Zeit</span>
          <span class="time-value mono">{{ formatTime(store.activeLap?.lap_time_ms) }}</span>
        </div>
        <div class="time-block">
          <span class="time-label">Beste</span>
          <span class="time-value mono text-blue">{{ formatTime(store.fastestLap?.lap_time_ms) }}</span>
        </div>
        <div class="time-block">
          <span class="time-label">Delta</span>
          <span class="time-value mono" :class="totalDeltaMs > 0 ? 'text-red' : 'text-green'">
            {{ formatGap(totalDeltaMs) }}
          </span>
        </div>
      </div>
      <div class="corner-summary-strip">
        <div
          v-for="cd in cornerDeltas"
          :key="cd.id"
          class="corner-chip"
          :class="{
            'chip-losing': cd.segmentDeltaMs > 20,
            'chip-gaining': cd.segmentDeltaMs < -20,
            'chip-neutral': Math.abs(cd.segmentDeltaMs) <= 20,
          }"
        >
          <span class="chip-name">{{ cd.name }}</span>
          <span class="chip-delta mono">{{ cd.segmentDeltaMs > 0 ? '+' : '' }}{{ cd.segmentDeltaMs.toFixed(0) }}ms</span>
        </div>
      </div>
    </div>

    <!-- Track map -->
    <div class="track-area">
      <TrackMap :distance-range="distanceRange" />
    </div>

    <!-- Corner cards -->
    <div class="corner-cards">
      <CornerCard
        v-for="c in store.corners"
        :key="c.id"
        :corner="c"
        :active-telemetry="store.activeTelemetry"
        :ref-telemetry="store.refTelemetry"
        :delta="store.delta"
      />
      <div v-if="store.corners.length === 0 && !store.loading" class="no-data">
        Keine Kurven erkannt. Lade eine Session mit ausreichend Telemetriedaten.
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-layout {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
}

/* Header */
.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 12px;
}
.header-left {
  display: flex;
  align-items: baseline;
  gap: 16px;
}
.header-left h2 {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
}
.session-meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.meta-track {
  color: var(--accent-blue);
  font-weight: 600;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.lap-selector {
  display: flex;
  align-items: center;
  gap: 6px;
}
.selector-label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.lap-select {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 4px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
}
.ref-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.ref-label {
  color: var(--text-muted);
}
.ref-time {
  color: var(--accent-blue);
  font-size: 11px;
}

/* Summary strip */
.summary-strip {
  padding: 12px 20px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.summary-times {
  display: flex;
  gap: 32px;
  margin-bottom: 12px;
}
.time-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.time-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
}
.time-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}
.corner-summary-strip {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.corner-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 10px;
  border-radius: 4px;
  min-width: 56px;
}
.chip-losing {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
}
.chip-gaining {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.25);
}
.chip-neutral {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
}
.chip-name {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-primary);
}
.chip-delta {
  font-size: 10px;
  font-weight: 600;
}
.chip-losing .chip-delta { color: var(--negative); }
.chip-gaining .chip-delta { color: var(--positive); }
.chip-neutral .chip-delta { color: var(--text-muted); }

/* Track map area */
.track-area {
  height: 200px;
  min-height: 160px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}

/* Corner cards */
.corner-cards {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.no-data {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
  font-size: 14px;
}
</style>
