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
 *
 * Two things can be asked of this map - where the time went, and where the
 * brakes went on - and it shows one at a time. Both at once would put two
 * meanings on the same stroke: the corner colouring already spends hue *and*
 * width on time lost, and braking laid over it would be read as part of that.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  map: { type: Object, required: true },
  losses: { type: Object, default: () => ({}) },
  /** { reference: [[from_m, to_m], ...], other: [...] }, measured server-side
   *  on the full trace - see the compare route on why not from the series. */
  braking: { type: Object, default: null },
  selected: { type: Number, default: null },
  size: { type: Number, default: 560 },
})
const emit = defineEmits(['select'])

const PADDING = 22
const NOISE_S = 0.02

const mode = ref('time')

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

/**
 * A distance range as a path along the drawn line.
 *
 * The line is thinned, so a metre maps onto it by the ratio of the two - and
 * the range is clamped rather than wrapped: a braking zone that crosses the
 * start/finish line arrives as two ranges from the server, because the grid
 * it was measured on ends there.
 */
function zonePath(from_m, to_m) {
  const perPoint = props.map.track_length_m / props.map.x.length
  const first = Math.max(0, Math.round(from_m / perPoint))
  const last = Math.min(props.map.x.length - 1, Math.round(to_m / perPoint))
  // One point is a dot, and `M x,y` alone draws nothing at all - so a zone
  // shorter than the map's own spacing is widened to the two points that
  // bracket it rather than silently disappearing.
  return pathFrom(first, Math.max(last + 1, first + 2))
}

/**
 * Both laps' zones, reference first.
 *
 * The order is the drawing order, and it is load-bearing rather than
 * incidental: both laps brake for the same corner, so their zones overlap
 * almost exactly, and the reference has to go down first and wider for the
 * compared lap to sit inside it as a core. Drawn the other way round the
 * reference vanished and the map showed one lap while claiming two.
 */
const brakingPaths = computed(() => {
  if (!props.braking) return []
  return ['reference', 'other'].flatMap((side) =>
    (props.braking[side] ?? []).map(([from_m, to_m], at) => ({
      key: `${side}-${at}`,
      side,
      d: zonePath(from_m, to_m),
      title: `${side === 'reference' ? 'reference' : 'compared'} — brakes at `
        + `${from_m.toFixed(0)} m for ${(to_m - from_m).toFixed(0)} m`,
      start: toPoint(
        Math.max(0, Math.round(from_m / (props.map.track_length_m / props.map.x.length))),
      ).split(','),
    })),
  )
})

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
  <div class="map-block">
    <div v-if="props.braking" class="modes" role="group" aria-label="what the map shows">
      <button type="button" :class="{ current: mode === 'time' }"
              @click="mode = 'time'">time lost</button>
      <button type="button" :class="{ current: mode === 'braking' }"
              @click="mode = 'braking'">braking</button>
    </div>

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
      :class="[mode === 'braking' ? 'quiet' : corner.tone,
               { selected: corner.index === props.selected }]"
      @mouseenter="emit('select', corner)"
      @click="emit('select', corner)"
    >
      <title>{{ title(corner) }}</title>
    </path>

    <template v-if="mode === 'braking'">
      <!-- In the order brakingPaths hands them over, which is where the
           reference-before-compared guarantee lives. -->
      <path v-for="zone in brakingPaths" :key="zone.key" :d="zone.d"
            class="braking" :class="zone.side">
        <title>{{ zone.title }}</title>
      </path>
      <circle v-for="zone in brakingPaths" :key="`dot-${zone.key}`"
              :cx="zone.start[0]" :cy="zone.start[1]" r="3.5"
              class="brake-start" :class="zone.side">
        <title>{{ zone.title }}</title>
      </circle>
    </template>

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
  </div>
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
/* In braking mode the corners stay clickable but say nothing about time -
 * the map is answering one question at a time. */
.corner.quiet { stroke: var(--level); stroke-width: 6; opacity: 0.5; }

/* Braking is weight on the circuit's own line. The reference is wider and
 * underneath so the two are still telling apart where both brake together. */
.braking { fill: none; stroke-linecap: butt; pointer-events: none; }
.braking.reference { stroke: var(--reference); stroke-width: 14; }
.braking.other { stroke: var(--compared); stroke-width: 7; }
.brake-start { pointer-events: none; }
.brake-start.reference { fill: var(--reference); }
.brake-start.other { fill: var(--compared); }

.map-block { display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
.modes { display: flex; gap: 0.3rem; }
.modes button {
  padding: 0.2rem 0.6rem;
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 0.76rem;
  color: var(--ink-secondary);
}
.modes button:hover { background: var(--hover); }
.modes button.current { background: var(--selected); color: var(--ink); border-color: var(--compared); }

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
