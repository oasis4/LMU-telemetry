<script setup>
import { computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()

// Compute delta at each corner apex
const cornersWithDelta = computed(() => {
  return store.corners.map(c => {
    let deltaAtApex = null
    if (store.delta && store.delta.distance?.length) {
      const idx = store.delta.distance.findIndex(d => d >= c.distance_apex)
      if (idx >= 0) {
        deltaAtApex = store.delta.delta[idx]
      }
    }
    return { ...c, deltaAtApex }
  })
})

function formatDelta(d) {
  if (d == null) return '—'
  const ms = d * 1000
  const sign = ms > 0 ? '+' : ''
  return `${sign}${ms.toFixed(0)}ms`
}

function deltaClass(d) {
  if (d == null) return ''
  return d > 0.01 ? 'text-red' : d < -0.01 ? 'text-green' : ''
}

function selectCorner(c) {
  store.setActiveCorner(store.activeCorner?.id === c.id ? null : c)
}
</script>

<template>
  <div class="corner-list">
    <div class="corner-list-header">
      <span>Corners</span>
      <span class="text-muted">{{ store.corners.length }}</span>
    </div>
    <div
      v-for="c in cornersWithDelta"
      :key="c.id"
      class="corner-item"
      :class="{ active: store.activeCorner?.id === c.id }"
      @click="selectCorner(c)"
    >
      <div class="corner-name">{{ c.name }}</div>
      <div class="corner-speed mono">{{ c.min_speed.toFixed(0) }} km/h</div>
      <div class="corner-delta mono" :class="deltaClass(c.deltaAtApex)">
        {{ formatDelta(c.deltaAtApex) }}
      </div>
    </div>
    <div v-if="store.corners.length === 0" class="no-corners text-muted">
      No corners detected
    </div>
  </div>
</template>

<style scoped>
.corner-list {
  padding: 8px 0;
}
.corner-list-header {
  display: flex;
  justify-content: space-between;
  padding: 8px 14px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}
.corner-item {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  cursor: pointer;
  transition: background 0.1s;
  border-left: 2px solid transparent;
}
.corner-item:hover {
  background: var(--bg-tertiary);
}
.corner-item.active {
  background: rgba(59, 130, 246, 0.08);
  border-left-color: var(--accent-blue);
}
.corner-name {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
}
.corner-speed {
  font-size: 11px;
  color: var(--text-secondary);
}
.corner-delta {
  font-size: 11px;
  text-align: right;
}
.no-corners {
  padding: 20px 14px;
  text-align: center;
  font-size: 12px;
}
</style>
