import { describe, expect, it } from 'vitest'

import { project, pointAt, spanIndices } from '../src/components/track-projection.js'

const SQUARE = { x: [0, 100, 100, 0], y: [0, 0, 100, 100] }

describe('project', () => {
  it('uses one scale for both axes, so a circuit keeps its shape', () => {
    const wide = { x: [0, 200, 0], y: [0, 0, 50] }
    const frame = project(wide, 560)
    // A separate scale per axis would stretch this to fill the box.
    expect(frame.scale).toBeCloseTo((560 - 44) / 200, 6)
  })

  it('centres what it draws inside the box', () => {
    const frame = project(SQUARE, 560)
    expect(frame.offsetX).toBeCloseTo(frame.offsetY, 6)
  })

  it('survives a degenerate extent rather than dividing by zero', () => {
    const frame = project({ x: [5, 5], y: [7, 7] }, 560)
    expect(Number.isFinite(frame.scale)).toBe(true)
  })
})

describe('pointAt', () => {
  it('flips y, because SVG grows downward and a circuit would be mirrored', () => {
    const frame = project(SQUARE, 560)
    const bottom = pointAt(SQUARE, frame, 560, 0)   // y = 0, the lowest point
    const top = pointAt(SQUARE, frame, 560, 2)      // y = 100, the highest
    expect(Number(bottom.split(',')[1])).toBeGreaterThan(Number(top.split(',')[1]))
  })
})

describe('spanIndices', () => {
  it('maps a plain range onto the drawn points', () => {
    // 1000 m of track over 100 points: 10 m each.
    expect(spanIndices(200, 400, 1000, 100)).toEqual([[20, 40]])
  })

  it('splits a span that holds the start/finish line into two', () => {
    // A block from 900 m round to 100 m is the end of the lap and its start.
    // Read as one range it is empty, and the block would vanish from the map
    // with nothing saying so.
    expect(spanIndices(900, 100, 1000, 100)).toEqual([[90, 100], [0, 10]])
  })

  it('never returns an empty range, which would draw nothing at all', () => {
    // Shorter than the spacing between two drawn points.
    const [[first, last]] = spanIndices(200, 201, 1000, 100)
    expect(last).toBeGreaterThan(first)
  })

  it('stays inside the array it will be used to index', () => {
    for (const [first, last] of spanIndices(995, 5, 1000, 100)) {
      expect(first).toBeGreaterThanOrEqual(0)
      expect(last).toBeLessThanOrEqual(100)
    }
  })
})
