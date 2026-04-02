import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

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
  const loading = ref(false)
  const error = ref(null)

  // Computed
  const sessionId = computed(() => currentSession.value?.session_id || null)

  const fastestLap = computed(() => {
    if (!laps.value.length) return null
    return laps.value.reduce((best, l) =>
      l.lap_time_ms < best.lap_time_ms ? l : best
    )
  })

  // Actions
  async function fetchSessions() {
    loading.value = true
    error.value = null
    try {
      const { data } = await axios.get('/api/sessions')
      sessions.value = data
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function loadSession(filename) {
    loading.value = true
    error.value = null
    try {
      const { data } = await axios.post('/api/load', null, { params: { filename } })
      currentSession.value = data
      await fetchLaps()
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchLaps() {
    if (!sessionId.value) return
    try {
      const { data } = await axios.get(`/api/laps/${sessionId.value}`)
      laps.value = data.laps
      theoreticalBestMs.value = data.theoretical_best_ms
      theoreticalSectors.value = data.theoretical_sectors
      // Auto-select fastest lap
      if (data.laps.length > 0) {
        const fastest = data.laps.reduce((b, l) =>
          l.lap_time_ms < b.lap_time_ms ? l : b
        )
        await selectActiveLap(fastest.lap_number)
      }
    } catch (e) {
      error.value = e.message
    }
  }

  async function selectActiveLap(lapNumber) {
    if (!sessionId.value) return
    activeLap.value = laps.value.find(l => l.lap_number === lapNumber)
    try {
      const { data } = await axios.get(`/api/telemetry/${sessionId.value}/${lapNumber}`)
      activeTelemetry.value = data
      await fetchCorners(lapNumber)
    } catch (e) {
      error.value = e.message
    }
  }

  async function selectRefLap(lapNumber) {
    if (!sessionId.value) return
    refLap.value = laps.value.find(l => l.lap_number === lapNumber)
    try {
      const [telRes, deltaRes] = await Promise.all([
        axios.get(`/api/telemetry/${sessionId.value}/${lapNumber}`),
        activeLap.value
          ? axios.get(`/api/delta/${sessionId.value}/${activeLap.value.lap_number}/${lapNumber}`)
          : Promise.resolve({ data: null }),
      ])
      refTelemetry.value = telRes.data
      delta.value = deltaRes.data
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchCorners(lapNumber) {
    if (!sessionId.value) return
    try {
      const { data } = await axios.get(`/api/corners/${sessionId.value}`, {
        params: { lap_number: lapNumber },
      })
      corners.value = data.corners
    } catch (e) {
      error.value = e.message
    }
  }

  async function loadDelta() {
    if (!sessionId.value || !activeLap.value || !refLap.value) return
    try {
      const { data } = await axios.get(
        `/api/delta/${sessionId.value}/${activeLap.value.lap_number}/${refLap.value.lap_number}`
      )
      delta.value = data
    } catch (e) {
      error.value = e.message
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
    loading, error, sessionId, fastestLap,
    fetchSessions, loadSession, fetchLaps,
    selectActiveLap, selectRefLap, fetchCorners, loadDelta,
    setCursorDistance, setActiveCorner,
  }
})
