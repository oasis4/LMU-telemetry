<script setup>
/**
 * One corner, zoomed, with both laps' own paths on it.
 *
 * The track's edges are not drawn. `Track Edge` and `Path Lateral` are both
 * recorded, and it looked as though a ribbon could be built from them - but
 * measured across laps, `Path Lateral - Track Edge` varies from lap to lap
 * exactly as much as `Path Lateral` alone (0.44 m against 0.43 m at
 * Silverstone), so it is not the track's half width. Drawing a ribbon anyway
 * would be a guess dressed as a measurement.
 *
 * What is drawn is measured: the reference line the corners were detected on,
 * and where each lap actually put the car.
 */
import { computed } from 'vue'

const props = defineProps({
  map: { type: Object, required: true },        // { x, y, corners, track_length_m }
  corner: { type: Object, required: true },     // the corner in focus
  reference: { type: Object, default: null },   // { x, y } on the same grid
  other: { type: Object, default: null },
  approachM: { type: Number, default: 150 },
  size: { type: Number, default: 420 },
})

const PADDING = 26

/** Grid indices covering the corner and its approach, wrapping if needed. */
const window = computed(() => {
  const total = props.map.x.length
  const perPoint = props.map.track_length_m / total
  const first = Math.round(((props.corner.start_m - props.approachM) % props.map.track_length_m
    + props.map.track_length_m) % props.map.track_length_m / perPoint)
  const last = Math.round(((props.corner.end_m + props.approachM) % props.map.track_length_m
    + props.map.track_length_m) % props.map.track_length_m / perPoint)
  const indices = []
  if (first <= last) {
    for (let i = first; i <= last; i += 1) indices.push(i)
  } else {
    for (let i = first; i < total; i += 1) indices.push(i)
    for (let i = 0; i <= last; i += 1) indices.push(i)
  }
  return indices
})

/** The frame is fixed by the reference line's extent over this window, so the
 *  two laps are drawn against the same box and their offset is readable. */
const frame = computed(() => {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const i of window.value) {
    const x = props.map.x[i]
    const y = props.map.y[i]
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  const width = maxX - minX || 1
  const height = maxY - minY || 1
  const scale = (props.size - 2 * PADDING) / Math.max(width, height)
  return {
    minX, minY, scale,
    offsetX: PADDING + (props.size - 2 * PADDING - width * scale) / 2,
    offsetY: PADDING + (props.size - 2 * PADDING - height * scale) / 2,
  }
})

function project(x, y) {
  const f = frame.value
  return [
    f.offsetX + (x - f.minX) * f.scale,
    // SVG's y grows downward; unflipped, every circuit is mirrored.
    props.size - (f.offsetY + (y - f.minY) * f.scale),
  ]
}

function pathOf(source, sampleAt) {
  if (!source) return ''
  const points = []
  for (const i of window.value) {
    const index = sampleAt ? sampleAt(i) : i
    const x = source.x[index]
    const y = source.y[index]
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    points.push(project(x, y).map((v) => v.toFixed(1)).join(','))
  }
  return points.length ? `M${points.join('L')}` : ''
}

/** The map is thinned; a lap trace is not. Both index by distance, so a map
 *  index maps onto a lap index by the ratio of their lengths. */
function lapIndexer(lapPath) {
  if (!lapPath) return null
  const ratio = lapPath.x.length / props.map.x.length
  return (i) => Math.min(Math.round(i * ratio), lapPath.x.length - 1)
}

const referencePath = computed(() => pathOf(props.reference, lapIndexer(props.reference)))
const otherPath = computed(() => pathOf(props.other, lapIndexer(props.other)))
const modelPath = computed(() => pathOf(props.map, null))

/** Where the apex sits on the drawn line, or null if it cannot be placed.
 *
 *  Checked once, on the result. The comparison's corners carried no `apex_m`,
 *  and `undefined` divided by a metres-per-point stayed a number-shaped
 *  nothing all the way to `<circle cx="NaN">` - an attribute the browser
 *  rejects and then ignores, so the marker simply was not there and nothing
 *  said why. Guarding the input as well would read better and test worse:
 *  either guard alone covers every case, so neither could be shown to matter.
 */
const apexPoint = computed(() => {
  const perPoint = props.map.track_length_m / props.map.x.length
  const index = Math.min(Math.round(props.corner.apex_m / perPoint), props.map.x.length - 1)
  const point = project(props.map.x[index], props.map.y[index])
  return point.every(Number.isFinite) ? point : null
})
</script>

<template>
  <svg :viewBox="`0 0 ${props.size} ${props.size}`" class="corner-map" role="img"
       :aria-label="`${props.corner.name}, both laps' paths`">
    <path :d="modelPath" class="reference-line" />
    <path v-if="referencePath" :d="referencePath" class="lap reference" />
    <path v-if="otherPath" :d="otherPath" class="lap other" />
    <template v-if="apexPoint">
      <circle :cx="apexPoint[0]" :cy="apexPoint[1]" r="3.5" class="apex" />
      <text :x="apexPoint[0]" :y="apexPoint[1] - 9" class="apex-label">apex</text>
    </template>
  </svg>
</template>

<style scoped>
.corner-map { width: 100%; height: auto; display: block; }

/* The circuit's own line, recessive: it is the context, not the comparison. */
.reference-line {
  fill: none;
  stroke: var(--axis);
  stroke-width: 9;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.lap { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.lap.reference { stroke: var(--reference); stroke-width: 2; }
.lap.other { stroke: var(--compared); stroke-width: 2.5; }
.apex { fill: var(--accent); }
.apex-label {
  font-size: 9px;
  fill: var(--ink-muted);
  text-anchor: middle;
}
</style>
