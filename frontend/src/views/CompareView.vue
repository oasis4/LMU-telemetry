<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import DeltaStrip from '../components/DeltaStrip.vue'
import CoachingTip from '../components/CoachingTip.vue'
import axios from 'axios'

const store = useTelemetryStore()

// ── Side state: A (left/orange), B (right/blue) ──
const sideA = ref({ sessions: [], session: null, laps: [], lap: null, telemetry: null, loading: false })
const sideB = ref({ sessions: [], session: null, laps: [], lap: null, telemetry: null, loading: false })

// Session picker open state
const pickingA = ref(true)
const pickingB = ref(true)

// Filter state
const filterTrack = ref('')
const filterCar = ref('')
const filterDriver = ref('')
const filterDriverB = ref('')
const sortBy = ref('date-desc')

// Corner zoom
const distanceRange = computed(() => {
  if (store.activeCorner) {
    return {
      min: store.activeCorner.distance_start - 50,
      max: store.activeCorner.distance_end + 50,
    }
  }
  return null
})

// ── Formatters ──
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

// ── Session type badge color ──
const TYPE_COLORS = { Practice: '#3b82f6', Qualifying: '#f97316', Race: '#22c55e' }

function parseSessionMeta(filename) {
  if (!filename) return { type: '', date: '', typeShort: '' }
  const m = filename.match(/_([PQR])_(\d{4})-(\d{2})-(\d{2})T(\d{2})_(\d{2})/)
  if (!m) return { type: '', date: '', typeShort: '' }
  const types = { P: 'Practice', Q: 'Qualifying', R: 'Race' }
  return { type: types[m[1]] || m[1], typeShort: m[1], date: `${m[3]}.${m[4]}.${m[2]} ${m[5]}:${m[6]}` }
}

// ── Filter options ──
const trackOptions = computed(() => {
  const set = new Set()
  store.sessions.forEach(s => { if (s.track) set.add(s.track) })
  return [...set].sort()
})
const carOptions = computed(() => {
  const set = new Set()
  let list = store.sessions
  if (filterTrack.value) list = list.filter(s => s.track === filterTrack.value)
  list.forEach(s => { if (s.car) set.add(s.car) })
  return [...set].sort()
})

const driverOptions = computed(() => {
  const set = new Set()
  let list = store.sessions
  if (filterTrack.value) list = list.filter(s => s.track === filterTrack.value)
  if (filterCar.value) list = list.filter(s => s.car === filterCar.value)
  list.forEach(s => { if (s.driver) set.add(s.driver) })
  return [...set].sort()
})

// Driver options for side B (scoped to locked track)
const driverOptionsB = computed(() => {
  const set = new Set()
  let list = [...store.sessions]
  const trackLock = sideA.value.session?.track
  if (trackLock) {
    list = list.filter(s => s.track === trackLock)
  } else if (filterTrack.value) {
    list = list.filter(s => s.track === filterTrack.value)
  }
  if (filterCar.value) list = list.filter(s => s.car === filterCar.value)
  list.forEach(s => { if (s.driver) set.add(s.driver) })
  return [...set].sort()
})

/** Parse DD.MM.YYYY HH:MM → timestamp for sorting */
function parseDate(dateStr) {
  if (!dateStr) return 0
  const m = dateStr.match(/(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/)
  if (!m) return 0
  return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]).getTime()
}

// ── Sort helper ──
function applySorting(list) {
  switch (sortBy.value) {
    case 'date-desc': list.sort((a, b) => parseDate(b.date) - parseDate(a.date)); break
    case 'date-asc':  list.sort((a, b) => parseDate(a.date) - parseDate(b.date)); break
    case 'time-asc':  list.sort((a, b) => (a.best_time || Infinity) - (b.best_time || Infinity)); break
    case 'time-desc': list.sort((a, b) => (b.best_time || 0) - (a.best_time || 0)); break
  }
  return list
}

// ── Filtered sessions for side A (uses all filters) ──
const filteredSessions = computed(() => {
  let list = [...store.sessions]
  if (filterTrack.value) list = list.filter(s => s.track === filterTrack.value)
  if (filterCar.value) list = list.filter(s => s.car === filterCar.value)
  if (filterDriver.value) list = list.filter(s => s.driver === filterDriver.value)
  return applySorting(list)
})

// ── Filtered sessions for side B: same track as A, own driver filter ──
const filteredSessionsB = computed(() => {
  let list = [...store.sessions]
  // Lock to side A's track when A is selected (cross-track comparison is not useful)
  const trackLock = sideA.value.session?.track
  if (trackLock) {
    list = list.filter(s => s.track === trackLock)
  } else if (filterTrack.value) {
    list = list.filter(s => s.track === filterTrack.value)
  }
  // Car filter still applies
  if (filterCar.value) list = list.filter(s => s.car === filterCar.value)
  // Driver filter B — separate from side A
  if (filterDriverB.value) list = list.filter(s => s.driver === filterDriverB.value)
  return applySorting(list)
})

// ── Delta between A and B ──
const totalDelta = computed(() => {
  if (!sideA.value.lap?.lap_time_ms || !sideB.value.lap?.lap_time_ms) return null
  return sideA.value.lap.lap_time_ms - sideB.value.lap.lap_time_ms
})

// ── Segments comparison ──
const segments = computed(() => {
  const la = sideA.value.lap
  const lb = sideB.value.lap
  if (!la?.sectors) return []
  const names = ['Seg 1', 'Seg 2', 'Seg 3']
  const keys = ['s1', 's2', 's3']
  return keys.map((k, i) => {
    const time = la.sectors?.[k] || 0
    const refTime = lb?.sectors?.[k] || 0
    const diff = time && refTime ? time - refTime : null
    return { name: names[i], timeA: time, timeB: refTime, diff }
  }).filter(s => s.timeA > 0 || s.timeB > 0)
})

// ── Load session & laps for a side ──
function selectSessionA(s) {
  pickingA.value = false
  loadSideSession(sideA.value, s)
}
function selectSessionB(s) {
  pickingB.value = false
  loadSideSession(sideB.value, s)
}

async function loadSideSession(side, session) {
  side.loading = true
  side.session = session
  side.laps = []
  side.lap = null
  side.telemetry = null
  try {
    // Load session on backend
    const { data: sess } = await axios.post('/api/load', null, {
      params: { filename: session.filename, driver: session.driver || '' }
    })
    side.session = { ...session, session_id: sess.session_id }
    // Fetch laps
    const { data: lapData } = await axios.get(`/api/laps/${sess.session_id}`)
    side.laps = lapData.laps
    // Auto-select fastest valid lap
    const valid = lapData.laps.filter(l => l.valid !== false && l.lap_time_ms > 0)
    const pool = valid.length > 0 ? valid : lapData.laps
    if (pool.length > 0) {
      const fastest = pool.reduce((b, l) => l.lap_time_ms < b.lap_time_ms ? l : b)
      await loadSideLap(side, fastest)
    }
  } catch (e) {
    console.error('loadSideSession error', e)
    store.error = e.message
  } finally {
    side.loading = false
  }
}

async function loadSideLap(side, lap) {
  if (!side.session?.session_id) return
  side.lap = lap
  try {
    const { data } = await axios.get(`/api/telemetry/${side.session.session_id}/${lap.lap_number}`)
    side.telemetry = data
  } catch (e) {
    console.error('loadSideLap error', e)
  }
  syncToStore()
}

// ── Sync to global store so chart/map/delta components work ──
function syncToStore() {
  const a = sideA.value
  const b = sideB.value
  // A = active (orange), B = reference (blue)
  store.activeTelemetry = a.telemetry
  store.refTelemetry = b.telemetry
  store.activeLap = a.lap
  store.refLap = b.lap
  // Compute delta client-side
  if (a.telemetry?.time?.length && b.telemetry?.time?.length) {
    store.delta = computeClientDelta(a.telemetry, b.telemetry)
  } else if (a.telemetry?.speed?.length && b.telemetry?.speed?.length) {
    store.delta = computeDeltaFromSpeed(a.telemetry, b.telemetry)
  } else {
    store.delta = null
  }
  // Detect corners from reference (B) if available, else from A
  const cornerSide = b.telemetry ? b : a
  if (cornerSide.session?.session_id && cornerSide.lap) {
    fetchCorners(cornerSide.session.session_id, cornerSide.lap.lap_number)
  }
}

// ── Client-side delta (replicated from store for direct use) ──
function lerpArr(dArr, vArr, d) {
  if (d <= dArr[0]) return vArr[0]
  if (d >= dArr[dArr.length - 1]) return vArr[vArr.length - 1]
  let lo = 0, hi = dArr.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (dArr[mid] <= d) lo = mid; else hi = mid
  }
  const t = (d - dArr[lo]) / (dArr[hi] - dArr[lo] || 1)
  return vArr[lo] + t * (vArr[hi] - vArr[lo])
}

function computeClientDelta(active, ref) {
  const dA = active.distance, tA = active.time
  const dR = ref.distance, tR = ref.time
  const maxDist = Math.min(dA[dA.length - 1], dR[dR.length - 1])
  const dist = [], dt = []
  for (let d = 0; d < maxDist; d += 1.0) {
    dist.push(d)
    dt.push(lerpArr(dA, tA, d) - lerpArr(dR, tR, d))
  }
  return { distance: dist, delta: dt }
}

function computeDeltaFromSpeed(active, ref) {
  const dA = active.distance, sA = active.speed
  const dR = ref.distance, sR = ref.speed
  const maxDist = Math.min(dA[dA.length - 1], dR[dR.length - 1])
  const dist = [], dt = []
  let cum = 0
  for (let d = 0; d < maxDist; d += 1.0) {
    const va = lerpArr(dA, sA, d) / 3.6
    const vr = lerpArr(dR, sR, d) / 3.6
    cum += (va > 0.1 ? 1.0 / va : 0) - (vr > 0.1 ? 1.0 / vr : 0)
    dist.push(d)
    dt.push(cum)
  }
  return { distance: dist, delta: dt }
}

async function fetchCorners(sessionId, lapNumber) {
  try {
    const { data } = await axios.get(`/api/corners/${sessionId}`, {
      params: { lap_number: lapNumber }
    })
    store.corners = data.corners
  } catch (e) {
    console.error('fetchCorners error', e)
  }
}

function closeCorner() {
  store.setActiveCorner(null)
}

function onCornerClick(c) {
  store.setActiveCorner(store.activeCorner?.id === c.id ? null : c)
}

// ── Coaching (client-side, same as SessionDashboard) ──
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
  const active = sideA.value.telemetry
  const reference = sideB.value.telemetry
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

// ── Panel collapse state ──
const panelOpen = ref({ segA: true, segB: true, segments: true, lapsA: true, lapsB: true })

// ── Init ──
onMounted(() => {
  if (!store.sessions.length) store.fetchSessions()
  // Clear store state for fresh compare
  store.activeTelemetry = null
  store.refTelemetry = null
  store.activeLap = null
  store.refLap = null
  store.delta = null
  store.corners = []
  store.activeCorner = null
  store.coaching = null
})
</script>

<template>
  <div class="compare-view">
    <!-- ===== LEFT SIDEBAR ===== -->
    <aside class="sidebar">
      <!-- Filters -->
      <div class="filter-block">
        <div class="filter-row">
          <label class="filter-label">Track</label>
          <select v-model="filterTrack" class="filter-select">
            <option value="">Alle Strecken</option>
            <option v-for="t in trackOptions" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="filter-row">
          <label class="filter-label">Car</label>
          <select v-model="filterCar" class="filter-select">
            <option value="">Alle Autos</option>
            <option v-for="c in carOptions" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="filter-row">
          <label class="filter-label">Driver</label>
          <select v-model="filterDriver" class="filter-select">
            <option value="">Alle Fahrer</option>
            <option v-for="d in driverOptions" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div class="filter-row">
          <label class="filter-label">Sort</label>
          <select v-model="sortBy" class="filter-select">
            <option value="date-desc">Datum ↓ (neueste)</option>
            <option value="date-asc">Datum ↑ (älteste)</option>
            <option value="time-asc">Bestzeit ↑ (schnellste)</option>
            <option value="time-desc">Bestzeit ↓ (langsamste)</option>
          </select>
        </div>
      </div>

      <!-- ── SIDE A (Active / Orange) ── -->
      <div class="side-block side-a">
        <div class="side-header" @click="pickingA = !pickingA">
          <span class="side-dot dot-orange"></span>
          <span class="side-title">LAP A</span>
          <span class="side-time mono" v-if="sideA.lap">{{ formatTime(sideA.lap.lap_time_ms) }}</span>
          <span class="side-chevron" :class="{ open: pickingA }">▸</span>
        </div>

        <!-- Selected session compact card (when not picking) -->
        <div class="selected-card" v-if="sideA.session && !pickingA" @click="pickingA = true">
          <div class="lm-badge-sm">LM</div>
          <div class="sel-info">
            <div class="sel-track">{{ sideA.session.track || sideA.session.filename }}</div>
            <div class="sel-car">{{ sideA.session.car || '—' }} <span class="sel-driver" v-if="sideA.session.driver">· {{ sideA.session.driver }}</span></div>
            <div class="sel-meta">
              <span class="sel-time mono">{{ fmtTimeSec(sideA.session.best_time) }}</span>
              <span class="sel-type" v-if="sideA.session.session_type" :style="{ color: TYPE_COLORS[sideA.session.session_type] || '#888' }">{{ sideA.session.session_type }}</span>
              <span class="sel-date">{{ sideA.session.date }}</span>
            </div>
          </div>
          <button class="btn-change" @click.stop="pickingA = true">✎</button>
        </div>

        <!-- Session card list (picker) -->
        <div class="session-picker" v-if="pickingA">
          <div class="picker-scroll">
            <div
              v-for="s in filteredSessions" :key="s.filename"
              class="pick-card"
              :class="{ active: sideA.session?.filename === s.filename }"
              @click="selectSessionA(s)"
            >
              <div class="lm-badge-sm">LM</div>
              <div class="pick-info">
                <div class="pick-track">{{ s.track || s.filename }}</div>
                <div class="pick-layout" v-if="s.layout && s.layout !== s.track">{{ s.layout }}</div>
                <div class="pick-car">{{ s.car || '—' }} <span class="pick-driver" v-if="s.driver">· {{ s.driver }}</span></div>
                <div class="pick-bottom">
                  <span class="pick-time mono">{{ fmtTimeSec(s.best_time) }}</span>
                  <span class="pick-laps mono">{{ s.lap_count }} laps</span>
                  <span class="pick-type" v-if="s.session_type" :style="{ color: TYPE_COLORS[s.session_type] || '#888' }">{{ s.session_type }}</span>
                </div>
              </div>
              <div class="pick-date mono">{{ s.date }}</div>
            </div>
            <div class="pick-empty" v-if="filteredSessions.length === 0">Keine Sessions gefunden</div>
          </div>
        </div>

        <!-- Lap list A -->
        <div class="side-body" v-if="sideA.laps.length && !pickingA">
          <div class="lap-list-mini">
            <div
              v-for="l in sideA.laps.filter(l => l.valid !== false)"
              :key="l.lap_number"
              class="lap-row-mini"
              :class="{ active: sideA.lap?.lap_number === l.lap_number }"
              @click="loadSideLap(sideA, l)"
            >
              <span class="lap-num">{{ l.lap_number }}</span>
              <span class="lap-time mono">{{ formatTime(l.lap_time_ms) }}</span>
            </div>
          </div>
        </div>
        <div class="side-loading" v-if="sideA.loading">Laden…</div>
      </div>

      <!-- ── Delta display ── -->
      <div class="delta-block" v-if="totalDelta != null">
        <div class="delta-label">DELTA</div>
        <div class="delta-value mono" :class="gapClass(totalDelta)">{{ formatDelta(totalDelta) }}</div>
      </div>

      <!-- ── SIDE B (Reference / Blue) ── -->
      <div class="side-block side-b">
        <div class="side-header" @click="pickingB = !pickingB">
          <span class="side-dot dot-blue"></span>
          <span class="side-title">LAP B</span>
          <span class="side-time mono" v-if="sideB.lap">{{ formatTime(sideB.lap.lap_time_ms) }}</span>
          <span class="side-chevron" :class="{ open: pickingB }">▸</span>
        </div>

        <!-- Selected session compact card (when not picking) -->
        <div class="selected-card" v-if="sideB.session && !pickingB" @click="pickingB = true">
          <div class="lm-badge-sm">LM</div>
          <div class="sel-info">
            <div class="sel-track">{{ sideB.session.track || sideB.session.filename }}</div>
            <div class="sel-car">{{ sideB.session.car || '—' }} <span class="sel-driver" v-if="sideB.session.driver">· {{ sideB.session.driver }}</span></div>
            <div class="sel-meta">
              <span class="sel-time mono">{{ fmtTimeSec(sideB.session.best_time) }}</span>
              <span class="sel-type" v-if="sideB.session.session_type" :style="{ color: TYPE_COLORS[sideB.session.session_type] || '#888' }">{{ sideB.session.session_type }}</span>
              <span class="sel-date">{{ sideB.session.date }}</span>
            </div>
          </div>
          <button class="btn-change" @click.stop="pickingB = true">✎</button>
        </div>

        <!-- Session card list (picker) -->
        <div class="session-picker" v-if="pickingB">
          <div class="picker-b-filters">
            <div class="picker-b-track" v-if="sideA.session?.track">
              Strecke: <strong>{{ sideA.session.track }}</strong>
            </div>
            <div class="picker-b-driver">
              <label class="filter-label">Fahrer</label>
              <select v-model="filterDriverB" class="filter-select filter-select-sm">
                <option value="">Alle Fahrer</option>
                <option v-for="d in driverOptionsB" :key="d" :value="d">{{ d }}</option>
              </select>
            </div>
          </div>
          <div class="picker-scroll">
            <div
              v-for="s in filteredSessionsB" :key="s.filename"
              class="pick-card"
              :class="{ active: sideB.session?.filename === s.filename }"
              @click="selectSessionB(s)"
            >
              <div class="lm-badge-sm">LM</div>
              <div class="pick-info">
                <div class="pick-track">{{ s.track || s.filename }}</div>
                <div class="pick-layout" v-if="s.layout && s.layout !== s.track">{{ s.layout }}</div>
                <div class="pick-car">{{ s.car || '—' }} <span class="pick-driver" v-if="s.driver">· {{ s.driver }}</span></div>
                <div class="pick-bottom">
                  <span class="pick-time mono">{{ fmtTimeSec(s.best_time) }}</span>
                  <span class="pick-laps mono">{{ s.lap_count }} laps</span>
                  <span class="pick-type" v-if="s.session_type" :style="{ color: TYPE_COLORS[s.session_type] || '#888' }">{{ s.session_type }}</span>
                </div>
              </div>
              <div class="pick-date mono">{{ s.date }}</div>
            </div>
            <div class="pick-empty" v-if="filteredSessionsB.length === 0">Keine Sessions gefunden</div>
          </div>
        </div>

        <!-- Lap list B -->
        <div class="side-body" v-if="sideB.laps.length && !pickingB">
          <div class="lap-list-mini">
            <div
              v-for="l in sideB.laps.filter(l => l.valid !== false)"
              :key="l.lap_number"
              class="lap-row-mini"
              :class="{ active: sideB.lap?.lap_number === l.lap_number }"
              @click="loadSideLap(sideB, l)"
            >
              <span class="lap-num">{{ l.lap_number }}</span>
              <span class="lap-time mono">{{ formatTime(l.lap_time_ms) }}</span>
            </div>
          </div>
        </div>
        <div class="side-loading" v-if="sideB.loading">Laden…</div>
      </div>

      <!-- ── Segments comparison ── -->
      <div class="panel" v-if="segments.length">
        <div class="panel-header" @click="panelOpen.segments = !panelOpen.segments">
          <span class="panel-chevron" :class="{ open: panelOpen.segments }">▸</span>
          <span class="panel-title">Segments</span>
        </div>
        <div class="panel-body" v-show="panelOpen.segments">
          <table class="stats-table">
            <thead>
              <tr>
                <th class="stat-label"></th>
                <th class="stat-value mono" style="text-align:right; color: var(--accent-orange); font-size:10px">A</th>
                <th class="stat-value mono" style="text-align:right; color: var(--accent-blue); font-size:10px">B</th>
                <th class="stat-diff"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="seg in segments" :key="seg.name">
                <td class="stat-label">{{ seg.name }}</td>
                <td class="stat-value mono">{{ formatTime(seg.timeA) }}</td>
                <td class="stat-value mono">{{ formatTime(seg.timeB) }}</td>
                <td class="stat-diff mono" :class="gapClass(seg.diff)">{{ seg.diff != null ? formatDelta(seg.diff) : '' }}</td>
              </tr>
            </tbody>
          </table>
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
      <!-- Empty state -->
      <div class="empty-main" v-if="!sideA.telemetry && !sideB.telemetry">
        <div class="empty-icon">⇄</div>
        <div class="empty-text">Wähle links zwei Sessions und Runden zum Vergleichen</div>
      </div>

      <template v-else>
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
            <button class="close-corner" @click="closeCorner">✕</button>
          </div>

          <!-- Speed chart -->
          <div class="chart-row">
            <div class="chart-label">SPEED
              <span class="chart-legend"><span class="cl-line cl-solid" style="background:#3b82f6"></span>A <span class="cl-line cl-dashed" style="background:#f97316"></span>B</span>
            </div>
            <div class="chart-container">
              <TelemetryChart :channels="['speed']" :distance-range="distanceRange" />
            </div>
          </div>

          <!-- Throttle + Brake overlay -->
          <div class="chart-row">
            <div class="chart-label">THROTTLE / BRAKE
              <span class="chart-legend"><span class="cl-line cl-solid" style="background:#22c55e"></span>Thr A <span class="cl-line cl-dashed" style="background:#4ade80"></span>Thr B <span class="cl-line cl-solid" style="background:#ef4444"></span>Brk A <span class="cl-line cl-dashed" style="background:#f87171"></span>Brk B</span>
            </div>
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
      </template>
    </div>
  </div>
</template>

<style scoped>
.compare-view {
  display: grid;
  grid-template-columns: 420px 1fr;
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

/* Filter block */
.filter-block {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  width: 44px;
  flex-shrink: 0;
}
.filter-select {
  flex: 1;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 6px 8px;
  font-size: 12px;
  border-radius: 5px;
  cursor: pointer;
  outline: none;
}
.filter-select:focus { border-color: #c8ff00; }

/* Side blocks */
.side-block {
  border-bottom: 1px solid var(--border);
}
.side-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px 8px;
  cursor: pointer;
  user-select: none;
  transition: background 0.1s;
}
.side-header:hover { background: var(--bg-tertiary); }
.side-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-orange { background: var(--accent-orange); }
.dot-blue { background: var(--accent-blue); }
.side-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  flex: 1;
}
.side-time {
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}
.side-chevron {
  font-size: 11px;
  color: var(--text-muted);
  transition: transform 0.15s ease;
  display: inline-block;
}
.side-chevron.open { transform: rotate(90deg); }
.side-body {
  padding: 0 20px 12px;
}
.side-loading {
  font-size: 11px;
  color: var(--text-muted);
  padding: 4px 20px 8px;
}

/* ── Selected session compact card ── */
.selected-card {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 12px 8px;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.selected-card:hover { border-color: #c8ff00; }
.lm-badge-sm {
  width: 36px; height: 36px;
  background: #e63946;
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 900; color: #fff;
  letter-spacing: -0.3px;
  flex-shrink: 0;
}
.sel-info { flex: 1; min-width: 0; }
.sel-track {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--text-primary);
}
.sel-car {
  font-size: 11px; color: var(--text-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sel-driver { color: var(--text-muted); }
.sel-meta {
  display: flex; gap: 8px; align-items: center;
  margin-top: 2px; font-size: 11px;
}
.sel-time { color: var(--text-primary); font-weight: 600; }
.sel-type { font-weight: 600; font-size: 10px; text-transform: uppercase; }
.sel-date { color: var(--text-muted); }
.btn-change {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}
.btn-change:hover { color: var(--text-primary); border-color: var(--text-muted); }

/* ── Session picker (card list) ── */
.session-picker {
  padding: 0 12px 8px;
}
.picker-scroll {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
}
.pick-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  transition: all 0.12s;
  border-bottom: 1px solid var(--border);
}
.pick-card:last-child { border-bottom: none; }
.pick-card:hover { background: var(--bg-tertiary); }
.pick-card.active {
  background: rgba(200, 255, 0, 0.06);
  border-left: 3px solid #c8ff00;
}
.side-b .pick-card.active {
  background: rgba(59, 130, 246, 0.06);
  border-left-color: var(--accent-blue);
}
.side-a .pick-card.active {
  background: rgba(249, 115, 22, 0.06);
  border-left-color: var(--accent-orange);
}
.pick-info { flex: 1; min-width: 0; }
.pick-track {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--text-primary); line-height: 1.3;
}
.pick-layout {
  font-size: 10px; color: var(--text-muted); font-style: italic;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.pick-car {
  font-size: 11px; color: var(--text-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  margin-top: 1px;
}
.pick-driver { color: var(--text-muted); }
.pick-bottom {
  display: flex; gap: 8px; align-items: center;
  margin-top: 2px; font-size: 11px;
}
.pick-time { color: #fff; font-weight: 600; }
.pick-laps { color: var(--text-muted); }
.pick-type { font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; }
.pick-date {
  font-size: 10px; color: var(--text-muted);
  text-align: right; white-space: nowrap; flex-shrink: 0;
}
.pick-empty {
  padding: 20px; text-align: center;
  font-size: 12px; color: var(--text-muted);
}
.picker-b-filters {
  padding: 8px 10px;
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 6px;
}
.picker-b-track {
  font-size: 11px; color: var(--text-muted);
}
.picker-b-track strong { color: var(--text-primary); }
.picker-b-driver {
  display: flex; align-items: center; gap: 8px;
}
.filter-select-sm {
  flex: 1; padding: 4px 6px; font-size: 11px;
}

/* Lap list mini */
.lap-list-mini {
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--bg-primary);
}
.lap-row-mini {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  cursor: pointer;
  transition: background 0.1s;
  font-size: 12px;
}
.lap-row-mini:hover { background: var(--bg-tertiary); }
.lap-row-mini.active {
  background: rgba(249, 115, 22, 0.08);
  border-left: 3px solid var(--accent-orange);
}
.side-b .lap-row-mini.active {
  background: rgba(59, 130, 246, 0.08);
  border-left-color: var(--accent-blue);
}
.lap-num {
  color: var(--text-secondary);
  font-weight: 600;
  width: 28px;
}
.lap-time {
  color: var(--text-primary);
  margin-left: auto;
}

/* Delta block */
.delta-block {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
}
.delta-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
}
.delta-value {
  font-size: 24px;
  font-weight: 800;
}
.gap-red { color: #ef4444; }
.gap-green { color: #22c55e; }

/* ===== Panels (segments / coaching) ===== */
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
.panel-header:hover { background: var(--bg-tertiary); }
.panel-chevron {
  font-size: 11px;
  color: var(--text-muted);
  transition: transform 0.15s ease;
  display: inline-block;
}
.panel-chevron.open { transform: rotate(90deg); }
.panel-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  flex: 1;
}
.panel-body {
  padding: 0 20px 12px;
}
.stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.stats-table th {
  padding: 2px 0;
  font-weight: 700;
  border: none;
}
.stat-label {
  color: var(--text-secondary);
  padding: 4px 0;
  font-weight: 500;
}
.stat-value {
  text-align: right;
  color: var(--text-primary);
  font-weight: 600;
  padding: 4px 0;
}
.stat-diff {
  text-align: right;
  padding: 4px 0 4px 8px;
  width: 70px;
}

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
.empty-main {
  grid-row: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-muted);
}
.empty-icon {
  font-size: 48px;
  opacity: 0.3;
}
.empty-text {
  font-size: 14px;
  max-width: 280px;
  text-align: center;
  line-height: 1.6;
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
.close-corner {
  margin-left: auto;
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
  display: flex;
  align-items: center;
  gap: 10px;
}
.chart-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: none;
}
.cl-line {
  display: inline-block;
  width: 14px; height: 2px;
  border-radius: 1px;
  vertical-align: middle;
}
.cl-dashed {
  background: repeating-linear-gradient(
    90deg,
    currentColor 0px, currentColor 4px,
    transparent 4px, transparent 7px
  ) !important;
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
