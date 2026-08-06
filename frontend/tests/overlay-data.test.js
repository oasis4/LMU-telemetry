import { describe, expect, it } from 'vitest'

import { showData } from '../src/components/overlay-data.js'

/**
 * A stand-in for a uPlot instance in a cursor sync group.
 *
 * Its `setData` deliberately does *not* re-range x even when asked to, because
 * that is what the real one does once a scale is synced - measured in the
 * browser on the corner overlay: after stepping three corners the data read
 * 9406-9908 m while `scales.x` still read 5756-6242 m. A fake that re-ranged
 * on setData would let the bug through, which is the whole point of it not
 * doing so.
 */
function syncedChart(distance) {
  return {
    data: [distance],
    scales: { x: { min: distance[0], max: distance[distance.length - 1] } },
    setData(data, _resetScales) {
      this.data = data
    },
    setScale(name, { min, max }) {
      this.scales[name] = { min, max }
    },
  }
}

const range = (chart) => [chart.scales.x.min, chart.scales.x.max]

describe('showing a new stretch of lap in a synced chart', () => {
  it('moves the axis to the new stretch', () => {
    // The failure this exists for: the corner changed, the numbers changed,
    // and the charts went blank because they were still drawing the metres of
    // the corner they had been built on.
    const chart = syncedChart(Float64Array.from([5756, 5758, 6242]))
    showData(chart, [Float64Array.from([9406, 9408, 9908]), Float64Array.from([1, 2, 3])])
    expect(range(chart)).toEqual([9406, 9908])
  })

  it('hands the data to the chart as well', () => {
    const chart = syncedChart(Float64Array.from([0, 2, 4]))
    const data = [Float64Array.from([10, 12, 14]), Float64Array.from([1, 2, 3])]
    showData(chart, data)
    expect(chart.data).toBe(data)
  })

  it('spans exactly the data, so the run-up and run-off are both visible', () => {
    const chart = syncedChart(Float64Array.from([0, 2, 4]))
    const distance = Float64Array.from([100, 102, 104, 106])
    showData(chart, [distance, Float64Array.from([1, 2, 3, 4])])
    expect(range(chart)).toEqual([100, 106])
  })

  it('leaves the axis alone when there is nothing to show', () => {
    // An empty window would otherwise ask for a range of undefined to
    // undefined, and uPlot draws that as a blank chart with no axis at all.
    const chart = syncedChart(Float64Array.from([5756, 6242]))
    showData(chart, [Float64Array.from([]), Float64Array.from([])])
    expect(range(chart)).toEqual([5756, 6242])
  })
})
