<script setup>
/**
 * The circuit, drawn from the line that was measured.
 *
 * Not reconstructed from corner radii and headings: that draws what the
 * detector believed rather than where the car went, and it then agrees with
 * the corner list however wrong both are. The points come from the same median
 * line the corners were detected on.
 *
 * SVG rather than a canvas. The whole path is at most ~1500 points, a corner
 * is a slice of it, and hovering one has to highlight it - which is a class
 * change on an element in SVG and a full redraw on a canvas.
 */
import { computed } from 'vue'

const props = defineProps({
  map: { type: Object, required: true },       // { x, y, corners, ... }
  losses: { type: Object, default: () => ({}) }, // corner index -> seconds lost
  selected: { type: Number, default: null },
  size: { type: Number, default: 520 },
})
const emit = defineEmits(['select'])

const PADDING = 12

const frame = computed(() => {
  const { x, y } = props.map
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (let i = 0; i < x.length; i += 1) {
    if (x[i] < minX) minX = x[i]
    if (x[i] > maxX) maxX = x[i]
    if (y[i] < minY) minY = y[i]
    if (y[i] > maxY) maxY = y[i]
  }
  const width = maxX - minX || 1
  const height = maxY - minY || 1
  // One scale for both axes: a circuit stretched to fill a box is no longer
  // the shape of that circuit.
  const scale = (props.size - 2 * PADDING) / Math.max(width, height)
  return {
    minX, minY, scale,
    offsetX: PADDING + (props.size - 2 * PADDING - width * scale) / 2,
    offsetY: PADDING + (props.size - 2 * PADDING - height * scale) / 2,
  }
})

function toPoint(index) {
  const { minX, minY, scale, offsetX, offsetY } = frame.value
  const px = offsetX + (props.map.x[index] - minX) * scale
  // SVG's y grows downward; a circuit drawn without flipping it is mirrored.
  const py = props.size - (offsetY + (props.map.y[index] - minY) * scale)
  return `${px.toFixed(1)},${py.toFixed(1)}`
}

function pathFrom(first, last) {
  const points = []
  for (let i = first; i < last; i += 1) points.push(toPoint(i))
  return points.length ? `M${points.join('L')}` : ''
}

const outline = computed(() => `${pathFrom(0, props.map.x.length)}Z`)

const cornerPaths = computed(() =>
  props.map.corners.map((corner) => ({
    ...corner,
    lost: props.losses[corner.index] ?? null,
    d: corner.spans.map(([first, last]) => pathFrom(first, last)).join(' '),
  })),
)

function labelPoint(corner) {
  const [first, last] = corner.spans[0]
  return toPoint(Math.floor((first + last) / 2)).split(',')
}

function tone(lost) {
  if (lost === null) return 'neutral'
  if (lost > 0.05) return 'loss'
  if (lost < -0.05) return 'gain'
  return 'level'
}
</script>

<template>
  <svg :viewBox="`0 0 ${props.size} ${props.size}`" class="map" role="img"
       :aria-label="`${props.map.track} — ${props.map.corners.length} corners`">
    <path :d="outline" class="outline" />

    <path
      v-for="corner in cornerPaths"
      :key="corner.index"
      :d="corner.d"
      class="corner"
      :class="[tone(corner.lost), { selected: corner.index === props.selected }]"
      @mouseenter="emit('select', corner)"
      @click="emit('select', corner)"
    >
      <title>
        {{ corner.name }}{{ corner.lost === null ? ''
          : ` — ${corner.lost >= 0 ? '+' : '−'}${Math.abs(corner.lost).toFixed(3)} s` }}
      </title>
    </path>

    <g class="labels">
      <text
        v-for="corner in cornerPaths"
        :key="`label-${corner.index}`"
        :x="labelPoint(corner)[0]"
        :y="labelPoint(corner)[1]"
        :class="{ selected: corner.index === props.selected }"
      >{{ corner.index }}</text>
    </g>

    <circle :cx="toPoint(0).split(',')[0]" :cy="toPoint(0).split(',')[1]" r="4"
            class="start" />
  </svg>
</template>

<style scoped>
.map { width: 100%; height: auto; max-width: 520px; display: block; }
.outline { fill: none; stroke: var(--line); stroke-width: 7; stroke-linejoin: round; }
.corner {
  fill: none;
  stroke-width: 7;
  stroke-linecap: round;
  cursor: pointer;
  transition: stroke-width 0.1s;
}
.corner.neutral { stroke: #5b6472; }
.corner.level { stroke: #5b6472; }
.corner.loss { stroke: var(--loss); }
.corner.gain { stroke: var(--gain); }
.corner.selected { stroke-width: 12; }
.labels text {
  font-size: 10px;
  fill: var(--muted);
  text-anchor: middle;
  dominant-baseline: middle;
  pointer-events: none;
}
.labels text.selected { fill: var(--accent); font-weight: 700; }
.start { fill: var(--accent); }
</style>
