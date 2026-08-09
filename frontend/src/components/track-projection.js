/**
 * Putting a measured circuit into a square box.
 *
 * Lifted out of TrackMap so BlockMap can draw the same circuit the same way.
 * Two components each with their own copy of this would drift, and the drift
 * would look like the two maps disagreeing about the track.
 */

const PADDING = 22

/** Bounds and scale for `map`, drawn into a `size` by `size` box. */
export function project(map, size) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (let i = 0; i < map.x.length; i += 1) {
    if (map.x[i] < minX) minX = map.x[i]
    if (map.x[i] > maxX) maxX = map.x[i]
    if (map.y[i] < minY) minY = map.y[i]
    if (map.y[i] > maxY) maxY = map.y[i]
  }
  const width = maxX - minX || 1
  const height = maxY - minY || 1
  // One scale for both axes: a circuit stretched to fill a box is no longer
  // the shape of that circuit. Taking the larger extent also keeps it inside
  // the box when the circuit is taller than it is wide.
  const scale = (size - 2 * PADDING) / Math.max(width, height)
  return {
    minX, minY, scale,
    offsetX: PADDING + (size - 2 * PADDING - width * scale) / 2,
    offsetY: PADDING + (size - 2 * PADDING - height * scale) / 2,
  }
}

/** One point as `"x,y"`, ready for an SVG path. */
export function pointAt(map, frame, size, index) {
  const px = frame.offsetX + (map.x[index] - frame.minX) * frame.scale
  // SVG's y grows downward; drawn without flipping, every circuit is mirrored.
  const py = size - (frame.offsetY + (map.y[index] - frame.minY) * frame.scale)
  return `${px.toFixed(1)},${py.toFixed(1)}`
}

/**
 * A distance range as index ranges into the drawn points.
 *
 * Comes back as two ranges when the span holds the start/finish line, which is
 * `fromM > toM` - the run to the line and the run away from it. Read as one
 * range it is empty and the block vanishes from the map with nothing saying
 * so. This is the same split `api.corner_spans` makes server-side, for the
 * same reason.
 *
 * TrackMap's own `zonePath` clamps instead of splitting, and is right to: the
 * server hands it braking zones already cut at the line, because the grid they
 * were measured on ends there. A block arrives whole.
 */
export function spanIndices(fromM, toM, trackLengthM, pointCount) {
  const perPoint = trackLengthM / pointCount
  const edges = fromM <= toM
    ? [[fromM, toM]]
    : [[fromM, trackLengthM], [0, toM]]
  return edges.map(([firstM, lastM]) => {
    const first = Math.min(Math.max(0, Math.round(firstM / perPoint)), pointCount - 1)
    const last = Math.min(Math.max(Math.round(lastM / perPoint), first + 1), pointCount)
    return [first, last]
  })
}
