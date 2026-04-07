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
  const compositeAvailable = ref(false)
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
  const driverBests = ref([])

  // Coaching analysis state
  const coaching = ref(null)

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
    const valid = laps.value.filter(l => l.valid !== false && l.lap_time_ms > 0)
    const pool = valid.length > 0 ? valid : laps.value
    return pool.reduce((best, l) =>
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
      compositeAvailable.value = data.composite_available || false
      log('laps', `got ${data.laps.length} laps`)

      if (loading.value) setProgress(Math.max(loadingProgress.value, 50), 'Selecting lap…')

      if (data.laps.length > 0) {
        const validLaps = data.laps.filter(l => l.valid !== false && l.lap_time_ms > 0)
        const pool = validLaps.length > 0 ? validLaps : data.laps
        // Pick the last valid lap as active (most recent to analyze)
        const lastValid = pool[pool.length - 1]
        log('laps', `selecting last valid lap ${lastValid.lap_number} (${lastValid.lap_time_ms}ms)`)
        await _selectActiveLapInternal(lastValid.lap_number)

        // Auto-select fastest valid lap as reference baseline
        if (!refLap.value && pool.length > 1) {
          const fastest = pool.reduce((b, l) => l.lap_time_ms < b.lap_time_ms ? l : b)
          log('laps', `auto-ref = lap ${fastest.lap_number} (${fastest.lap_time_ms}ms)`)
          await selectRefLap(fastest.lap_number)
        }
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

      // Recompute delta when active lap changes and ref is set
      if (refLap.value && refTelemetry.value) {
        await _recomputeDelta(lapNumber)
      }
    } catch (e) {
      log('activeLap', 'ERROR', e.message)
      error.value = e.message
    }
  }

  /** Recompute delta for current active lap vs current ref. */
  async function _recomputeDelta(activeLapNumber) {
    if (!refLap.value || !refTelemetry.value) return
    log('delta', `recomputing for lap ${activeLapNumber} vs ref ${refLap.value.lap_number}…`)
    if (refLap.value.lap_number === 0 || refLap.value._crossSession) {
      // Composite or cross-session: client-side delta
      if (activeTelemetry.value?.time?.length && refTelemetry.value?.time?.length) {
        delta.value = computeClientDelta(activeTelemetry.value, refTelemetry.value)
      } else {
        delta.value = computeClientDeltaFromSpeed(activeTelemetry.value, refTelemetry.value)
      }
    } else {
      try {
        const { data } = await withRetry(() =>
          axios.get(`/api/delta/${sessionId.value}/${activeLapNumber}/${refLap.value.lap_number}`)
        )
        delta.value = data
      } catch (e) {
        // Fallback to client-side
        if (activeTelemetry.value?.time?.length && refTelemetry.value?.time?.length) {
          delta.value = computeClientDelta(activeTelemetry.value, refTelemetry.value)
        }
      }
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
    log('refLap', `selecting ref lap ${lapNumber}…`)
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading reference lap…')
    try {
      if (lapNumber === 0) {
        // Composite best lap — fetch telemetry only, delta computed client-side
        refLap.value = {
          lap_number: 0,
          lap_time_ms: theoreticalBestMs.value || 0,
          sectors: theoreticalSectors.value,
          gap_to_best_ms: 0,
          valid: true,
        }
        const { data: telData } = await withRetry(() =>
          axios.get(`/api/telemetry/${sessionId.value}/0`)
        )
        refTelemetry.value = telData
        if (activeTelemetry.value?.time?.length && telData.time?.length) {
          delta.value = computeClientDelta(activeTelemetry.value, telData)
        } else {
          delta.value = null
        }
      } else {
        refLap.value = laps.value.find(l => l.lap_number === lapNumber)
        const [telRes, deltaRes] = await Promise.all([
          withRetry(() => axios.get(`/api/telemetry/${sessionId.value}/${lapNumber}`)),
          activeLap.value
            ? withRetry(() => axios.get(`/api/delta/${sessionId.value}/${activeLap.value.lap_number}/${lapNumber}`))
            : Promise.resolve({ data: null }),
        ])
        refTelemetry.value = telRes.data
        delta.value = deltaRes.data
      }
      log('refLap', `got telemetry + delta`)
      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('refLap', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  /**
   * Load a reference lap from a DIFFERENT session (cross-session comparison).
   * Computes delta client-side since the backend delta endpoint is same-session only.
   */
  async function loadCrossSessionRef(refSid, lapNumber) {
    log('crossRef', `loading session=${refSid} lap=${lapNumber}…`)
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading cross-session reference…')
    try {
      // Fetch ref laps to get lap_time_ms
      const { data: lapData } = await withRetry(() => axios.get(`/api/laps/${refSid}`))
      const lapInfo = lapData.laps.find(l => l.lap_number === lapNumber)
      if (!lapInfo) throw new Error(`Lap ${lapNumber} not found in session ${refSid}`)
      refLap.value = lapInfo

      if (!isNested) setProgress(40, 'Loading reference telemetry…')
      const { data: telData } = await withRetry(() => axios.get(`/api/telemetry/${refSid}/${lapNumber}`))
      refTelemetry.value = telData

      // Compute delta client-side from time arrays
      if (!isNested) setProgress(70, 'Computing delta…')
      if (activeTelemetry.value?.time?.length && telData.time?.length) {
        delta.value = computeClientDelta(activeTelemetry.value, telData)
        log('crossRef', `computed client-side delta (${delta.value.distance.length} points)`)
      } else {
        // Fallback: approximate time from distance/speed
        delta.value = computeClientDeltaFromSpeed(activeTelemetry.value, telData)
        log('crossRef', `computed speed-based delta (${delta.value.distance.length} points)`)
      }

      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('crossRef', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  /**
   * Load best lap from another driver's session as reference.
   * Loads the session on the backend, finds fastest lap, sets as cross-session ref.
   */
  async function loadDriverBestRef(filename, driver) {
    log('driverBestRef', `loading ${filename} (${driver})…`)
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Loading driver best…')
    try {
      // Load that session (without changing current view)
      const { data: sess } = await withRetry(() =>
        axios.post('/api/load', null, { params: { filename, driver } })
      )
      if (!isNested) setProgress(40, 'Finding fastest lap…')
      const { data: lapData } = await withRetry(() =>
        axios.get(`/api/laps/${sess.session_id}`)
      )
      const fastest = lapData.laps.reduce((b, l) => l.lap_time_ms < b.lap_time_ms ? l : b)
      if (!isNested) setProgress(60, 'Loading reference telemetry…')
      await loadCrossSessionRef(sess.session_id, fastest.lap_number)
      // Mark as cross-session for delta recomputation
      if (refLap.value) refLap.value._crossSession = true
      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('driverBestRef', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  async function fetchDriverBests(track) {
    if (!track) return
    log('driverBests', `fetching for track=${track}…`)
    try {
      const { data } = await withRetry(() =>
        axios.get('/api/driver-bests', { params: { track } })
      )
      driverBests.value = data
      log('driverBests', `got ${data.length} driver bests`)
    } catch (e) {
      log('driverBests', 'ERROR', e.message)
    }
  }

  async function deleteSession(filename) {
    log('delete', `deleting ${filename}…`)
    try {
      await withRetry(() =>
        axios.delete('/api/session/delete', { params: { filename } })
      )
      sessions.value = sessions.value.filter(s => s.filename !== filename)
      log('delete', 'done')
    } catch (e) {
      log('delete', 'ERROR', e.message)
      error.value = e.message
    }
  }

  /** Compute delta from time(distance) arrays. */
  function computeClientDelta(active, ref) {
    const dA = active.distance, tA = active.time
    const dR = ref.distance, tR = ref.time
    const maxDist = Math.min(dA[dA.length - 1], dR[dR.length - 1])
    const resolution = 1.0
    const dist = [], dt = []
    for (let d = 0; d < maxDist; d += resolution) {
      dist.push(d)
      const ta = lerpArr(dA, tA, d)
      const tr = lerpArr(dR, tR, d)
      dt.push(ta - tr) // positive = active is slower
    }
    return { distance: dist, delta: dt }
  }

  /** Approximate delta from speed when time arrays not available. */
  function computeClientDeltaFromSpeed(active, ref) {
    const dA = active.distance, sA = active.speed
    const dR = ref.distance, sR = ref.speed
    const maxDist = Math.min(dA[dA.length - 1], dR[dR.length - 1])
    const resolution = 1.0
    const dist = [], dt = []
    let cumDelta = 0
    for (let d = 0; d < maxDist; d += resolution) {
      const va = lerpArr(dA, sA, d) / 3.6 // km/h → m/s
      const vr = lerpArr(dR, sR, d) / 3.6
      // time to cover 1m at this speed
      const dtA = va > 0.1 ? resolution / va : 0
      const dtR = vr > 0.1 ? resolution / vr : 0
      cumDelta += dtA - dtR
      dist.push(d)
      dt.push(cumDelta)
    }
    return { distance: dist, delta: dt }
  }

  /** Linear interpolation: find value at distance d in sorted arrays. */
  function lerpArr(dArr, vArr, d) {
    if (d <= dArr[0]) return vArr[0]
    if (d >= dArr[dArr.length - 1]) return vArr[vArr.length - 1]
    // Binary search
    let lo = 0, hi = dArr.length - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (dArr[mid] <= d) lo = mid; else hi = mid
    }
    const t = (d - dArr[lo]) / (dArr[hi] - dArr[lo] || 1)
    return vArr[lo] + t * (vArr[hi] - vArr[lo])
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

  async function fetchCoaching() {
    if (!sessionId.value || !activeLap.value || !refLap.value) {
      log('coaching', 'skipped — missing session/active/ref')
      return
    }
    log('coaching', `fetching for laps ${activeLap.value.lap_number} vs ${refLap.value.lap_number}`)
    const isNested = loading.value
    if (!isNested) setProgress(10, 'Analysiere Coaching…')
    try {
      const { data } = await withRetry(() => axios.get(
        `/api/coaching/${sessionId.value}/${activeLap.value.lap_number}/${refLap.value.lap_number}`
      ))
      coaching.value = data
      log('coaching', `got ${data.segments?.length || 0} segments`)
      if (!isNested) setProgress(100, 'Done')
    } catch (e) {
      log('coaching', 'ERROR', e.message)
      error.value = e.message
    } finally {
      if (!isNested) clearProgress()
    }
  }

  return {
    sessions, currentSession, laps, theoreticalBestMs, theoreticalSectors,
    compositeAvailable,
    activeLap, refLap, activeTelemetry, refTelemetry,
    corners, delta, activeCorner, cursorDistance,
    loading, loadingProgress, loadingMessage, error, sessionId, fastestLap,
    loadedSessions, comparison, driverName, drivers, tracks,
    coaching, driverBests,
    fetchSessions, loadSession, fetchLaps, uploadFile,
    selectActiveLap, selectRefLap, loadCrossSessionRef, loadDriverBestRef,
    fetchCorners, loadDelta,
    setCursorDistance, setActiveCorner,
    fetchLoadedSessions, updateDriver, fetchComparison,
    fetchCoaching, fetchDriverBests, deleteSession,
  }
})
