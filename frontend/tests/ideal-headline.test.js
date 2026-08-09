import { describe, expect, it } from 'vitest'

import { headlineFor } from '../src/components/ideal-headline.js'

const SOUND = {
  ideal_s: 101.212, best_lap_s: 101.271, gain_s: 0.059, sound: true,
  seams: [
    { at_m: 0, speed_spread_kmh: 3.1, sound: true },
    { at_m: 900, speed_spread_kmh: 1.6, sound: true },
  ],
}

/** Monza, the largest gain in the sampled corpus - and 20 km/h at one join. */
const UNSOUND = {
  ideal_s: 99.5, best_lap_s: 100.936, gain_s: 1.436, sound: false,
  seams: [
    { at_m: 0, speed_spread_kmh: 2.0, sound: true },
    { at_m: 1500, speed_spread_kmh: 20.0, sound: false },
    { at_m: 3000, speed_spread_kmh: 6.2, sound: false },
  ],
}

describe('headlineFor', () => {
  it('passes the numbers through when every join holds', () => {
    const headline = headlineFor(SOUND)
    expect(headline.qualified).toBe(false)
    expect(headline.gainS).toBeCloseTo(0.059, 6)
    expect(headline.worstSeam).toBeNull()
  })

  it('marks the headline unsupported when one join does not hold', () => {
    // core/blocks.py: `sound` is an all() and not a count, because one join
    // that does not hold makes the whole time a claim the laps do not support.
    expect(headlineFor(UNSOUND).qualified).toBe(true)
  })

  it('names the worst join, not merely the first bad one', () => {
    // The first is wherever the lap happens to start. The driver needs the
    // join that costs the claim the most.
    const headline = headlineFor(UNSOUND)
    expect(headline.worstSeam.speed_spread_kmh).toBe(20.0)
    expect(headline.worstSeam.at_m).toBe(1500)
  })

  it('still carries the numbers, so the table can show them', () => {
    // Qualified, not hidden. A driver who wants the figure can have it; what
    // they must not get is the figure without the doubt attached.
    const headline = headlineFor(UNSOUND)
    expect(headline.gainS).toBeCloseTo(1.436, 6)
    expect(headline.idealS).toBeCloseTo(99.5, 6)
  })

  it('trusts the served flag rather than recounting the seams', () => {
    // The server computes `sound` with SEAM_SPEED_KMH and sends the limit so
    // the two cannot disagree. Deriving it again here would be a second
    // opinion, and one day a differing one.
    const contradictory = { ...SOUND, sound: false }
    expect(headlineFor(contradictory).qualified).toBe(true)
  })

  it('is safe before anything has loaded', () => {
    expect(headlineFor(null).qualified).toBe(false)
    expect(headlineFor(null).idealS).toBeNull()
  })

  it('does not claim a bad join when the seam list is missing', () => {
    // A payload without seams is not a payload with sound ones.
    const headline = headlineFor({ ideal_s: 1, best_lap_s: 2, gain_s: 1, sound: true })
    expect(headline.worstSeam).toBeNull()
    expect(headline.qualified).toBe(false)
  })
})
