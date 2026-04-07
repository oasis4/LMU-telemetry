<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const router = useRouter()
const dragging = ref(false)
const fileInput = ref(null)

// Dropdown filter state
const filterTrack = ref('')
const filterCar = ref('')
const filterDriver = ref('')
const sortBy = ref('date-desc')

const TYPE_COLORS = { Practice: '#3b82f6', Qualifying: '#f97316', Race: '#22c55e' }

/** Format seconds to m:ss.fff */
function fmtTime(secs) {
  if (!secs || secs <= 0) return '-'
  const m = Math.floor(secs / 60)
  const s = secs - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}

/** Build unique track list from sessions */
const trackOptions = computed(() => {
  const set = new Set()
  store.sessions.forEach(s => { if (s.track) set.add(s.track) })
  return [...set].sort()
})

/** Build unique car list from sessions */
const carOptions = computed(() => {
  const set = new Set()
  store.sessions.forEach(s => { if (s.car) set.add(s.car) })
  return [...set].sort()
})

/** Build unique driver list from sessions */
const driverOptions = computed(() => {
  const set = new Set()
  store.sessions.forEach(s => { if (s.driver) set.add(s.driver) })
  return [...set].sort()
})

/** Parse DD.MM.YYYY HH:MM → timestamp for sorting */
function parseDate(dateStr) {
  if (!dateStr) return 0
  const m = dateStr.match(/(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/)
  if (!m) return 0
  return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]).getTime()
}

/** Filtered and sorted sessions */
const filteredSessions = computed(() => {
  let list = [...store.sessions]
  if (filterTrack.value) list = list.filter(s => s.track === filterTrack.value)
  if (filterCar.value) list = list.filter(s => s.car === filterCar.value)
  if (filterDriver.value) list = list.filter(s => s.driver === filterDriver.value)
  switch (sortBy.value) {
    case 'date-desc': list.sort((a, b) => parseDate(b.date) - parseDate(a.date)); break
    case 'date-asc':  list.sort((a, b) => parseDate(a.date) - parseDate(b.date)); break
    case 'time-asc':  list.sort((a, b) => (a.best_time || Infinity) - (b.best_time || Infinity)); break
    case 'time-desc': list.sort((a, b) => (b.best_time || 0) - (a.best_time || 0)); break
  }
  return list
})

/** Pagination */
const page = ref(1)
const perPage = 20
const totalPages = computed(() => Math.max(1, Math.ceil(filteredSessions.value.length / perPage)))
const pagedSessions = computed(() => {
  const start = (page.value - 1) * perPage
  return filteredSessions.value.slice(start, start + perPage)
})

function setPage(p) {
  page.value = Math.max(1, Math.min(p, totalPages.value))
}

// Reset page when filters change
function onFilterChange() { page.value = 1 }

onMounted(() => {
  store.fetchSessions()
  store.fetchLoadedSessions()
})

async function openSession(s) {
  await store.loadSession(s.filename, s.driver || '')
  if (store.sessionId) {
    router.push({ name: 'dashboard', params: { sessionId: store.sessionId } })
  }
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFiles(files) {
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith('.duckdb')) continue
    const result = await store.uploadFile(file, '')
    if (result) {
      router.push({ name: 'dashboard', params: { sessionId: result.session_id } })
      return
    }
  }
}

function onFileChange(e) {
  if (e.target.files?.length) handleFiles(e.target.files)
  e.target.value = ''
}

function onDrop(e) {
  dragging.value = false
  if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files)
}

function onDragOver(e) {
  e.preventDefault()
  dragging.value = true
}

function onDragLeave() {
  dragging.value = false
}

async function confirmDelete(s) {
  if (!confirm(`Session "${s.track || s.filename}" wirklich löschen?\nDie .duckdb Datei wird permanent gelöscht.`)) return
  await store.deleteSession(s.filename)
}
</script>

<template>
  <div
    class="session-page"
    :class="{ 'drag-over': dragging }"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- Header -->
    <div class="page-header">
      <h1 class="page-title">YOUR SESSIONS</h1>
      <div class="page-pagination" v-if="totalPages > 1">
        <button
          v-for="p in Math.min(totalPages, 5)" :key="p"
          class="page-btn" :class="{ active: page === p }"
          @click="setPage(p)"
        >{{ p }}</button>
        <button v-if="page < totalPages" class="page-btn" @click="setPage(page + 1)">&gt;</button>
      </div>
    </div>

    <!-- Filters and actions bar -->
    <div class="filter-bar">
      <div class="filter-group">
        <div class="filter-item">
          <label class="filter-label">Track:</label>
          <select v-model="filterTrack" class="filter-select" @change="onFilterChange">
            <option value="">All tracks</option>
            <option v-for="t in trackOptions" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="filter-item">
          <label class="filter-label">Car:</label>
          <select v-model="filterCar" class="filter-select" @change="onFilterChange">
            <option value="">All cars</option>
            <option v-for="c in carOptions" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
      </div>
      <div class="action-group">
        <div class="filter-item">
          <label class="filter-label">Driver:</label>
          <select v-model="filterDriver" class="filter-select" @change="onFilterChange">
            <option value="">All drivers</option>
            <option v-for="d in driverOptions" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div class="filter-item">
          <label class="filter-label">Sort:</label>
          <select v-model="sortBy" class="filter-select filter-sort" @change="onFilterChange">
            <option value="date-desc">Datum ↓ (neueste)</option>
            <option value="date-asc">Datum ↑ (älteste)</option>
            <option value="time-asc">Bestzeit ↑ (schnellste)</option>
            <option value="time-desc">Bestzeit ↓ (langsamste)</option>
          </select>
        </div>
        <button class="btn-upload" @click="triggerUpload">
          <input ref="fileInput" type="file" accept=".duckdb" multiple hidden @change="onFileChange" />
          + Upload
        </button>
      </div>
    </div>

    <!-- Session grid -->
    <div class="session-grid-wrap">
      <div v-if="store.loading" class="loading-state">
        <div class="spinner"></div>
        <p>Scanning sessions…</p>
      </div>

      <div v-else-if="filteredSessions.length === 0" class="empty-state">
        <p v-if="store.sessions.length === 0">No sessions found.</p>
        <p v-else>No sessions match the selected filters.</p>
        <p class="text-muted">Drop .duckdb files anywhere or click Upload</p>
      </div>

      <div class="session-grid" v-else>
        <div
          v-for="s in pagedSessions"
          :key="s.filename"
          class="session-card"
          @click="openSession(s)"
        >
          <!-- LM logo -->
          <div class="card-logo">
            <div class="lm-badge">LM</div>
          </div>
          <!-- Info -->
          <div class="card-info">
            <div class="card-track">{{ s.track || s.filename }}</div>
            <div class="card-car">{{ s.car || '—' }} <span class="card-driver" v-if="s.driver">· {{ s.driver }}</span></div>
            <div class="card-time">{{ fmtTime(s.best_time) }}</div>
            <div class="card-meta">
              <span class="card-laps">{{ s.lap_count }} laps</span>
              <span
                class="card-type"
                v-if="s.session_type"
                :style="{ color: TYPE_COLORS[s.session_type] || '#888' }"
              >{{ s.session_type }}</span>
            </div>
          </div>
          <!-- Date -->
          <div class="card-date">{{ s.date }}</div>
          <!-- Delete button -->
          <button class="card-delete" @click.stop="confirmDelete(s)" title="Löschen">🗑</button>
        </div>
      </div>
    </div>

    <!-- Bottom pagination -->
    <div class="bottom-bar" v-if="totalPages > 1">
      <button
        class="page-btn" :class="{ disabled: page <= 1 }"
        @click="setPage(page - 1)"
      >&lt;</button>
      <span class="page-info">Page {{ page }} / {{ totalPages }}</span>
      <button
        class="page-btn" :class="{ disabled: page >= totalPages }"
        @click="setPage(page + 1)"
      >&gt;</button>
    </div>

    <div v-if="store.error" class="error-msg">{{ store.error }}</div>
  </div>
</template>

<style scoped>
.session-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: background 0.2s;
}
.session-page.drag-over {
  background: rgba(59, 130, 246, 0.04);
  outline: 2px dashed var(--accent-blue);
  outline-offset: -8px;
}

/* ---- Header ---- */
.page-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  padding: 24px 24px 8px;
  flex-shrink: 0;
}
.page-title {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.page-pagination {
  display: flex;
  gap: 6px;
}
.page-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}
.page-btn.active {
  background: #c8ff00;
  color: #000;
  border-color: #c8ff00;
}
.page-btn:hover:not(.active):not(.disabled) {
  border-color: var(--text-secondary);
}
.page-btn.disabled {
  opacity: 0.3;
  cursor: default;
}

/* ---- Filter bar ---- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 24px;
  flex-shrink: 0;
}
.filter-group {
  display: flex;
  gap: 16px;
  flex: 1;
}
.filter-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.filter-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  font-weight: 600;
}
.filter-select {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 8px 32px 8px 12px;
  font-size: 14px;
  font-family: var(--font-sans);
  border-radius: 4px;
  cursor: pointer;
  min-width: 220px;
  appearance: auto;
}
.filter-sort {
  min-width: 180px;
}
.filter-select:focus {
  border-color: var(--accent-blue);
  outline: none;
}
.action-group {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-shrink: 0;
}
.btn-upload {
  background: var(--accent-blue);
  color: #fff;
  border: none;
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 4px;
  transition: opacity 0.15s;
  white-space: nowrap;
}
.btn-upload:hover {
  opacity: 0.85;
}

/* ---- Session grid ---- */
.session-grid-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}
.loading-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state {
  text-align: center;
  padding: 80px 20px;
  color: var(--text-muted);
}
.empty-state p {
  font-size: 16px;
  margin-bottom: 8px;
}

.session-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* ---- Session card (TrackTitan-style) ---- */
.session-card {
  display: flex;
  align-items: center;
  gap: 16px;
  text-align: left;
  background: #3a3a3a;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 16px 20px;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text-primary);
  font-family: var(--font-sans);
  min-height: 80px;
  position: relative;
}
.session-card:hover {
  border-color: #c8ff00;
  background: #444;
}
.card-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(0,0,0,0.5);
  border: 1px solid transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 6px;
  opacity: 0;
  transition: all 0.15s;
  z-index: 2;
}
.session-card:hover .card-delete { opacity: 0.7; }
.card-delete:hover {
  opacity: 1 !important;
  color: #ef4444;
  border-color: #ef4444;
  background: rgba(239,68,68,0.1);
}

/* LM logo badge */
.card-logo {
  flex-shrink: 0;
}
.lm-badge {
  width: 56px;
  height: 56px;
  background: #e63946;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 900;
  color: #fff;
  letter-spacing: -0.5px;
}

/* Card info */
.card-info {
  flex: 1;
  min-width: 0;
}
.card-track {
  font-size: 15px;
  font-weight: 700;
  text-transform: uppercase;
  line-height: 1.3;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-car {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.card-driver {
  color: var(--text-muted);
}
.card-time {
  font-size: 14px;
  font-family: var(--font-mono);
  color: #fff;
  font-weight: 600;
  margin-top: 4px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 3px;
  font-size: 12px;
}
.card-laps {
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.card-type {
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

/* Date on right side */
.card-date {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  text-align: right;
  white-space: nowrap;
}

/* ---- Bottom bar ---- */
.bottom-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.page-info {
  font-size: 13px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

/* Error */
.error-msg {
  color: var(--negative);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 10px 16px;
  font-size: 13px;
  margin: 16px 24px 0;
  border-radius: 6px;
}
</style>
