import { describe, expect, it, vi } from 'vitest'

import { ApiError, createClient, toTypedSeries } from '../src/api/client.js'

function respond(body, { ok = true, status = 200, statusText = 'OK' } = {}) {
  return vi.fn(async () => ({ ok, status, statusText, json: async () => body }))
}

describe('the api client', () => {
  it('turns measurement arrays into typed arrays', () => {
    const typed = toTypedSeries({ speed: [1, 2, 3] })
    expect(typed.speed).toBeInstanceOf(Float64Array)
    expect(Array.from(typed.speed)).toEqual([1, 2, 3])
  })

  it('leaves an already typed array alone rather than copying it', () => {
    const original = Float64Array.from([1, 2])
    expect(toTypedSeries({ speed: original }).speed).toBe(original)
  })

  it('asks for a comparison with both laps in one request', async () => {
    const fetcher = respond({ series: {}, corners: [] })
    const client = createClient({ base: 'http://x/', fetcher })

    await client.compare({
      reference: 'a.duckdb', referenceLap: 2, other: 'b.duckdb', otherLap: 5,
    })

    const url = new URL(fetcher.mock.calls[0][0])
    expect(url.pathname).toBe('/api/compare')
    expect(url.searchParams.get('reference')).toBe('a.duckdb')
    expect(url.searchParams.get('reference_lap')).toBe('2')
    expect(url.searchParams.get('other')).toBe('b.duckdb')
    expect(url.searchParams.get('other_lap')).toBe('5')
  })

  it('does not ask for full resolution unless told to', async () => {
    const fetcher = respond({ series: {}, corners: [] })
    const client = createClient({ base: 'http://x/', fetcher })

    await client.compare({ reference: 'a', referenceLap: 1, other: 'a', otherLap: 2 })
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.has('full')).toBe(false)

    await client.compare({
      reference: 'a', referenceLap: 1, other: 'a', otherLap: 2, full: true,
    })
    expect(new URL(fetcher.mock.calls[1][0]).searchParams.get('full')).toBe('true')
  })

  it('escapes a recording name so a space or a slash cannot break the path', async () => {
    const fetcher = respond({ laps: [] })
    const client = createClient({ base: 'http://x/', fetcher })

    await client.laps('Circuit de la Sarthe_R.duckdb')

    expect(fetcher.mock.calls[0][0]).toContain('Circuit%20de%20la%20Sarthe_R.duckdb')
  })

  it('brings the map back as typed coordinate arrays', async () => {
    const fetcher = respond({
      track: 'Monza', x: [0, 1, 2], y: [10, 11, 12], corners: [], samples: 3,
    })
    const client = createClient({ base: 'http://x/', fetcher })

    const map = await client.map('monza.duckdb')

    expect(map.x).toBeInstanceOf(Float64Array)
    expect(map.y).toBeInstanceOf(Float64Array)
    expect(Array.from(map.y)).toEqual([10, 11, 12])
    expect(new URL(fetcher.mock.calls[0][0]).pathname).toBe(
      '/api/sessions/monza.duckdb/map',
    )
  })

  it('asks for the full map only when told to', async () => {
    const fetcher = respond({ x: [], y: [], corners: [] })
    const client = createClient({ base: 'http://x/', fetcher })

    await client.map('a.duckdb')
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.has('full')).toBe(false)

    await client.map('a.duckdb', { full: true })
    expect(new URL(fetcher.mock.calls[1][0]).searchParams.get('full')).toBe('true')
  })

  it('reports the server’s own reason for a refusal', async () => {
    const fetcher = respond(
      { detail: 'Monza and Paul Ricard are different circuits' },
      { ok: false, status: 422, statusText: 'Unprocessable Entity' },
    )
    const client = createClient({ base: 'http://x/', fetcher })

    await expect(
      client.compare({ reference: 'a', referenceLap: 1, other: 'b', otherLap: 1 }),
    ).rejects.toThrow(/different circuits/)
  })

  it('says the server is unreachable rather than reporting a status', async () => {
    // A refusal and a server that is not running need different actions from
    // the user, so they must not read the same.
    const client = createClient({
      base: 'http://x/',
      fetcher: async () => {
        throw new TypeError('Failed to fetch')
      },
    })

    await expect(client.sessions()).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
    })
    await expect(client.sessions()).rejects.toThrow(/cannot reach the server/)
  })

  it('falls back to the status line when the error body is not JSON', async () => {
    const client = createClient({
      base: 'http://x/',
      fetcher: async () => ({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => {
          throw new Error('not json')
        },
      }),
    })
    await expect(client.sessions()).rejects.toThrow(/500 Internal Server Error/)
  })

  it('is an ApiError carrying the url that failed', async () => {
    const client = createClient({
      base: 'http://x/',
      fetcher: respond({}, { ok: false, status: 404, statusText: 'Not Found' }),
    })
    const failure = await client.track('missing.duckdb').catch((e) => e)
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure.url).toContain('/api/sessions/missing.duckdb/track')
  })

  it('asks for an ideal lap by recording alone', async () => {
    // No lap number: the ideal is built from the recording's usable laps as a
    // set, which is what ideal_lap requires.
    const fetcher = respond({ blocks: [], seams: [] })
    const client = createClient({ base: 'http://x/', fetcher })

    await client.ideal('Monza Q.duckdb')

    const url = new URL(fetcher.mock.calls[0][0])
    expect(url.pathname).toBe('/api/sessions/Monza%20Q.duckdb/ideal')
    expect([...url.searchParams]).toEqual([])
  })

  it('hands the ideal lap back as plain numbers, not typed arrays', async () => {
    // Nothing here is a measurement series. Float64Array would describe it
    // dishonestly and break `.toFixed` on the way through.
    const client = createClient({
      base: 'http://x/',
      fetcher: respond({ ideal_s: 101.212, blocks: [{ time_s: 30.1 }], seams: [] }),
    })
    const body = await client.ideal('a.duckdb')
    expect(body.blocks[0].time_s).toBe(30.1)
    expect(body.blocks).toBeInstanceOf(Array)
  })

  it('surfaces the reason the server gave for refusing an ideal lap', async () => {
    // The 422 for too few usable laps is the common answer, not an edge case,
    // so its text has to reach the user rather than a status line.
    const client = createClient({
      base: 'http://x/',
      fetcher: vi.fn(async () => ({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        json: async () => ({ detail: "'a.duckdb' has 1 usable lap of 3." }),
      })),
    })
    await expect(client.ideal('a.duckdb')).rejects.toThrow(/1 usable lap of 3/)
  })
})
