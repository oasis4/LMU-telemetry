/**
 * The only place that knows the API's shape.
 *
 * Uses fetch for JSON reads and sharing mutations, without an extra HTTP
 * client dependency.
 *
 * Measurement arrays are handed back as plain `Float64Array`s. They are the
 * reason a comparison was slow - see `stores/telemetry.js` - and typed arrays
 * make it impossible to accidentally make one deeply reactive: Vue leaves
 * them alone.
 */

const DEFAULT_BASE = import.meta?.env?.VITE_API_BASE ?? globalThis.location.origin

export class ApiError extends Error {
  constructor(message, status, url) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
  }
}

/** Turn every array in `series` into a Float64Array, leaving the rest alone. */
export function toTypedSeries(series) {
  const out = {}
  for (const [name, values] of Object.entries(series ?? {})) {
    out[name] = values instanceof Float64Array ? values : Float64Array.from(values)
  }
  return out
}

export function createClient({ base = DEFAULT_BASE, fetcher = fetch } = {}) {
  async function get(path, params, options) {
    const url = new URL(path, base)
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value))
    }
    let response
    try {
      response = await fetcher(url.toString(), ...(options ? [options] : []))
    } catch (cause) {
      // A network failure and a refusal read very differently to a user, so
      // they are not collapsed into one message.
      throw new ApiError(`cannot reach the server at ${base}`, 0, url.toString())
    }
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`
      try {
        const body = await response.json()
        if (body?.detail) detail = body.detail
      } catch {
        /* the body was not JSON; the status line is what we have */
      }
      throw new ApiError(detail, response.status, url.toString())
    }
    return response.json()
  }

  const write = (method, path, body) => get(path, undefined, {
    method,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })

  return {
    base,
    sharing: () => get('/api/sharing'),
    saveSharing: (body) => write('PUT', '/api/sharing/settings', body),
    addFriend: (body) => write('POST', '/api/sharing/friends', body),
    removeFriend: (id) => write('DELETE', `/api/sharing/friends/${encodeURIComponent(id)}`),
    syncFriends: (id) => write('POST', id ? `/api/sharing/friends/${encodeURIComponent(id)}/sync` : '/api/sharing/sync'),
    shareLap: (name, lap) => write('POST', `/api/sessions/${encodeURIComponent(name)}/laps/${lap}/share`),
    stopSharing: (id) => write('DELETE', `/api/sharing/published/${encodeURIComponent(id)}`),
    health: () => get('/api/health'),
    sessions: () => get('/api/sessions').then((body) => body.sessions),
    laps: (name) => get(`/api/sessions/${encodeURIComponent(name)}/laps`).then((b) => b.laps),
    track: (name) => get(`/api/sessions/${encodeURIComponent(name)}/track`),

    // No toTypedSeries: this answer carries no measurement arrays, only a few
    // dozen numbers. Wrapping them in Float64Array would say otherwise.
    ideal: (name) => get(`/api/sessions/${encodeURIComponent(name)}/ideal`),

    async map(name, { full = false } = {}) {
      const body = await get(`/api/sessions/${encodeURIComponent(name)}/map`, {
        full: full || undefined,
      })
      return { ...body, x: Float64Array.from(body.x), y: Float64Array.from(body.y) }
    },

    async trace(name, lap, { full = false, reference } = {}) {
      const body = await get(
        `/api/sessions/${encodeURIComponent(name)}/laps/${lap}/trace`,
        { full: full || undefined, reference },
      )
      return { ...body, series: toTypedSeries(body.series) }
    },

    async compare({ reference, referenceLap, other, otherLap, full = false }) {
      const body = await get('/api/compare', {
        reference,
        reference_lap: referenceLap,
        other,
        other_lap: otherLap,
        full: full || undefined,
      })
      return { ...body, series: toTypedSeries(body.series) }
    },
  }
}
