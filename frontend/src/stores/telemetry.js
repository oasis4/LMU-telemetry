import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

function log(tag, ...args) {
  console.log(`[telemetry:${tag}]`, ...args)
}

/** Retry wrapper — retries on 502/503/network errors (up to 3 attempts). */
async function withRetry(fn, retries = 3, delayMs = 1000) {
  for (let i = 0; i < retries; i++) {
    try {
      return await fn()
    } catch (e) {
      const status = e.response?.status
      const isRetryable = !status || status === 502 || status === 503
      if (isRetryable && i < retries - 1) {
        log('retry', `attempt ${i + 1} failed (${status || 'network'}), retrying in ${delayMs}ms…`)
        await new Promise(r => setTimeout(r, delayMs))
        delayMs *= 2
        continue
      }
      throw e
    }
  }
}

export const useTelemetryStore = defineStore('telemetry', () => {
  // State
  const sessions = ref([])
  const currentSession = ref(null)
  const laps = ref([])
  const theoreticalBestMs = ref(null)
  const theoreticalSectors = ref({})
  const activeLap = ref(null)
  const refLap = ref(null)
  const activeTelemetry = ref(null)
  const refTelemetry = ref(null)
  const corners = ref([])
  const delta = ref(null)
  const activeCorner = ref(null)
  const cursorDistance = ref(null)
  const error = ref(null)

  // Loading state — progress-based
  const loadingProgress = ref(-1) // -1 = idle, 0-100 = loading
  const loadingMessage = ref('')
  const loading = computed(() => loadingProgress.value >= 0)

  // Multi-driver state
  const loadedSessions = ref([])
  const comparison = ref(null)
  const driverName = ref('')

  function setProgress(pct, msg) {
    loadingProgress.value = Math.min(100, Math.max(0, pct))
    if (msg) loadingMessage.value = msg
    log('progress', `${loadingProgress.value}% — ${loadingMessage.value}`)
  }

  function clearProgress() {
    loadingProgress.value = -1
    loadingMessage.value = ''
  }

  // Computed
  const sessionId = computed(() => currentSession.value?.session_id || null)

  const fastestLap = computed(() => {
    if (!laps.value.length) return null
    return laps.value.reduce((best, l) =>
      l.lap_time_ms < best.lap_time_ms ? l : best
    )
  })

  const drivers = computed(() => {
    const names = new Set(loadedSessions.value.map(s => s.driver))
    return [...names]
  })

  const tracks = computed(() => {
    const names = new Set(loadedSessions.value.map(s => s.track).filter(Boolean))
    return [...names]
  })

  // Actions
  async function fetchSessions() {
    log('sessions', 'fetching…')
    error.value = null
    try {
      const { data } = await withRetry(() => axios.get('/api/sessions'))
      sessions.value = data
      log('sessions', `found ${data.length} files`)
    } catch (e) {
      log('sessions', 'ERROR', e.message)
      error.value = e.message
    }
  }

  async function loadSession(filename, driver = '') {
    log('load', `loading ${filename}…`)
    error.value = null
    setProgress(5, 'Opening session…')
    try {
      const params = { filename }
      if (driver) params.driver = driver
      const { data } = await withRetry(() => axios.post('/api/load', null, { params }))
      currentSession.value = data
      log('load', `session ${data.session_id} opened — ${data.track} / ${data.car}`)

      setProgress(30, 'Loading laps…')
      await _fetchLapsInternal()

      setProgress(90, 'Updating session list…')
      await fetchLoadedSessions()

      setProgress(100, 'Done')
    } catch (e) {
      log('load', 'ERROR', e.message)
      error.value = e.message
    } finally {
      clearProgress()
    }
  }

  async function fetchLoadedSessions() {
    log('loaded', 'fetching…')
    try {
      const { data } = await withRetry(() => axios.get('/api/loaded'))
      loadedSessions.value = data
      log('loaded', `${data.length} sessions loaded`)
    } catch (e) {
      log('loaded', 'ERROR', e.message)
      error.value = e.message
    }
  }

  async function updateDriver(sid, driver) {
    log('driver', `updating ${sid} → ${driver}`)
    try {
      await withRetry(() => axios.patch(`/api/session/${sid}/driver`, null, {
        params: { driver },
      }))
      await fetchLoadedSessions()
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchComparison(track = '') {
    log('compare', `fetching… track=${track || 'all'}`)
    error.value = null
    setProgress(10, 'Comparing drivers…')
    try {
      const params = track ? { track } : {}
      const { data } = await withRetry(() => axios.get('/api/compare/corners', { params }))
      comparison.value = data
      log('compare', `got ${data.corners?.length || 0} corners, ${data.drivers?.length || 0} drivers`)
      setProgress(100, 'Done')
    } catch (e) {
      log('compare', 'ERROR', e.message)
      error.value = e.message
    } finally {
      clearProgress()
    }
  }

  async function uploadFile(file, driver = '') {
    log('upload', `uploading ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)…`)
    error.value = null
    setProgress(0, 'Uploading file…')
    try {
      const form = new FormData()
      form.append('file', file)
      const params = driver ? { driver } : {}
      const { data } = await axios.post('/api/upload', form, {
        params,
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress(e) {
          if (e.total) {
            // Upload = 0-50% of total progress
            const uploadPct = Math.round((e.loaded / e.total) * 50)
            setProgress(uploadPct, 'Uploading file…')
          }
        },
      })
      log('upload', `uploaded → session ${data.session_id}`)
      currentSession.value = data

      setProgress(55, 'Refreshing session list…')
      await fetchSessions()

      setProgress(65, 'Updating loaded sessions…')
      await fetchLoadedSessions()

      setProgress(75, 'Loading laps…')
      await _fetchLapsInternal()

      setProgress(100, 'Done')
      return data
    } catch (e) {
      log('upload', 'ERROR', e.response?.data?.detail || e.message)
      error.value = e.response?.data?.detail || e.message
      return null
    } finally {
      clearProgress()
    }
  }

  // Internal fetch laps — does NOT touch loading state
  async function _fetchLapsInternal() {
    if (!sessionId.value) {
      log('laps', 'skipped — no sessionId')
      return
    }
    log('laps', `fetching for session ${sessionId.value}…`)
    try {
      const { data } = await withRetry(() => axios.get(`/api/laps/${sessionId.value}`))
      laps.value = data.laps
      theoreticalBestMs.value = data.theoretical_best_ms
      theoreticalSectors.value = data.theoretical_sectors
      log('laps', `got ${data.laps.length} laps`)

      if (loading.value) setProgress(Math.max(loadingProgress.value, 50), 'Selecting fastest lap…')

      if (data.laps.length > 0) {
        const fastest = data.laps.reduce((b, l) =>
          l.lap_time_ms < b.lap_time_ms ? l : b
        )
        log('laps', `fastest = lap ${fastest.lap_number} (${fastest.lap_time_ms}ms)`)
        await _selectActiveLapInternal(fastest.lap_number)
      }
    } catch (e) {
      log('laps', 'ERROR', e.message)
      error.value = e.message
    }
  }

  // Public fetchLaps — sets its own loading bar (only if no parent op is running)
  async function fetchLaps() {
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading laps…')
    try {
      await _fetchLapsInternal()
      if (!isNested) setProgress(100, 'Done')
    } finally {
      if (!isNested) clearProgress()
    }
  }

  // Internal — does NOT touch loading
  async function _selectActiveLapInternal(lapNumber) {
    if (!sessionId.value) return
    activeLap.value = laps.value.find(l => l.lap_number === lapNumber)
    log('activeLap', `selecting lap ${lapNumber}…`)
    if (loading.value) setProgress(Math.max(loadingProgress.value, 60), 'Loading telemetry…')
    try {
      const { data } = await withRetry(() => axios.get(`/api/telemetry/${sessionId.value}/${lapNumber}`))
      activeTelemetry.value = data
      log('activeLap', `got ${data.distance?.length || 0} telemetry points`)

      if (loading.value) setProgress(Math.max(loadingProgress.value, 75), 'Detecting corners…')
      await _fetchCornersInternal(lapNumber)
    } catch (e) {
      log('activeLap', 'ERROR', e.message)
      error.value = e.message
    }
  }

  // Public selectActiveLap — sets its own loading bar (only if no parent op is running)
  async function selectActiveLap(lapNumber) {
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading lap data…')
    try {
      await _selectActiveLapInternal(lapNumber)
      if (!isNested) setProgress(100, 'Done')
    } finally {
      if (!isNested) clearProgress()
    }
  }

  async function selectRefLap(lapNumber) {
    if (!sessionId.value) return
    refLap.value = laps.value.find(l => l.lap_number === lapNumber)
    log('refLap', `selecting ref lap ${lapNumber}…`)
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading reference lap…')
    try {
      const [telRes, deltaRes] = await Promise.all([
        withRetry(() => axios.get(`/api/telemetry/${sessionId.value}/${lapNumber}`)),
        activeLap.value
          ? withRetry(() => axios.get(`/api/delta/${sessionId.value}/${activeLap.value.lap_number}/${lapNumber}`))
          : Promise.resolve({ data: null }),
      ])
      refTelemetry.value = telRes.data
      delta.value = deltaRes.data
      log('refLap', `got telemetry + delta`)
      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('refLap', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  // Internal — does NOT touch loading
  async function _fetchCornersInternal(lapNumber) {
    if (!sessionId.value) return
    log('corners', `fetching for lap ${lapNumber}…`)
    try {
      const { data } = await withRetry(() => axios.get(`/api/corners/${sessionId.value}`, {
        params: { lap_number: lapNumber },
      }))
      corners.value = data.corners
      log('corners', `got ${data.corners.length} corners`)
    } catch (e) {
      log('corners', 'ERROR', e.message)
      error.value = e.message
    }
  }

  async function fetchCorners(lapNumber) {
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Detecting corners…')
    try {
      await _fetchCornersInternal(lapNumber)
      if (!isNested) setProgress(100, 'Done')
    } finally {
      if (!isNested) clearProgress()
    }
  }

  async function loadDelta() {
    if (!sessionId.value || !activeLap.value || !refLap.value) return
    log('delta', 'loading…')
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Computing delta…')
    try {
      const { data } = await withRetry(() => axios.get(
        `/api/delta/${sessionId.value}/${activeLap.value.lap_number}/${refLap.value.lap_number}`
      ))
      delta.value = data
      log('delta', 'done')
      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('delta', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  function setCursorDistance(d) {
    cursorDistance.value = d
  }

  function setActiveCorner(corner) {
    activeCorner.value = corner
  }

  return {
    sessions, currentSession, laps, theoreticalBestMs, theoreticalSectors,
    activeLap, refLap, activeTelemetry, refTelemetry,
    corners, delta, activeCorner, cursorDistance,
    loading, loadingProgress, loadingMessage, error, sessionId, fastestLap,
    loadedSessions, comparison, driverName, drivers, tracks,
    fetchSessions, loadSession, fetchLaps, uploadFile,
    selectActiveLap, selectRefLap, fetchCorners, loadDelta,
    setCursorDistance, setActiveCorner,
    fetchLoadedSessions, updateDriver, fetchComparison,
  }
})
