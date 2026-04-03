<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'

const router = useRouter()

const store = useTelemetryStore()
const selectedTrack = ref('')
const expandedCorner = ref(null)
const selectedDriver = ref('')

onMounted(async () => {
  await store.fetchLoadedSessions()
  if (store.tracks.length === 1) {
    selectedTrack.value = store.tracks[0]
    await runCompare()
  }
})

async function runCompare() {
  if (!selectedTrack.value && store.tracks.length > 0) {
    selectedTrack.value = store.tracks[0]
  }
  await store.fetchComparison(selectedTrack.value)
}

function toggleCorner(cornerId) {
  expandedCorner.value = expandedCorner.value === cornerId ? null : cornerId
}

function formatTime(ms) {
  if (ms == null || ms === 0) return '—'
  return (ms / 1000).toFixed(3) + 's'
}

function formatSpeed(v) {
  return v != null ? v.toFixed(0) : '—'
}

function formatDist(v) {
  return v != null ? v.toFixed(0) + 'm' : '—'
}

const driverColors = ['#3b82f6', '#f97316', '#22c55e', '#a855f7', '#ef4444', '#eab308', '#06b6d4', '#ec4899']

function driverColor(driverName) {
  if (!store.comparison) return '#888'
  const idx = store.comparison.drivers.indexOf(driverName)
  return driverColors[idx % driverColors.length]
}

const filteredTips = computed(() => {
  if (!store.comparison || !selectedDriver.value) return []
  const tips = []
  for (const c of store.comparison.corners) {
    const driverTips = c.tips[selectedDriver.value]
    if (driverTips && driverTips.length > 0) {
      tips.push({ corner: c.corner_name, cornerId: c.corner_id, tips: driverTips })
    }
  }
  return tips
})
</script>

<template>
  <div class="compare-layout">
    <!-- Header -->
    <div class="compare-header">
      <button class="btn-back" @click="router.push({ name: 'sessions' })">← Sessions</button>
      <h2>Driver Comparison</h2>
      <div class="header-controls">
        <label class="track-label">
          <span class="text-muted">Track:</span>
          <select v-model="selectedTrack" class="track-select" @change="runCompare">
            <option value="">All</option>
            <option v-for="t in store.tracks" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <button class="btn" @click="runCompare" :disabled="store.loading">
          {{ store.loading ? 'Loading…' : 'Compare' }}
        </button>
      </div>
    </div>

    <div v-if="!store.comparison && !store.loading" class="empty-state">
      <p>Load at least 2 sessions with different driver names, then click <strong>Compare</strong>.</p>
      <p class="text-muted">Loaded drivers: {{ store.drivers.join(', ') || 'none' }}</p>
    </div>

    <div v-if="store.comparison" class="compare-body">
      <!-- Driver legend -->
      <div class="driver-legend">
        <button
          v-for="d in store.comparison.drivers"
          :key="d"
          class="driver-tag"
          :class="{ active: selectedDriver === d }"
          :style="{ '--driver-color': driverColor(d) }"
          @click="selectedDriver = selectedDriver === d ? '' : d"
        >
          {{ d }}
        </button>
      </div>

      <!-- Corner table -->
      <div class="corner-table-wrap">
        <table class="corner-table">
          <thead>
            <tr>
              <th>Corner</th>
              <th v-for="d in store.comparison.drivers" :key="d"
                  :style="{ color: driverColor(d) }">
                {{ d }}
              </th>
              <th>Best</th>
              <th>Δ</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="c in store.comparison.corners" :key="c.corner_id">
              <tr class="corner-row" @click="toggleCorner(c.corner_id)">
                <td class="corner-name">{{ c.corner_name }}</td>
                <td v-for="dm in c.drivers" :key="dm.driver"
                    :class="{ 'cell-best': dm.driver === c.best_driver }">
                  {{ formatTime(dm.corner_time_ms) }}
                </td>
                <td class="cell-best-driver" :style="{ color: driverColor(c.best_driver) }">
                  {{ c.best_driver }}
                </td>
                <td class="cell-delta">
                  <template v-if="c.drivers.length > 1">
                    {{ formatTime(
                      Math.max(...c.drivers.map(d => d.corner_time_ms)) -
                      c.best_time_ms
                    ) }}
                  </template>
                </td>
              </tr>
              <!-- Expanded detail -->
              <tr v-if="expandedCorner === c.corner_id" class="detail-row">
                <td :colspan="c.drivers.length + 3">
                  <div class="detail-grid">
                    <div v-for="dm in c.drivers" :key="dm.driver" class="detail-card"
                         :style="{ borderColor: driverColor(dm.driver) }">
                      <div class="detail-driver" :style="{ color: driverColor(dm.driver) }">
                        {{ dm.driver }}
                      </div>
                      <div class="detail-metrics">
                        <div><span class="label">Entry</span> {{ formatSpeed(dm.entry_speed) }} km/h</div>
                        <div><span class="label">Apex</span> {{ formatSpeed(dm.apex_speed) }} km/h</div>
                        <div><span class="label">Exit</span> {{ formatSpeed(dm.exit_speed) }} km/h</div>
                        <div><span class="label">Min</span> {{ formatSpeed(dm.min_speed) }} km/h</div>
                        <div><span class="label">Brake @</span> {{ formatDist(dm.brake_point) }}</div>
                        <div><span class="label">Throttle @</span> {{ formatDist(dm.throttle_point) }}</div>
                      </div>
                      <!-- Tips for this driver -->
                      <div v-if="c.tips[dm.driver] && c.tips[dm.driver].length" class="detail-tips">
                        <div v-for="(tip, i) in c.tips[dm.driver]" :key="i" class="tip-item">
                          💡 {{ tip }}
                        </div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Coaching panel for selected driver -->
      <div v-if="selectedDriver && filteredTips.length" class="coaching-panel">
        <h3>Coaching for <span :style="{ color: driverColor(selectedDriver) }">{{ selectedDriver }}</span></h3>
        <div v-for="ct in filteredTips" :key="ct.cornerId" class="coaching-corner">
          <div class="coaching-corner-name">{{ ct.corner }}</div>
          <div v-for="(tip, i) in ct.tips" :key="i" class="coaching-tip">{{ tip }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.compare-layout {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
  overflow-y: auto;
}
.compare-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.btn-back {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: var(--font-sans);
}
.btn-back:hover {
  color: var(--accent-blue);
  border-color: var(--accent-blue);
}
.compare-header h2 {
  font-size: 16px;
  font-weight: 600;
  flex: 1;
}
.header-controls {
  margin-left: auto;
}
.header-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}
.track-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.track-select {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 4px 8px;
  font-size: 12px;
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.compare-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.driver-legend {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.driver-tag {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  border: 2px solid var(--driver-color);
  color: var(--driver-color);
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.driver-tag.active {
  background: var(--driver-color);
  color: #fff;
}
.corner-table-wrap {
  overflow-x: auto;
}
.corner-table {
  width: 100%;
  border-collapse: collapse;
}
.corner-table th, .corner-table td {
  text-align: left;
  padding: 8px 12px;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.corner-table th {
  font-weight: 600;
  color: var(--text-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.corner-row {
  cursor: pointer;
  transition: background 0.1s;
}
.corner-row:hover {
  background: var(--bg-tertiary);
}
.corner-name {
  font-weight: 500;
}
.cell-best {
  color: var(--accent-green);
  font-weight: 600;
}
.cell-best-driver {
  font-weight: 600;
}
.cell-delta {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
}
.detail-row td {
  padding: 12px;
  background: var(--bg-secondary);
}
.detail-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.detail-card {
  flex: 1;
  min-width: 200px;
  border-left: 3px solid;
  padding: 12px;
  background: var(--bg-tertiary);
}
.detail-driver {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 8px;
}
.detail-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  font-size: 11px;
  color: var(--text-primary);
}
.detail-metrics .label {
  color: var(--text-muted);
  margin-right: 4px;
}
.detail-tips {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tip-item {
  font-size: 11px;
  color: var(--accent-orange);
  line-height: 1.4;
}
.coaching-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  padding: 16px;
}
.coaching-panel h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}
.coaching-corner {
  margin-bottom: 12px;
}
.coaching-corner-name {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 4px;
  color: var(--text-primary);
}
.coaching-tip {
  font-size: 12px;
  color: var(--accent-orange);
  padding-left: 16px;
  line-height: 1.5;
}
</style>
