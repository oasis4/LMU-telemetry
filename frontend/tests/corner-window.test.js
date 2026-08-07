import { describe, expect, it } from 'vitest'

import { cornerWindow } from '../src/components/corner-window.js'

/** A 1000 m lap on a 2 m grid: 500 points, 0, 2, 4 .. 998. */
const grid = Float64Array.from({ length: 500 }, (_, i) => i * 2)

describe('the window a corner is read over', () => {
  it('covers the corner and the run-up on both sides', () => {
    const { axis, wraps } = cornerWindow(grid, 400, 500, 100)
    expect(wraps).toBe(false)
    expect(axis[0]).toBe(300)
    expect(axis[axis.length - 1]).toBe(598)
  })

  it('takes any channel over the same stretch', () => {
    const speed = grid.map((m) => m / 10)
    const { axis, take } = cornerWindow(grid, 400, 500, 100)
    const taken = take(speed)
    expect(taken).toHaveLength(axis.length)
    expect(taken[0]).toBe(30)
  })

  it('reports a missing channel as missing rather than as an empty line', () => {
    const { take } = cornerWindow(grid, 400, 500, 100)
    expect(take(undefined)).toBeNull()
  })

  describe('for a corner whose run-up is on the far side of the line', () => {
    // Turn 1 at 50-150 m with a 100 m approach starts at -50 m, which is
    // 950 m: the window is cut at the seam and joined.
    const window = () => cornerWindow(grid, 50, 150, 100)

    it('joins the two pieces into one stretch', () => {
      const { axis, wraps } = window()
      expect(wraps).toBe(true)
      expect(axis[0]).toBe(950)
      expect(axis).toHaveLength(150) // 50 points before the line, 100 after
    })

    it('keeps the axis increasing across the seam', () => {
      const { axis } = window()
      for (let i = 1; i < axis.length; i += 1) {
        expect(axis[i]).toBeGreaterThan(axis[i - 1])
      }
      expect(axis[axis.length - 1]).toBe(1248) // 248 m, a lap on
    })

    it('moves a distance quoted against the lap onto that axis', () => {
      // Without this a brake point at 20 m is drawn at 20 m - 930 m before
      // the window it belongs to, which reads as no marker at all.
      const { unwrap, axis } = window()
      expect(unwrap(20)).toBe(1020)
      expect(unwrap(20)).toBeGreaterThan(axis[0])
      expect(unwrap(20)).toBeLessThan(axis[axis.length - 1])
    })

    it('leaves a distance already inside the window alone', () => {
      const { unwrap } = window()
      expect(unwrap(970)).toBe(970)
    })

    it('has nothing to say about a metric the lap does not have', () => {
      const { unwrap } = window()
      expect(unwrap(null)).toBeNull()
      expect(unwrap(undefined)).toBeNull()
    })
  })
})
