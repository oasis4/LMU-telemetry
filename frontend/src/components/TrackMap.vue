<script setup>
/**
 * The circuit, drawn from the line that was measured.
 *
 * Not reconstructed from corner radii and headings: that draws what the
 * detector believed rather than where the car went, and it then agrees with
 * the corner list however wrong both are.
 *
 * Colour carries polarity - lost time against gained - and that pair sits
 * inside the CVD band where colour alone is not enough. The second channel
 * here is stroke width: a corner that cost time is drawn thicker. The bars
 * beside the map carry the signed numbers.
 *
 * SVG rather than canvas: the whole path is at most ~1500 points, a corner is
 * a slice of it, and highlighting one is a class change rather than a redraw.
 */
import { computed } from 'vue'

const props = defineProps({
  map: { type: Object, required: true },
  losses: { type: Object, default: () => ({}) },
  selected: { type: Number, default: null },
  size: { type: Number, default: 560 },
})
const emit = defineEmits(['select'])

const PADDING = 22
const NOISE_S = 0.02

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
  // the shape of that circuit. Taking the larger extent also keeps it inside
  // the box when the circuit is taller than it is wide.
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
  // SVG's y grows downward; drawn without flipping, every circuit is mirrored.
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
  props.map.corners.map((corner) => {
    const lost = props.losses[corner.index] ?? null
    const tone =
      lost === null ? 'neutral' : lost > NOISE_S ? 'loss' : lost < -NOISE_S ? 'gain' : 'level'
    return {
      ...corner,
      lost,
      tone,
      d: corner.spans.map(([first, last]) => pathFrom(first, last)).join(' '),
    }
  }),
)

function labelPoint(corner) {
  const [first, last] = corner.spans[0]
  return toPoint(Math.floor((first + last) / 2)).split(',')
}

function title(corner) {
  if (corner.lost === null) return corner.name
  const sign = corner.lost >= 0 ? '+' : '−'
  return `${corner.name} — ${sign}${Math.abs(corner.lost).toFixed(3)} s`
}
</script>

<template>
  <svg
    :viewBox="`0 0 ${props.size} ${props.size}`"
    class="map"
    role="img"
    :aria-label="`${props.map.track} — ${props.map.corners.length} corners`"
  >
    <path :d="outline" class="outline" />

    <path
      v-for="corner in cornerPaths"
      :key="corner.index"
      :d="corner.d"
      class="corner"
      :class="[corner.tone, { selected: corner.index === props.selected }]"
      @mouseenter="emit('select', corner)"
      @click="emit('select', corner)"
    >
      <title>{{ title(corner) }}</title>
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

    <circle
      :cx="toPoint(0).split(',')[0]"
      :cy="toPoint(0).split(',')[1]"
      r="4.5"
      class="start"
    />
    <title>start / finish</title>
  </svg>
</template>

<style scoped>
.map { width: 100%; height: auto; display: block; }

.outline {
  fill: none;
  stroke: var(--axis);
  stroke-width: 6;
  stroke-linejoin: round;
}

.corner {
  fill: none;
  stroke-linecap: round;
  cursor: pointer;
  transition: stroke-width 0.12s ease;
}
/* Stroke width is the second channel beside hue: a corner that cost time is
 * drawn heavier, so the polarity survives colour-vision deficiency. */
.corner.neutral { stroke: var(--level); stroke-width: 6; }
.corner.level { stroke: var(--level); stroke-width: 6; }
.corner.gain { stroke: var(--gain); stroke-width: 6; }
.corner.loss { stroke: var(--loss); stroke-width: 10; }
.corner.selected { stroke-width: 13; }

.labels text {
  font-size: 10px;
  font-weight: 600;
  fill: var(--ink-secondary);
  text-anchor: middle;
  dominant-baseline: middle;
  pointer-events: none;
}
.labels text.selected { fill: var(--accent); }

.start { fill: var(--accent); }
</style>
