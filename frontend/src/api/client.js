/**
 * The only place that knows the API's shape.
 *
 * Written against `fetch` rather than axios: every call here is a GET that
 * returns JSON, which is what fetch does without a dependency. The old client
 * pulled in axios for exactly that.
 *
 * Measurement arrays are handed back as plain `Float64Array`s. They are the
 * reason a comparison was slow - see `stores/telemetry.js` - and typed arrays
 * make it impossible to accidentally make one deeply reactive: Vue leaves
 * them alone.
 */

const DEFAULT_BASE = import.meta?.env?.VITE_API_BASE ?? 'http://127.0.0.1:8000'

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
  async function get(path, params) {
    const url = new URL(path, base)
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value))
    }
    let response
    try {
      response = await fetcher(url.toString())
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

  return {
    base,
    health: () => get('/api/health'),
    sessions: () => get('/api/sessions').then((body) => body.sessions),
    laps: (name) => get(`/api/sessions/${encodeURIComponent(name)}/laps`).then((b) => b.laps),
    track: (name) => get(`/api/sessions/${encodeURIComponent(name)}/track`),

    async trace(name, lap, { full = false } = {}) {
      const body = await get(
        `/api/sessions/${encodeURIComponent(name)}/laps/${lap}/trace`,
        { full: full || undefined },
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
