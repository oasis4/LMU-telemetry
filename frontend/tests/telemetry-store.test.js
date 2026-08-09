import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { isProxy, isReactive, ref } from 'vue'

import { useTelemetryStore } from '../src/stores/telemetry.js'

const SAMPLES = 3000

function comparisonPayload() {
  const series = {}
  for (const name of ['distance_m', 'delta_s', 'speed_reference_kmh', 'speed_other_kmh']) {
    series[name] = Array.from({ length: SAMPLES }, (_, i) => i * 0.5)
  }
  return {
    reference: { name: 'a.duckdb', lap: 2, duration_s: 111.0 },
    other: { name: 'a.duckdb', lap: 1, duration_s: 116.56 },
    lap_delta_s: 5.56,
    samples: SAMPLES,
    series,
    corners: [
      { index: 1, name: 'T1', lost_s: 0.4, summary: 'T1: lost 0.40 s', differences: [] },
      { index: 2, name: 'T2', lost_s: 1.9, summary: 'T2: lost 1.90 s', differences: [] },
      { index: 3, name: 'T3', lost_s: -0.2, summary: 'T3: gained 0.20 s', differences: [] },
    ],
  }
}

// The client returns the decoded body, so a stub stands in for the whole call
// rather than for fetch. Stubbing fetch instead would also exercise the
// client's parsing, which client.test.js covers on its own.
function returns(body) {
  return async () => body
}

describe('the telemetry store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('does not wrap measurement samples in reactive proxies', async () => {
    // This is the fix the rework exists for. ref() walks a payload and proxies
    // every nested array recursively; the old store did that to about 300,000
    // floats on every selection change, and the charts then read through the
    // proxies on every frame.
    const store = useTelemetryStore()
    store.client.compare = returns(comparisonPayload())
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'a.duckdb', otherLap: 1 })

    await store.loadComparison()

    expect(store.comparison).not.toBeNull()
    expect(isProxy(store.comparison)).toBe(false)
    expect(isReactive(store.comparison.series)).toBe(false)
    expect(isReactive(store.comparison.series.delta_s)).toBe(false)
  })

  it('holds measurements in a shallow ref, so any payload stays raw', () => {
    // shallowRef and markRaw cover for each other: with markRaw applied in
    // loadComparison, a deep ref would behave identically, and the test above
    // passes either way. This one assigns a payload that was never marked, so
    // only the shallowness of the ref can keep it unproxied.
    const store = useTelemetryStore()
    store.comparison = comparisonPayload()
    expect(isReactive(store.comparison.series)).toBe(false)
  })

  it('marks the payload raw, so a deep ref elsewhere cannot proxy it either', async () => {
    // This is markRaw's own job, and the only thing that fails if it goes:
    // a component or a later store assigning the payload into a deep ref.
    const store = useTelemetryStore()
    store.client.compare = returns(comparisonPayload())
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'a.duckdb', otherLap: 1 })
    await store.loadComparison()

    const elsewhere = ref({ held: store.comparison })

    expect(isReactive(elsewhere.value.held)).toBe(false)
    expect(isReactive(elsewhere.value.held.series.delta_s)).toBe(false)
  })

  it('shows the difference: a plain ref would proxy the same payload', () => {
    // The contrast is the point. Without it the assertion above could pass
    // because the payload happens not to be proxyable, rather than because
    // the store chose shallowRef.
    const payload = comparisonPayload()
    const deep = ref(payload)
    expect(isReactive(deep.value.series)).toBe(true)
  })

  it('still reacts when a different comparison replaces the old one', async () => {
    // shallowRef is only correct because nothing mutates a sample in place:
    // the arrays are replaced wholesale, and that is what a view watches.
    const store = useTelemetryStore()
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'a.duckdb', otherLap: 1 })

    store.client.compare = returns(comparisonPayload())
    await store.loadComparison()
    const first = store.comparison

    const second = comparisonPayload()
    second.lap_delta_s = 1.25
    store.client.compare = returns(second)
    await store.loadComparison()

    expect(store.comparison).not.toBe(first)
    expect(store.comparison.lap_delta_s).toBe(1.25)
  })

  it('refuses to ask for a comparison before two laps are chosen', async () => {
    const store = useTelemetryStore()
    store.client.compare = () => {
      throw new Error('the server must not be asked')
    }
    expect(store.ready).toBe(false)
    await store.loadComparison()
    expect(store.error).toMatch(/choose two laps/i)
  })

  it('reports a failure instead of leaving the view spinning', async () => {
    const store = useTelemetryStore()
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'b.duckdb', otherLap: 1 })
    store.client.compare = async () => {
      throw new Error('different circuits')
    }

    await store.loadComparison()

    expect(store.loading).toBe(false)
    expect(store.error).toBe('different circuits')
    expect(store.comparison).toBeNull()
  })

  it('ranks the corners that cost the most time first', async () => {
    const store = useTelemetryStore()
    store.client.compare = returns(comparisonPayload())
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'a.duckdb', otherLap: 1 })

    await store.loadComparison()

    expect(store.worstCorners.map((c) => c.name)).toEqual(['T2', 'T1', 'T3'])
  })

  it('does not reorder the corner list it was given', async () => {
    // Track order is what the map and the table read. Sorting in place would
    // silently renumber them.
    const store = useTelemetryStore()
    store.client.compare = returns(comparisonPayload())
    store.select({ reference: 'a.duckdb', referenceLap: 2, other: 'a.duckdb', otherLap: 1 })

    await store.loadComparison()
    void store.worstCorners

    expect(store.corners.map((c) => c.index)).toEqual([1, 2, 3])
  })

  it('keeps only the laps a comparison can actually use', async () => {
    const store = useTelemetryStore()
    store.client.laps = async () => [
      { number: 0, clean: false, reason: 'lap 0 runs from the start of recording' },
      { number: 1, clean: true, reason: null },
      { number: 2, clean: true, reason: null },
    ]

    await store.loadLaps('a.duckdb')

    expect(store.laps).toHaveLength(3)
    expect(store.cleanLaps.map((l) => l.number)).toEqual([1, 2])
  })
})

describe('what a view watches to know the selection changed', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('has nothing to watch until both laps are chosen', () => {
    const store = useTelemetryStore()
    expect(store.selectionKey).toBeNull()
    store.select({ reference: 'a.duckdb', referenceLap: 2 })
    expect(store.selectionKey).toBeNull()
  })

  it('changes when only the lap changes', async () => {
    // `ready` cannot do this job. It is true for both selections, and a
    // computed that recomputes to the same value notifies nobody - so a view
    // watching it goes on showing the previous lap's numbers with the new
    // lap's name beside them. This is the whole reason the key exists.
    const store = useTelemetryStore()
    store.select({ reference: 'a.duckdb', referenceLap: 2,
                   other: 'b.duckdb', otherLap: 5 })
    const before = store.selectionKey
    expect(store.ready).toBe(true)

    store.select({ otherLap: 9 })

    expect(store.ready).toBe(true)
    expect(store.selectionKey).not.toBe(before)
  })

  it('changes when the recording on one side changes', () => {
    const store = useTelemetryStore()
    store.select({ reference: 'a.duckdb', referenceLap: 2,
                   other: 'b.duckdb', otherLap: 5 })
    const before = store.selectionKey
    store.select({ other: 'c.duckdb' })
    expect(store.selectionKey).not.toBe(before)
  })

  it('tells two selections apart that share a name and a number', () => {
    // "a.duckdb lap 21" against "b.duckdb lap 5" must not read the same as
    // "a.duckdb lap 2" against "1b.duckdb lap 5".
    const store = useTelemetryStore()
    store.select({ reference: 'a.duckdb', referenceLap: 21,
                   other: 'b.duckdb', otherLap: 5 })
    const first = store.selectionKey
    store.select({ reference: 'a.duckdb', referenceLap: 2,
                   other: '1b.duckdb', otherLap: 5 })
    expect(store.selectionKey).not.toBe(first)
  })

  it('holds an ideal lap, and reports the reason one was refused', async () => {
    const store = useTelemetryStore()
    store.client.ideal = returns({ ideal_s: 101.212, sound: true, blocks: [], seams: [] })

    await store.loadIdeal('a.duckdb')
    expect(store.ideal.ideal_s).toBeCloseTo(101.212, 6)
    expect(store.error).toBeNull()

    // The refusal is the common answer for a recording with one usable lap,
    // so it has to land somewhere the view can show it.
    store.client.ideal = async () => {
      throw new Error("'a.duckdb' has 1 usable lap of 3.")
    }
    await store.loadIdeal('a.duckdb')
    expect(store.error).toMatch(/1 usable lap of 3/)
  })

  it('forgets the ideal lap when the store is reset', async () => {
    // Left behind, it would sit under a different recording's name - the same
    // fault the selectionKey watch exists to prevent for a comparison.
    const store = useTelemetryStore()
    store.client.ideal = returns({ ideal_s: 101.212, sound: true, blocks: [], seams: [] })
    await store.loadIdeal('a.duckdb')

    store.reset()
    expect(store.ideal).toBeNull()
  })
})
