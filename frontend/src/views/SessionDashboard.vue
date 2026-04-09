<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import DeltaStrip from '../components/DeltaStrip.vue'
import CoachingTip from '../components/CoachingTip.vue'
import axios from 'axios'

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

// Human-readable reference label
const refLabel = computed(() => {
  if (!store.refLap) return null
  const v = refValue.value
  if (v === 'composite') return { type: 'Composite', lap: 'Best Composite', time: formatTime(store.refLap.lap_time_ms), cross: false }
  if (v.startsWith('popup:')) {
    const parts = v.split(':')
    const session = refPopupSession.value
    return { type: 'Cross-Session', lap: `Lap ${store.refLap.lap_number}`, time: formatTime(store.refLap.lap_time_ms), cross: true, driver: session?.driver, car: session?.car }
  }
  return { type: 'Same Session', lap: `Lap ${store.refLap.lap_number}`, time: formatTime(store.refLap.lap_time_ms), cross: false }
})

// ── Reference popup state ──
const showRefPopup = ref(false)
const refPopupDriver = ref('')
const refPopupSort = ref('time-asc')
const refPopupSession = ref(null)   // selected session in popup
const refPopupLaps = ref([])        // laps for selected session
const refPopupLoading = ref(false)

const TYPE_COLORS = { Practice: '#3b82f6', Qualifying: '#f97316', Race: '#22c55e' }

// Sessions for the popup: same track, optionally filtered by driver
const refPopupSessions = computed(() => {
  const track = store.currentSession?.track
  if (!track) return []
  let list = store.sessions.filter(s => s.track === track)
  if (refPopupDriver.value) list = list.filter(s => s.driver === refPopupDriver.value)
  switch (refPopupSort.value) {
    case 'time-asc':  list.sort((a, b) => (a.best_time || Infinity) - (b.best_time || Infinity)); break
    case 'date-desc': list.sort((a, b) => parseDate(b.date) - parseDate(a.date)); break
    case 'date-asc':  list.sort((a, b) => parseDate(a.date) - parseDate(b.date)); break
  }
  return list
})

// Driver options for popup (same track)
const refPopupDriverOptions = computed(() => {
  const track = store.currentSession?.track
  if (!track) return []
  const set = new Set()
  store.sessions.filter(s => s.track === track).forEach(s => { if (s.driver) set.add(s.driver) })
  return [...set].sort()
})

/** Parse DD.MM.YYYY HH:MM → timestamp for sorting */
function parseDate(dateStr) {
  if (!dateStr) return 0
  const m = dateStr.match(/(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/)
  if (!m) return 0
  return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]).getTime()
}

function openRefPopup() {
  // Make sure sessions are loaded
  if (!store.sessions.length) store.fetchSessions()
  refPopupDriver.value = ''
  refPopupSession.value = null
  refPopupLaps.value = []
  showRefPopup.value = true
}

async function refPopupSelectSession(s) {
  refPopupSession.value = s
  refPopupLaps.value = []
  refPopupLoading.value = true
  try {
    const { data: sess } = await axios.post('/api/load', null, {
      params: { filename: s.filename, driver: s.driver || '' }
    })
    refPopupSession.value = { ...s, session_id: sess.session_id }
    const { data: lapData } = await axios.get(`/api/laps/${sess.session_id}`)
    refPopupLaps.value = lapData.laps.filter(l => l.valid !== false && l.lap_time_ms > 0)
  } catch (e) {
    console.error('refPopup session error', e)
  } finally {
    refPopupLoading.value = false
  }
}

async function refPopupSelectLap(lap) {
  if (!refPopupSession.value?.session_id) return
  showRefPopup.value = false
  try {
    await store.loadCrossSessionRef(refPopupSession.value.session_id, lap.lap_number)
    if (store.refLap) store.refLap._crossSession = true
    refValue.value = `popup:${refPopupSession.value.filename}:${lap.lap_number}`
  } catch (e) {
    console.error('refPopup lap error', e)
  }
}

// Watch refValue for changes (more reliable than @change on <select>)
watch(refValue, async (val, oldVal) => {
  if (!val || val === oldVal || val.startsWith('popup:')) return
  try {
    if (val === 'composite') {
      // Skip if already loaded
      if (store.refLap?.lap_number === 0 && store.refTelemetry) return
      await store.selectRefLap(0)
    } else if (val.startsWith('lap:')) {
      const n = Number(val.substring(4))
      if (store.refLap?.lap_number === n && store.refTelemetry && !store.refLap._crossSession) return
      await store.selectRefLap(n)
    } else if (val.startsWith('driver:')) {
      const filename = val.substring(7)
      const db = driverBests.value.find(d => d.filename === filename)
      if (db) await store.loadDriverBestRef(filename, db.driver)
    }
  } catch (err) {
    console.error('ref change error', err)
  }
})

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
watch(() => [store.currentSession?.track, store.currentSession?.layout], ([track, layout]) => {
  if (track) store.fetchDriverBests(track, layout || '')
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
          <span class="delta-label">vs Ref</span>
        </div>
        <div class="session-car" v-if="store.currentSession">
          <span class="lm-badge-sm">LM</span>
          <div>
            <div class="car-name">{{ store.currentSession.car }}</div>
            <div class="track-name">{{ store.currentSession.track }}</div>
            <div class="layout-name" v-if="store.currentSession.layout">{{ store.currentSession.layout }}</div>
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
                <td class="stat-diff mono" :class="gapClass(store.activeLap?.gap_to_best_ms)">{{ formatDelta(store.activeLap?.gap_to_best_ms) }}</td>
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
          <select class="ref-select" v-model="refValue">
            <option value="" disabled>Referenz wählen…</option>
            <optgroup label="Diese Session">
              <option v-if="store.compositeAvailable" value="composite">
                Best Composite — {{ formatTime(store.theoreticalBestMs) }}
              </option>
              <option v-for="l in refOptions" :key="l.lap_number" :value="'lap:' + l.lap_number">
                Lap {{ l.lap_number }} — {{ formatTime(l.lap_time_ms) }}{{ !l.valid ? ' ⚠' : '' }}
              </option>
            </optgroup>
          </select>
          <button class="btn-ref-popup" @click="openRefPopup">
            Andere Session wählen…
          </button>

          <!-- Active reference indicator -->
          <div class="ref-indicator" v-if="store.refLap">
            <div class="ref-indicator-dot"></div>
            <div class="ref-indicator-info">
              <span class="ref-indicator-lap mono">{{ refLabel?.lap }} — {{ refLabel?.time }}</span>
              <span class="ref-indicator-meta" v-if="refLabel?.cross">{{ refLabel.driver || '' }} {{ refLabel.car ? '· ' + refLabel.car : '' }}</span>
              <span class="ref-indicator-meta" v-else>{{ refLabel?.type }}</span>
            </div>
          </div>
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
        <TrackMap :distance-range="distanceRange" :show-ref="true" @corner-click="onCornerClick" />
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

    <!-- ===== REFERENCE POPUP ===== -->
    <Teleport to="body">
      <div class="ref-popup-overlay" v-if="showRefPopup" @click.self="showRefPopup = false">
        <div class="ref-popup">
          <div class="ref-popup-header">
            <h3>Referenz wählen</h3>
            <span class="ref-popup-track" v-if="store.currentSession?.track">{{ store.currentSession.track }}</span>
            <button class="ref-popup-close" @click="showRefPopup = false">✕</button>
          </div>

          <div class="ref-popup-filters">
            <div class="ref-popup-filter">
              <label>Fahrer</label>
              <select v-model="refPopupDriver" class="filter-select">
                <option value="">Alle Fahrer</option>
                <option v-for="d in refPopupDriverOptions" :key="d" :value="d">{{ d }}</option>
              </select>
            </div>
            <div class="ref-popup-filter">
              <label>Sortierung</label>
              <select v-model="refPopupSort" class="filter-select">
                <option value="time-asc">Bestzeit ↑</option>
                <option value="date-desc">Datum ↓</option>
                <option value="date-asc">Datum ↑</option>
              </select>
            </div>
          </div>

          <div class="ref-popup-body">
            <!-- Session list (left) -->
            <div class="ref-popup-sessions">
              <div
                v-for="s in refPopupSessions" :key="s.filename"
                class="ref-popup-card"
                :class="{ active: refPopupSession?.filename === s.filename }"
                @click="refPopupSelectSession(s)"
              >
                <div class="lm-badge-sm">LM</div>
                <div class="ref-popup-card-info">
                  <div class="ref-popup-card-track">{{ s.track || s.filename }}</div>
                  <div class="ref-popup-card-car">{{ s.car || '—' }} <span class="ref-popup-card-driver" v-if="s.driver">· {{ s.driver }}</span></div>
                  <div class="ref-popup-card-meta">
                    <span class="mono">{{ fmtTimeSec(s.best_time) }}</span>
                    <span>{{ s.lap_count }} laps</span>
                    <span class="ref-popup-card-type" v-if="s.session_type" :style="{ color: TYPE_COLORS[s.session_type] || '#888' }">{{ s.session_type }}</span>
                  </div>
                </div>
                <div class="ref-popup-card-date mono">{{ s.date }}</div>
              </div>
              <div class="ref-popup-empty" v-if="refPopupSessions.length === 0">Keine Sessions gefunden</div>
            </div>

            <!-- Lap list (right) -->
            <div class="ref-popup-laps">
              <div class="ref-popup-laps-header" v-if="refPopupSession">
                <span class="ref-popup-laps-title">{{ refPopupSession.car || '—' }}</span>
                <span class="ref-popup-laps-driver" v-if="refPopupSession.driver">{{ refPopupSession.driver }}</span>
              </div>
              <div class="ref-popup-laps-hint" v-if="!refPopupSession">← Session wählen</div>
              <div class="ref-popup-laps-loading" v-if="refPopupLoading">Laden…</div>
              <div class="ref-popup-lap-list" v-if="refPopupLaps.length">
                <div
                  v-for="l in refPopupLaps" :key="l.lap_number"
                  class="ref-popup-lap-row"
                  @click="refPopupSelectLap(l)"
                >
                  <span class="lap-num">{{ l.lap_number }}</span>
                  <span class="lap-time mono">{{ formatTime(l.lap_time_ms) }}</span>
                </div>
              </div>
              <div class="ref-popup-laps-empty" v-if="refPopupSession && !refPopupLoading && refPopupLaps.length === 0">Keine gültigen Runden</div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
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
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.delta-label {
  font-size: 11px;
  font-weight: 400;
  color: #888;
  font-family: var(--font-sans, sans-serif);
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
.layout-name {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
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

/* Button to open ref popup */
.btn-ref-popup {
  width: 100%;
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border: 1px dashed var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-ref-popup:hover {
  border-color: #c8ff00;
  color: var(--text-primary);
  background: rgba(200, 255, 0, 0.04);
}

/* Reference indicator card */
.ref-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(249, 115, 22, 0.06);
  border: 1px solid rgba(249, 115, 22, 0.2);
  border-radius: 6px;
}
.ref-indicator-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #f97316;
  flex-shrink: 0;
}
.ref-indicator-info {
  display: flex; flex-direction: column; gap: 1px;
}
.ref-indicator-lap {
  font-size: 12px; font-weight: 600;
  color: var(--text-primary);
}
.ref-indicator-meta {
  font-size: 10px;
  color: var(--text-muted);
}

/* ===== Reference Popup ===== */
.ref-popup-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.65);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.ref-popup {
  width: 820px; max-width: 95vw;
  max-height: 80vh;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  display: flex; flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.ref-popup-header {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.ref-popup-header h3 {
  font-size: 16px; font-weight: 700; margin: 0;
  color: var(--text-primary);
}
.ref-popup-track {
  font-size: 12px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
  flex: 1;
}
.ref-popup-close {
  background: none; border: none;
  color: var(--text-muted); font-size: 18px;
  cursor: pointer; padding: 4px 8px;
}
.ref-popup-close:hover { color: var(--text-primary); }

.ref-popup-filters {
  display: flex; gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
}
.ref-popup-filter {
  display: flex; align-items: center; gap: 8px;
}
.ref-popup-filter label {
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-muted); white-space: nowrap;
}
.ref-popup-filter .filter-select {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 5px 8px; font-size: 12px;
  border-radius: 5px; cursor: pointer; outline: none;
}

.ref-popup-body {
  display: grid;
  grid-template-columns: 1fr 220px;
  flex: 1; min-height: 0;
  overflow: hidden;
}

/* Session list in popup */
.ref-popup-sessions {
  overflow-y: auto;
  border-right: 1px solid var(--border);
}
.ref-popup-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background 0.12s;
}
.ref-popup-card:hover { background: var(--bg-tertiary); }
.ref-popup-card.active {
  background: rgba(59, 130, 246, 0.08);
  border-left: 3px solid var(--accent-blue);
}
.ref-popup-card-info { flex: 1; min-width: 0; }
.ref-popup-card-track {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--text-primary);
}
.ref-popup-card-car {
  font-size: 11px; color: var(--text-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ref-popup-card-driver { color: var(--text-muted); }
.ref-popup-card-meta {
  display: flex; gap: 8px; align-items: center;
  margin-top: 2px; font-size: 11px;
  color: var(--text-muted);
}
.ref-popup-card-meta .mono { color: var(--text-primary); font-weight: 600; }
.ref-popup-card-type { font-weight: 600; font-size: 10px; text-transform: uppercase; }
.ref-popup-card-date { font-size: 10px; color: var(--text-muted); white-space: nowrap; flex-shrink: 0; }
.ref-popup-empty {
  padding: 30px; text-align: center;
  font-size: 12px; color: var(--text-muted);
}

/* Lap list in popup */
.ref-popup-laps {
  display: flex; flex-direction: column;
  overflow-y: auto;
}
.ref-popup-laps-header {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12px; font-weight: 600;
  color: var(--text-primary);
}
.ref-popup-laps-driver {
  display: block; font-size: 11px;
  color: var(--text-muted); font-weight: 400;
}
.ref-popup-laps-hint,
.ref-popup-laps-loading,
.ref-popup-laps-empty {
  padding: 30px 14px;
  text-align: center; font-size: 12px;
  color: var(--text-muted);
}
.ref-popup-lap-list {
  flex: 1; overflow-y: auto;
}
.ref-popup-lap-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}
.ref-popup-lap-row:hover {
  background: rgba(59, 130, 246, 0.08);
}
.ref-popup-lap-row .lap-num {
  color: var(--text-secondary); font-weight: 600; width: 28px; font-size: 12px;
}
.ref-popup-lap-row .lap-time {
  color: var(--text-primary); font-size: 13px; margin-left: auto;
}

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
