/**
 * Putting a new stretch of lap into a chart that shares its cursor.
 *
 * `setData(data, true)` is documented to reset the scales, and for a lone
 * chart it does. It does not for a chart in a cursor sync group: uPlot takes
 * a synced scale out of auto-ranging, because a synced range is meant to be
 * driven from outside. Measured in the browser on the corner overlay - the
 * data moved to 9406-9908 m while `scales.x` stayed on 5756-6242 m, the
 * window of whichever corner was showing when the chart was built. Three
 * corners later the data was entirely outside the drawn range and the rows
 * were blank, with the axis still naming the old corner's metres.
 *
 * So the range is stated rather than inferred. The overlay always knows which
 * stretch it is showing - it is the window it just cut - and saying so
 * outright cannot be quietly ignored.
 */

/**
 * Show *data* in *chart*, with the x-axis spanning exactly the data's own
 * distances.
 *
 * @param {object} chart  a uPlot instance
 * @param {Array}  data   [distance, ...series], as uPlot takes it
 */
export function showData(chart, data) {
  chart.setData(data, true)
  const distance = data[0]
  if (!distance || distance.length === 0) return
  chart.setScale('x', { min: distance[0], max: distance[distance.length - 1] })
}
