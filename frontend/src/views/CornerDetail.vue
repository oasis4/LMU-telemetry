<script setup>
import { computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import DeltaStrip from '../components/DeltaStrip.vue'
import CoachingTip from '../components/CoachingTip.vue'

const props = defineProps({
  sessionId: String,
  cornerId: [String, Number],
})

const store = useTelemetryStore()
const router = useRouter()

// Select corner from store on mount / prop change
watch(() => [store.corners, props.cornerId], ([corners, id]) => {
  if (!corners?.length || !id) return
  const c = corners.find(cc => String(cc.id) === String(id))
  if (c) store.setActiveCorner(c)
}, { immediate: true })

const corner = computed(() => store.activeCorner)

// Distance range: generous padding for context
const distanceRange = computed(() => {
  if (!corner.value) return null
  return {
    min: corner.value.distance_start - 100,
    max: corner.value.distance_end + 100,
  }
})

// Previous / next corner navigation
const cornerIndex = computed(() => {
  if (!corner.value || !store.corners?.length) return -1
  return store.corners.findIndex(c => c.id === corner.value.id)
})
const prevCorner = computed(() => {
  const i = cornerIndex.value
  return i > 0 ? store.corners[i - 1] : null
})
const nextCorner = computed(() => {
  const i = cornerIndex.value
  return i >= 0 && i < store.corners.length - 1 ? store.corners[i + 1] : null
})

function goToCorner(c) {
  router.replace({ name: 'corner', params: { sessionId: props.sessionId, cornerId: c.id } })
}

function goBack() {
  store.setActiveCorner(null)
  router.push({ name: 'dashboard', params: { sessionId: props.sessionId } })
}

// Formatting
function formatTime(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

// Client-side coaching for this corner
const coaching = computed(() => {
  const active = store.activeTelemetry
  const reference = store.refTelemetry
  const c = corner.value
  if (!active?.distance?.length || !reference?.distance?.length || !c) return null

  const d = active.distance
  const si = d.findIndex(dd => dd >= c.distance_start)
  const ai = d.findIndex(dd => dd >= c.distance_apex)
  const ei = d.findIndex(dd => dd >= c.distance_end)
  if (si < 0 || ai < 0 || ei < 0) return null

  const dR = reference.distance
  const siR = dR.findIndex(dd => dd >= c.distance_start)
  const aiR = dR.findIndex(dd => dd >= c.distance_apex)
  const eiR = dR.findIndex(dd => dd >= c.distance_end)
  if (siR < 0 || aiR < 0 || eiR < 0) return null

  const tips = []

  // Brake point
  let aBrake = null, rBrake = null
  for (let i = Math.max(0, si - 50); i < ai; i++) {
    if (active.brake[i] > 0.1 && aBrake === null) aBrake = d[i]
  }
  for (let i = Math.max(0, siR - 50); i < aiR; i++) {
    if (reference.brake[i] > 0.1 && rBrake === null) rBrake = dR[i]
  }
  if (aBrake != null && rBrake != null) {
    const diff = aBrake - rBrake
    if (Math.abs(diff) > 5) {
      tips.push({
        icon: '🛑',
        label: diff < 0 ? 'Zu früh gebremst' : 'Zu spät gebremst',
        detail: `${Math.abs(diff).toFixed(0)}m ${diff < 0 ? 'früher' : 'später'} als Referenz`,
      })
    }
  }

  // Min speed
  const aMin = Math.min(...active.speed.slice(si, ei + 1))
  const rMin = Math.min(...reference.speed.slice(siR, eiR + 1))
  if (Math.abs(aMin - rMin) > 3) {
    tips.push({
      icon: aMin < rMin ? '🐢' : '🏎️',
      label: aMin < rMin ? 'Niedrigerer Apex-Speed' : 'Höherer Apex-Speed',
      detail: `${Math.abs(aMin - rMin).toFixed(0)} km/h ${aMin < rMin ? 'langsamer' : 'schneller'}`,
    })
  }

  // Throttle application
  let aThr = null, rThr = null
  for (let i = ai; i < Math.min(ei + 50, active.throttle.length); i++) {
    if (active.throttle[i] > 0.5 && aThr === null) aThr = d[i]
  }
  for (let i = aiR; i < Math.min(eiR + 50, reference.throttle.length); i++) {
    if (reference.throttle[i] > 0.5 && rThr === null) rThr = dR[i]
  }
  if (aThr != null && rThr != null && Math.abs(aThr - rThr) > 5) {
    const diff = aThr - rThr
    tips.push({
      icon: '⚡',
      label: diff > 0 ? 'Spätere Gasannahme' : 'Frühere Gasannahme',
      detail: `${Math.abs(diff).toFixed(0)}m ${diff > 0 ? 'später' : 'früher'} ans Gas`,
    })
  }

  // Delta at this corner
  const deltaData = store.delta
  if (deltaData?.distance?.length) {
    const dsi = deltaData.distance.findIndex(dd => dd >= c.distance_start)
    const dei = deltaData.distance.findIndex(dd => dd >= c.distance_end)
    if (dsi >= 0 && dei >= 0) {
      const cornerDelta = deltaData.delta[dei] - deltaData.delta[dsi]
      tips.unshift({
        icon: cornerDelta > 0.005 ? '🔴' : cornerDelta < -0.005 ? '🟢' : '⚪',
        label: `Delta: ${cornerDelta > 0 ? '+' : ''}${(cornerDelta * 1000).toFixed(0)}ms`,
        detail: cornerDelta > 0.005 ? 'Zeit verloren' : cornerDelta < -0.005 ? 'Zeit gewonnen' : 'Neutral',
      })
    }
  }

  return tips.length > 0 ? tips : null
})
</script>

<template>
  <div class="corner-detail" v-if="corner">
    <!-- Top bar -->
    <header class="cd-header">
      <button class="cd-back" @click="goBack">← Zurück</button>
      <div class="cd-title">
        <span class="cd-badge">{{ corner.id }}</span>
        <span class="cd-name">{{ corner.name }}</span>
      </div>
      <div class="cd-nav">
        <button class="cd-nav-btn" :disabled="!prevCorner" @click="prevCorner && goToCorner(prevCorner)">◀ Prev</button>
        <button class="cd-nav-btn" :disabled="!nextCorner" @click="nextCorner && goToCorner(nextCorner)">Next ▶</button>
      </div>
    </header>

    <!-- Main content -->
    <div class="cd-body">
      <!-- Left: map + coaching tips -->
      <div class="cd-left">
        <div class="cd-map">
          <TrackMap :distance-range="distanceRange" @corner-click="goToCorner" />
        </div>
        <div class="cd-coaching" v-if="coaching">
          <h3 class="cd-section-title">Analyse</h3>
          <div class="cd-tip" v-for="(tip, i) in coaching" :key="i">
            <span class="cd-tip-icon">{{ tip.icon }}</span>
            <div class="cd-tip-body">
              <div class="cd-tip-label">{{ tip.label }}</div>
              <div class="cd-tip-detail">{{ tip.detail }}</div>
            </div>
          </div>
        </div>
        <!-- Corner list nav -->
        <div class="cd-corners-nav">
          <h3 class="cd-section-title">Alle Kurven</h3>
          <div class="cd-corners-list">
            <button
              v-for="c in store.corners" :key="c.id"
              class="cd-corner-btn"
              :class="{ active: corner.id === c.id }"
              @click="goToCorner(c)"
            >
              <span class="cd-corner-num">{{ c.id }}</span>
              {{ c.name }}
            </button>
          </div>
        </div>
      </div>

      <!-- Right: charts -->
      <div class="cd-right">
        <div class="cd-chart-block">
          <div class="cd-chart-label">SPEED</div>
          <div class="cd-chart">
            <TelemetryChart :channels="['speed']" :distance-range="distanceRange" />
          </div>
        </div>
        <div class="cd-chart-block">
          <div class="cd-chart-label">THROTTLE / BRAKE</div>
          <div class="cd-chart">
            <TelemetryChart :channels="['throttle', 'brake']" :distance-range="distanceRange" />
          </div>
        </div>
        <div class="cd-chart-block">
          <div class="cd-chart-label">STEERING</div>
          <div class="cd-chart">
            <TelemetryChart :channels="['steering']" :distance-range="distanceRange" />
          </div>
        </div>
        <div class="cd-delta-block">
          <DeltaStrip :distance-range="distanceRange" />
        </div>
      </div>
    </div>
  </div>
  <div v-else class="cd-loading">Lade Kurvendaten…</div>
</template>

<style scoped>
.corner-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

/* Header */
.cd-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.cd-back {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.cd-back:hover { border-color: #c8ff00; color: #c8ff00; }
.cd-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.cd-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  background: var(--accent-orange);
  border-radius: 50%;
  font-size: 14px; font-weight: 800; color: #000;
}
.cd-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}
.cd-nav { display: flex; gap: 6px; }
.cd-nav-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.cd-nav-btn:hover:not(:disabled) { border-color: var(--text-muted); color: var(--text-primary); }
.cd-nav-btn:disabled { opacity: 0.3; cursor: default; }

/* Body */
.cd-body {
  display: grid;
  grid-template-columns: 340px 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Left panel */
.cd-left {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  background: var(--bg-secondary);
}
.cd-map {
  height: 200px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.cd-section-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  padding: 12px 16px 6px;
  margin: 0;
}

/* Coaching tips */
.cd-coaching {
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
.cd-tip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 6px 16px;
}
.cd-tip-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
.cd-tip-body { flex: 1; }
.cd-tip-label { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.cd-tip-detail { font-size: 11px; color: var(--text-muted); margin-top: 1px; }

/* Corner list */
.cd-corners-nav { flex: 1; min-height: 0; overflow-y: auto; }
.cd-corners-list { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 3px; }
.cd-corner-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.12s;
}
.cd-corner-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.cd-corner-btn.active {
  background: rgba(249, 115, 22, 0.08);
  border-color: var(--accent-orange);
  color: var(--text-primary);
  font-weight: 600;
}
.cd-corner-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px; height: 22px;
  border-radius: 50%;
  background: var(--bg-tertiary);
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  flex-shrink: 0;
}
.cd-corner-btn.active .cd-corner-num {
  background: var(--accent-orange);
  color: #000;
}

/* Right – charts */
.cd-right {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.cd-chart-block {
  flex: 1;
  min-height: 100px;
  display: flex;
  flex-direction: column;
  position: relative;
  border-bottom: 1px solid var(--border);
}
.cd-chart-label {
  position: absolute;
  top: 6px; left: 44px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  z-index: 1;
  pointer-events: none;
  opacity: 0.7;
}
.cd-chart { flex: 1; min-height: 0; overflow: hidden; }
.cd-delta-block {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}

.cd-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 14px;
}
</style>
