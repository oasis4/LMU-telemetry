<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({ sessionId: String })
const store = useTelemetryStore()
const router = useRouter()

function formatTime(ms) {
  if (ms == null || ms === 0) return '—'
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(3)
  return minutes > 0 ? `${minutes}:${seconds.padStart(6, '0')}` : `${seconds}`
}

function formatGap(ms) {
  if (ms === 0) return '—'
  const sign = ms > 0 ? '+' : ''
  return `${sign}${(ms / 1000).toFixed(3)}`
}

function gapClass(ms) {
  if (ms === 0) return ''
  return ms > 0 ? 'text-red' : 'text-green'
}

function isFastest(lap) {
  return store.fastestLap && lap.lap_number === store.fastestLap.lap_number
}

function isActive(lap) {
  return store.activeLap && lap.lap_number === store.activeLap.lap_number
}

function selectLap(lap) {
  store.selectActiveLap(lap.lap_number)
}

function goToAnalysis() {
  router.push({ name: 'analysis', params: { sessionId: props.sessionId } })
}

function goToReport() {
  router.push({ name: 'report', params: { sessionId: props.sessionId } })
}

// Auto-select ref lap as second fastest
const refLapOptions = computed(() =>
  store.laps.filter(l => !store.activeLap || l.lap_number !== store.activeLap.lap_number)
)

function onRefChange(e) {
  store.selectRefLap(Number(e.target.value))
}

onMounted(() => {
  if (!store.laps.length && store.sessionId) {
    store.fetchLaps()
  }
})

watch(() => store.activeLap, (newLap) => {
  if (newLap && store.laps.length > 1) {
    const ref = store.laps.find(l => l.lap_number !== newLap.lap_number)
    if (ref && !store.refLap) {
      store.selectRefLap(ref.lap_number)
    }
  }
})
</script>

<template>
  <div class="lap-overview">
    <div class="lap-header">
      <div class="lap-header-left">
        <h2>Lap Overview</h2>
        <span class="text-muted" v-if="store.currentSession">
          {{ store.currentSession.track }}
        </span>
      </div>
      <div class="lap-header-right">
        <label class="ref-label">
          <span class="text-muted">Compare vs:</span>
          <select class="ref-select" @change="onRefChange" :value="store.refLap?.lap_number">
            <option v-for="l in refLapOptions" :key="l.lap_number" :value="l.lap_number">
              Lap {{ l.lap_number }} — {{ formatTime(l.lap_time_ms) }}
            </option>
          </select>
        </label>
        <button class="btn btn-primary" @click="goToReport">
          Session Report →
        </button>
        <button class="btn" :class="{ 'btn-active': store.activeLap }" @click="goToAnalysis">
          Detail-Analyse →
        </button>
      </div>
    </div>

    <div class="lap-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Lap</th>
            <th>Time</th>
            <th>S1</th>
            <th>S2</th>
            <th>S3</th>
            <th>Gap</th>
            <th>Valid</th>
          </tr>
        </thead>
        <tbody>
          <!-- Theoretical best row -->
          <tr class="theoretical-row" v-if="store.theoreticalBestMs">
            <td class="text-muted">Theo.</td>
            <td class="text-blue">{{ formatTime(store.theoreticalBestMs) }}</td>
            <td class="text-blue">{{ formatTime(store.theoreticalSectors?.s1) }}</td>
            <td class="text-blue">{{ formatTime(store.theoreticalSectors?.s2) }}</td>
            <td class="text-blue">{{ formatTime(store.theoreticalSectors?.s3) }}</td>
            <td>—</td>
            <td>—</td>
          </tr>
          <tr
            v-for="lap in store.laps"
            :key="lap.lap_number"
            :class="{
              'row-fastest': isFastest(lap),
              'row-active': isActive(lap),
            }"
            @click="selectLap(lap)"
          >
            <td>{{ lap.lap_number }}</td>
            <td>{{ formatTime(lap.lap_time_ms) }}</td>
            <td>{{ formatTime(lap.sectors?.s1) }}</td>
            <td>{{ formatTime(lap.sectors?.s2) }}</td>
            <td>{{ formatTime(lap.sectors?.s3) }}</td>
            <td :class="gapClass(lap.gap_to_best_ms)">{{ formatGap(lap.gap_to_best_ms) }}</td>
            <td>{{ lap.valid ? '✓' : '✗' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.lap-overview {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
}
.lap-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.lap-header-left h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.lap-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.ref-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.ref-select {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 4px 8px;
  font-family: var(--font-mono);
  font-size: 11px;
}
.lap-table-wrap {
  flex: 1;
  overflow-y: auto;
}
tr {
  cursor: pointer;
  transition: background 0.1s;
}
tr:hover {
  background: var(--bg-tertiary);
}
.theoretical-row {
  border-bottom: 2px solid var(--border);
  font-style: italic;
}
.row-fastest td {
  color: var(--accent-blue);
}
.row-active {
  background: rgba(249, 115, 22, 0.08);
  border-left: 2px solid var(--accent-orange);
}
.row-active td:first-child {
  color: var(--accent-orange);
  font-weight: 700;
}
</style>
