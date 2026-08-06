/**
 * The stretch of a lap a corner is read over, and how to put a distance on it.
 *
 * A lap's grid runs 0 .. length and then stops. A corner near the start/finish
 * line has its run-up on the other side of that seam, so the window has to be
 * cut in two pieces and joined - and once joined, the axis has to keep
 * increasing or every chart on it draws a fold-back. That means distances
 * quoted against the lap (a brake point, the corner's own edges) have to be
 * moved onto the same unwrapped axis, or a marker at 120 m lands 5 km from
 * the line it belongs to.
 *
 * This is arithmetic with an off-by-a-lap failure mode that looks like a
 * plausible picture, which is why it is a function with tests rather than a
 * closure inside the component.
 */

/**
 * @param {Float64Array} distance  the lap's own distance grid, evenly spaced
 * @param {number} startM  where the corner begins
 * @param {number} endM    where it ends (may be < startM if it spans the line)
 * @param {number} approachM  how much run-up and run-off to include
 * @returns {{axis: Float64Array, take: Function, unwrap: Function, wraps: boolean}}
 */
export function cornerWindow(distance, startM, endM, approachM) {
  const step = distance[1] - distance[0]
  const lapLength = distance[distance.length - 1] + step
  const index = (m) => Math.round((((m % lapLength) + lapLength) % lapLength) / step)

  const first = index(startM - approachM)
  const last = index(endM + approachM)
  const wraps = first > last

  const take = (values) =>
    !values
      ? null
      : wraps
        ? Float64Array.from([
            ...values.slice(first, distance.length),
            ...values.slice(0, last),
          ])
        : values.slice(first, last)

  const axis = Float64Array.from(take(distance))
  for (let i = 1; i < axis.length; i += 1) {
    if (axis[i] < axis[i - 1]) axis[i] += lapLength
  }

  // Anything before the window's own start is a metre on the far side of the
  // seam, so it belongs a lap further along.
  const unwrap = (m) =>
    m === null || m === undefined ? null : m < axis[0] ? m + lapLength : m

  return { axis, take, unwrap, wraps }
}
