<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import DeltaStrip from '../components/DeltaStrip.vue'
import CoachingTip from '../components/CoachingTip.vue'

const props = defineProps({ sessionId: String })
const store = useTelemetryStore()
const router = useRouter()

// Corner zoom range
const distanceRange = computed(() => {
  if (store.activeCorner) {
    return {
      min: store.activeCorner.distance_start - 50,
      max: store.activeCorner.distance_end + 50,
    }
  }
  return null
})

// Formatting helpers
function formatTime(ms) {
  if (!ms) return '—'
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}
function fmtTimeSec(secs) {
  if (!secs || secs <= 0) return '—'
  const m = Math.floor(secs / 60)
  const s = secs - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}
function formatDelta(ms) {
  if (ms == null || ms === 0) return ''
  const sign = ms > 0 ? '+' : ''
  return `${sign}${(ms / 1000).toFixed(3)}`
}
function gapClass(ms) {
  if (!ms || ms === 0) return ''
  return ms > 0 ? 'gap-red' : 'gap-green'
}
function isFastest(lap) {
  return store.fastestLap && lap.lap_number === store.fastestLap.lap_number
}
function isActive(lap) {
  return store.activeLap && lap.lap_number === store.activeLap.lap_number
}

// Totals
const totalDelta = computed(() => {
  if (!store.activeLap?.lap_time_ms || !store.refLap?.lap_time_ms) return null
  return store.activeLap.lap_time_ms - store.refLap.lap_time_ms
})

const sessionMeta = computed(() => {
  const fn = store.currentSession?.filename
  if (!fn) return { type: '', date: '' }
  const m = fn.match(/_([PQR])_(\d{4})-(\d{2})-(\d{2})T(\d{2})_(\d{2})/)
  if (!m) return { type: '', date: '' }
  const types = { P: 'Practice', Q: 'Qualifying', R: 'Race' }
  return { type: types[m[1]] || m[1], date: `${m[3]}.${m[4]}.${m[2]} ${m[5]}:${m[6]}` }
})

// Segment data (sectors)
const segments = computed(() => {
  const active = store.activeLap
  const rLap = store.refLap
  if (!active?.sectors) return []
  const names = ['Seg 1', 'Seg 2', 'Seg 3']
  const keys = ['s1', 's2', 's3']
  return keys.map((k, i) => {
    const time = active.sectors?.[k] || 0
    const refTime = rLap?.sectors?.[k] || 0
    const diff = time && refTime ? time - refTime : null
    return { name: names[i], time, diff }
  }).filter(s => s.time > 0)
})

// Reference: same-session laps
const refOptions = computed(() =>
  store.laps.filter(l => !store.activeLap || l.lap_number !== store.activeLap.lap_number)
)

// Reference: driver bests (cross-session)
const driverBests = computed(() => store.driverBests || [])

// Track the dropdown value directly from user selection
const refValue = ref('')

async function onRefChange() {
  const val = refValue.value
  try {
    if (val === 'composite') {
      await store.selectRefLap(0)
    } else if (val.startsWith('lap:')) {
      await store.selectRefLap(Number(val.substring(4)))
    } else if (val.startsWith('driver:')) {
      const filename = val.substring(7)
      const db = driverBests.value.find(d => d.filename === filename)
      if (db) await store.loadDriverBestRef(filename, db.driver)
    }
  } catch (err) {
    console.error('ref change error', err)
  }
}

function selectLap(lap) {
  store.selectActiveLap(lap.lap_number)
}

function onCornerClick(c) {
  store.setActiveCorner(c)
  router.push({ name: 'corner', params: { sessionId: props.sessionId, cornerId: c.id } })
}

function closeCorner() {
  store.setActiveCorner(null)
}

// Collapsible panel state
const panelOpen = ref({ stats: true, segments: true, ref: true, laps: true })

// Sync refValue dropdown when store.refLap changes (e.g. auto-selected in store)
watch(() => store.refLap, (lap) => {
  if (lap && !refValue.value) {
    refValue.value = `lap:${lap.lap_number}`
  }
}, { immediate: true })

// Fetch driver bests when session loads
watch(() => store.currentSession?.track, (track) => {
  if (track) store.fetchDriverBests(track)
}, { immediate: true })

// Client-side coaching
function classifyError(active, ref, corner) {
  const d = active.distance
  const si = d.findIndex(dd => dd >= corner.distance_start)
  const ai = d.findIndex(dd => dd >= corner.distance_apex)
  const ei = d.findIndex(dd => dd >= corner.distance_end)
  if (si < 0 || ai < 0 || ei < 0) return { type: null, label: '', explanation: '', recommendation: '' }
  const dR = ref.distance
  const siR = dR.findIndex(dd => dd >= corner.distance_start)
  const aiR = dR.findIndex(dd => dd >= corner.distance_apex)
  const eiR = dR.findIndex(dd => dd >= corner.distance_end)
  if (siR < 0 || aiR < 0 || eiR < 0) return { type: null, label: '', explanation: '', recommendation: '' }
  const errors = []
  let aBrake = null, rBrake = null
  for (let i = Math.max(0, si - 50); i < ai; i++) {
    if (active.brake[i] > 0.1 && aBrake === null) aBrake = d[i]
  }
  for (let i = Math.max(0, siR - 50); i < aiR; i++) {
    if (ref.brake[i] > 0.1 && rBrake === null) rBrake = dR[i]
  }
  if (aBrake != null && rBrake != null) {
    const diff = aBrake - rBrake
    if (diff < -8) errors.push({ severity: Math.abs(diff), type: 'early_brake', label: 'Zu frühes Bremsen', explanation: `Du bremst ${Math.abs(diff).toFixed(0)}m früher als die Referenz.`, recommendation: 'Versuche den Bremspunkt nach hinten zu verschieben.' })
    else if (diff > 8) errors.push({ severity: diff, type: 'late_brake', label: 'Zu spätes Bremsen', explanation: `Du bremst ${diff.toFixed(0)}m später als die Referenz.`, recommendation: 'Bremse etwas früher, um den Apex sauber zu treffen.' })
  }
  const aMin = Math.min(...active.speed.slice(si, ei + 1))
  const rMin = Math.min(...ref.speed.slice(siR, eiR + 1))
  if (aMin - rMin < -5) errors.push({ severity: Math.abs(aMin - rMin), type: 'low_min_speed', label: 'Zu niedriges Kurvenminimum', explanation: `Dein Minimum-Speed ist ${Math.abs(aMin - rMin).toFixed(0)} km/h langsamer.`, recommendation: 'Trage mehr Geschwindigkeit in die Kurve.' })
  let aThr = null, rThr = null
  for (let i = ai; i < Math.min(ei + 50, active.throttle.length); i++) {
    if (active.throttle[i] > 0.5 && aThr === null) aThr = d[i]
  }
  for (let i = aiR; i < Math.min(eiR + 50, ref.throttle.length); i++) {
    if (ref.throttle[i] > 0.5 && rThr === null) rThr = dR[i]
  }
  if (aThr != null && rThr != null && aThr - rThr > 8) errors.push({ severity: aThr - rThr, type: 'bad_traction', label: 'Schlechte Gasannahme / Traktion', explanation: `Du gehst ${(aThr - rThr).toFixed(0)}m später aufs Gas.`, recommendation: 'Gehe früher und progressiver ans Gas.' })
  if (!errors.length) return { type: null, label: '', explanation: '', recommendation: '' }
  errors.sort((a, b) => b.severity - a.severity)
  return errors[0]
}

const clientCoaching = computed(() => {
  const active = store.activeTelemetry
  const reference = store.refTelemetry
  const deltaData = store.delta
  const cornerData = store.corners
  if (!active?.distance?.length || !reference?.distance?.length || !deltaData?.distance?.length || !cornerData?.length) return null
  const segs = []
  let worstSegment = null
  for (const c of cornerData) {
    const si = deltaData.distance.findIndex(d => d >= c.distance_start)
    const ei = deltaData.distance.findIndex(d => d >= c.distance_end)
    let delta_s = 0
    if (si >= 0 && ei >= 0 && ei > si) delta_s = deltaData.delta[ei] - deltaData.delta[si]
    const err = classifyError(active, reference, c)
    const seg = { corner_id: c.id, corner_name: c.name, distance_start: c.distance_start, distance_apex: c.distance_apex, distance_end: c.distance_end, delta_s, error_type: err.type, error_label: err.label, explanation: err.explanation, recommendation: err.recommendation }
    segs.push(seg)
    if (!worstSegment || delta_s > worstSegment.delta_s) worstSegment = seg
  }
  let focus_zone = null
  let main_message = ''
  if (worstSegment && worstSegment.delta_s > 0.01) {
    focus_zone = { distance_start: worstSegment.distance_start, distance_end: worstSegment.distance_end, delta_s: worstSegment.delta_s, corner_name: worstSegment.corner_name }
    main_message = worstSegment.error_label
      ? `Größter Verlust: ${worstSegment.corner_name} (${worstSegment.delta_s > 0 ? '+' : ''}${worstSegment.delta_s.toFixed(3)}s) — ${worstSegment.error_label}`
      : `Größter Verlust: ${worstSegment.corner_name} (${worstSegment.delta_s > 0 ? '+' : ''}${worstSegment.delta_s.toFixed(3)}s)`
  }
  return { segments: segs, focus_zone, main_message }
})

watch(clientCoaching, (val) => { store.coaching = val }, { immediate: true })

onMounted(() => {
  if (!store.laps.length && store.sessionId) store.fetchLaps()
})
</script>

<template>
  <div class="dashboard">
    <!-- ===== LEFT SIDEBAR ===== -->
    <aside class="sidebar">
      <div class="session-block">
        <div class="session-label">SESSION LAP {{ store.activeLap?.lap_number || '—' }}</div>
        <div class="session-time">{{ formatTime(store.activeLap?.lap_time_ms) }}</div>
        <div class="session-deltas" v-if="totalDelta != null">
          <span :class="gapClass(totalDelta)">{{ formatDelta(totalDelta) }}</span>
        </div>
        <div class="session-car" v-if="store.currentSession">
          <span class="lm-badge-sm">LM</span>
          <div>
            <div class="car-name">{{ store.currentSession.car }}</div>
            <div class="track-name">{{ store.currentSession.track }}</div>
          </div>
        </div>
        <div class="session-date" v-if="sessionMeta.date">{{ sessionMeta.type }} · {{ sessionMeta.date }}</div>
      </div>

      <!-- Stats (collapsible) -->
      <div class="panel">
        <div class="panel-header" @click="panelOpen.stats = !panelOpen.stats">
          <span class="panel-chevron" :class="{ open: panelOpen.stats }">▸</span>
          <span class="panel-title">Stats</span>
        </div>
        <div class="panel-body" v-show="panelOpen.stats">
          <table class="stats-table">
            <tbody>
              <tr>
                <td class="stat-label">Fastest Lap</td>
                <td class="stat-value mono">{{ formatTime(store.fastestLap?.lap_time_ms) }}</td>
                <td class="stat-diff mono" :class="gapClass(totalDelta)">{{ formatDelta(totalDelta) }}</td>
              </tr>
              <tr v-if="store.theoreticalBestMs">
                <td class="stat-label">Best Possible</td>
                <td class="stat-value mono">{{ formatTime(store.theoreticalBestMs) }}</td>
                <td class="stat-diff"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Segments (collapsible) -->
      <div class="panel" v-if="segments.length">
        <div class="panel-header" @click="panelOpen.segments = !panelOpen.segments">
          <span class="panel-chevron" :class="{ open: panelOpen.segments }">▸</span>
          <span class="panel-title">Segments</span>
        </div>
        <div class="panel-body" v-show="panelOpen.segments">
          <table class="stats-table">
            <tbody>
              <tr v-for="seg in segments" :key="seg.name">
                <td class="stat-label">{{ seg.name }}</td>
                <td class="stat-value mono">{{ formatTime(seg.time) }}</td>
                <td class="stat-diff mono" :class="gapClass(seg.diff)">{{ seg.diff != null ? formatDelta(seg.diff) : '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Reference selector (collapsible) -->
      <div class="panel">
        <div class="panel-header" @click="panelOpen.ref = !panelOpen.ref">
          <span class="panel-chevron" :class="{ open: panelOpen.ref }">▸</span>
          <span class="panel-title">Reference</span>
          <span class="panel-badge" v-if="store.refLap">Lap {{ store.refLap.lap_number }}</span>
        </div>
        <div class="panel-body" v-show="panelOpen.ref">
          <select class="ref-select" v-model="refValue" @change="onRefChange">
            <option value="" disabled>Referenz wählen…</option>
            <optgroup label="Diese Session">
              <option v-if="store.compositeAvailable" value="composite">
                Best Composite — {{ formatTime(store.theoreticalBestMs) }}
              </option>
              <option v-for="l in refOptions" :key="l.lap_number" :value="'lap:' + l.lap_number">
                Lap {{ l.lap_number }} — {{ formatTime(l.lap_time_ms) }}{{ !l.valid ? ' ⚠' : '' }}
              </option>
            </optgroup>
            <optgroup label="Beste pro Fahrer" v-if="driverBests.length">
              <option v-for="db in driverBests" :key="db.filename" :value="'driver:' + db.filename">
                {{ db.driver }} — {{ fmtTimeSec(db.best_time) }} ({{ db.car }})
              </option>
            </optgroup>
          </select>
        </div>
      </div>

      <!-- Lap list (collapsible) -->
      <div class="panel panel-laps">
        <div class="panel-header" @click="panelOpen.laps = !panelOpen.laps">
          <span class="panel-chevron" :class="{ open: panelOpen.laps }">▸</span>
          <span class="panel-title">Laps</span>
          <span class="panel-badge">{{ store.laps.filter(l => l.valid !== false).length }} / {{ store.laps.length }}</span>
        </div>
        <div class="panel-body panel-body-scroll" v-show="panelOpen.laps">
          <div class="lap-list-header">
            <span>#</span><span>Time</span><span>Gap</span>
          </div>
          <div
            v-for="lap in store.laps" :key="lap.lap_number"
            class="lap-row"
            :class="{
              'lap-fastest': isFastest(lap),
              'lap-active': isActive(lap),
              'lap-invalid': lap.valid === false,
            }"
            @click="selectLap(lap)"
          >
            <span class="lap-num">{{ lap.lap_number }}</span>
            <span class="lap-time mono">{{ formatTime(lap.lap_time_ms) }}</span>
            <span class="lap-gap mono" :class="gapClass(lap.gap_to_best_ms)">{{ formatDelta(lap.gap_to_best_ms) }}</span>
          </div>
        </div>
      </div>

      <!-- Coaching message -->
      <div class="coaching-msg" v-if="clientCoaching?.main_message">
        <div class="coaching-icon">💡</div>
        <div class="coaching-text">{{ clientCoaching.main_message }}</div>
      </div>
    </aside>

    <!-- ===== MAIN AREA ===== -->
    <div class="main-area">
      <!-- Track map -->
      <div class="map-panel">
        <TrackMap :distance-range="distanceRange" @corner-click="onCornerClick" />
      </div>

      <!-- Charts panel -->
      <div class="charts-panel">
        <!-- Corner info bar -->
        <div class="corner-info" v-if="store.activeCorner">
          <span class="corner-badge">{{ store.activeCorner.id }}</span>
          <span class="corner-name">{{ store.activeCorner.name }}</span>
          <span class="corner-speed mono">{{ store.activeCorner.min_speed?.toFixed(0) }} km/h</span>
          <button class="btn-corner-detail" @click="onCornerClick(store.activeCorner)">Details →</button>
          <button class="close-corner" @click="closeCorner">✕</button>
        </div>

        <!-- Speed chart -->
        <div class="chart-row">
          <div class="chart-label">SPEED</div>
          <div class="chart-container">
            <TelemetryChart :channels="['speed']" :distance-range="distanceRange" />
          </div>
        </div>

        <!-- Throttle + Brake overlay -->
        <div class="chart-row">
          <div class="chart-label">THROTTLE / BRAKE</div>
          <div class="chart-container">
            <TelemetryChart :channels="['throttle', 'brake']" :distance-range="distanceRange" />
          </div>
        </div>

        <!-- Delta strip -->
        <div class="delta-row">
          <DeltaStrip :distance-range="distanceRange" />
        </div>

        <!-- Coaching tip when corner selected -->
        <CoachingTip v-if="store.activeCorner" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: grid;
  grid-template-columns: 360px 1fr;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

/* ===== SIDEBAR ===== */
.sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg-secondary);
}

.session-block {
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--border);
}
.session-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.session-time {
  font-size: 36px;
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--text-primary);
  line-height: 1.1;
  letter-spacing: -0.5px;
}
.session-deltas {
  font-size: 16px;
  font-family: var(--font-mono);
  font-weight: 600;
  margin-top: 4px;
}
.gap-red { color: #ef4444; }
.gap-green { color: #22c55e; }
.session-car {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
.lm-badge-sm {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  background: #e63946;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 900;
  color: #fff;
  flex-shrink: 0;
}
.car-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}
.track-name {
  font-size: 12px;
  color: var(--text-muted);
}
.session-date {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}

/* ===== COLLAPSIBLE PANELS ===== */
.panel {
  border-bottom: 1px solid var(--border);
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  cursor: pointer;
  user-select: none;
  transition: background 0.1s;
}
.panel-header:hover {
  background: var(--bg-tertiary);
}
.panel-chevron {
  font-size: 11px;
  color: var(--text-muted);
  transition: transform 0.15s ease;
  display: inline-block;
}
.panel-chevron.open {
  transform: rotate(90deg);
}
.panel-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  flex: 1;
}
.panel-badge {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  padding: 2px 8px;
  border-radius: 10px;
}
.panel-body {
  padding: 0 20px 12px;
}
.panel-body-scroll {
  max-height: 280px;
  overflow-y: auto;
  padding: 0 0 8px;
}

/* Stats & segments table */
.stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.stat-label {
  color: var(--text-secondary);
  padding: 5px 0;
  font-weight: 500;
}
.stat-value {
  text-align: right;
  color: var(--text-primary);
  font-weight: 600;
  padding: 5px 0;
}
.stat-diff {
  text-align: right;
  padding: 5px 0 5px 10px;
  width: 80px;
}

/* Reference selector */
.ref-select {
  width: 100%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 8px 10px;
  font-size: 13px;
  font-family: var(--font-mono);
  border-radius: 6px;
  cursor: pointer;
  outline: none;
}
.ref-select:focus { border-color: #c8ff00; }
.ref-select optgroup { color: var(--text-muted); font-size: 11px; }

/* Lap list */
.panel-laps {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.lap-list-header {
  display: grid;
  grid-template-columns: 40px 1fr auto;
  gap: 4px;
  padding: 6px 20px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
}
.lap-list-header span:nth-child(2) { text-align: right; }
.lap-list-header span:nth-child(3) { text-align: right; }
.lap-row {
  display: grid;
  grid-template-columns: 40px 1fr auto;
  gap: 4px;
  padding: 6px 20px;
  cursor: pointer;
  transition: background 0.1s;
  border-left: 3px solid transparent;
  font-size: 13px;
}
.lap-row:hover { background: var(--bg-tertiary); }
.lap-fastest .lap-time { color: var(--accent-blue); }
.lap-active {
  background: rgba(249, 115, 22, 0.06);
  border-left-color: var(--accent-orange);
}
.lap-active .lap-num { color: var(--accent-orange); font-weight: 700; }
.lap-invalid {
  opacity: 0.4;
}
.lap-invalid .lap-time {
  text-decoration: line-through;
}
.lap-num { color: var(--text-secondary); font-weight: 600; }
.lap-time { text-align: right; color: var(--text-primary); }
.lap-gap { text-align: right; }

/* Coaching */
.coaching-msg {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  flex-shrink: 0;
  background: rgba(200, 255, 0, 0.03);
}
.coaching-icon { font-size: 14px; flex-shrink: 0; }
.coaching-text { flex: 1; }

/* ===== MAIN AREA ===== */
.main-area {
  display: grid;
  grid-template-rows: minmax(200px, 2fr) minmax(300px, 3fr);
  overflow: hidden;
}

.map-panel {
  position: relative;
  overflow: hidden;
}

/* Charts panel */
.charts-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-top: 1px solid var(--border);
}

.corner-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.corner-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  background: var(--accent-orange);
  border-radius: 50%;
  font-size: 12px; font-weight: 800; color: #000;
}
.corner-name {
  font-size: 14px; font-weight: 700; color: var(--text-primary);
}
.corner-speed {
  font-size: 12px; color: var(--text-muted);
}
.btn-corner-detail {
  margin-left: auto;
  background: var(--accent-orange);
  border: none;
  color: #000;
  font-size: 12px; font-weight: 700;
  padding: 5px 14px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-corner-detail:hover { filter: brightness(1.15); }
.close-corner {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px; font-weight: 600;
  padding: 5px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.close-corner:hover {
  color: var(--text-primary);
  border-color: var(--text-muted);
}

.chart-row {
  flex: 1;
  min-height: 80px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
.chart-label {
  position: absolute;
  top: 4px; left: 44px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  z-index: 1;
  pointer-events: none;
  opacity: 0.7;
}
.chart-container {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.delta-row {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}

.mono {
  font-family: var(--font-mono);
}
</style>
