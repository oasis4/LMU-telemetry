/**
 * What the app is currently looking at.
 *
 * The measurement arrays are held in `shallowRef` and stored with `markRaw`.
 * That is the fix for the slowness this rework exists to remove, and it is
 * worth stating why rather than leaving it as an idiom.
 *
 * `ref(payload)` makes Vue walk the value and wrap every nested object and
 * array in a Proxy, recursively. A comparison carries several traces of a few
 * thousand samples each - the old code measured about 300,000 floats - and
 * every one of them was individually proxied, on every selection change. The
 * charts then read through those proxies on every frame.
 *
 * Nothing in the app ever mutates a sample. The arrays are replaced wholesale
 * when a different lap is chosen, and *that* is what a view needs to react to.
 * `shallowRef` reacts to the replacement and not to the contents, so the
 * proxies are never created. `markRaw` says so a second time, on the payload
 * itself, so a later `ref()` elsewhere cannot undo it.
 */

import { computed, markRaw, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { createClient } from '../api/client.js'

export const useTelemetryStore = defineStore('telemetry', () => {
  const client = createClient()

  // Small, cheap, genuinely reactive: these drive the UI's structure.
  const sessions = ref([])
  const laps = ref([])
  const track = ref(null)
  const corners = ref([])
  const loading = ref(false)
  const error = ref(null)

  // Bulk measurements: replaced wholesale, never mutated in place.
  const comparison = shallowRef(null)
  const trace = shallowRef(null)

  const selection = ref({
    reference: null,
    referenceLap: null,
    other: null,
    otherLap: null,
  })

  const cleanLaps = computed(() => laps.value.filter((lap) => lap.clean))
  const ready = computed(
    () =>
      Boolean(selection.value.reference) &&
      selection.value.referenceLap !== null &&
      Boolean(selection.value.other) &&
      selection.value.otherLap !== null,
  )
  const worstCorners = computed(() => {
    const found = comparison.value?.corners ?? []
    return [...found].sort((a, b) => b.lost_s - a.lost_s).slice(0, 5)
  })

  async function run(work) {
    loading.value = true
    error.value = null
    try {
      return await work()
    } catch (cause) {
      error.value = cause.message ?? String(cause)
      return null
    } finally {
      loading.value = false
    }
  }

  const loadSessions = () =>
    run(async () => {
      sessions.value = await client.sessions()
      return sessions.value
    })

  const loadLaps = (name) =>
    run(async () => {
      laps.value = await client.laps(name)
      return laps.value
    })

  const loadTrack = (name) =>
    run(async () => {
      const model = await client.track(name)
      track.value = model
      corners.value = model.corners
      return model
    })

  const loadComparison = ({ full = false } = {}) =>
    run(async () => {
      if (!ready.value) throw new Error('choose two laps first')
      const body = await client.compare({ ...selection.value, full })
      comparison.value = markRaw(body)
      corners.value = body.corners
      return body
    })

  const loadTrace = (name, lap, { full = false } = {}) =>
    run(async () => {
      trace.value = markRaw(await client.trace(name, lap, { full }))
      return trace.value
    })

  function select(patch) {
    selection.value = { ...selection.value, ...patch }
  }

  function reset() {
    comparison.value = null
    trace.value = null
    corners.value = []
    error.value = null
  }

  return {
    client,
    sessions,
    laps,
    track,
    corners,
    loading,
    error,
    comparison,
    trace,
    selection,
    cleanLaps,
    ready,
    worstCorners,
    loadSessions,
    loadLaps,
    loadTrack,
    loadComparison,
    loadTrace,
    select,
    reset,
  }
})
