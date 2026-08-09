<script setup>
/**
 * The circuit, split into the blocks an ideal lap was assembled from.
 *
 * Colour is categorical here - which lap this block was taken from - and that
 * is exactly why this is not a mode on TrackMap, whose header commits to
 * colour meaning time lost against time gained. Two meanings on one stroke is
 * the thing it says it will not do.
 *
 * Colour alone would fail a CVD reader, so each block carries the lap it came
 * from as a label. That number is the answer; the colour only groups.
 *
 * Seams are drawn only where they do not hold. A mark on every join would make
 * the mark mean "join" rather than "look at this one".
 */
import { computed } from 'vue'

import { pointAt, project, spanIndices } from './track-projection.js'

const props = defineProps({
  map: { type: Object, required: true },
  blocks: { type: Array, default: () => [] },
  seams: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  size: { type: Number, default: 560 },
})
const emit = defineEmits(['select'])

const frame = computed(() => project(props.map, props.size))

function toPoint(index) {
  return pointAt(props.map, frame.value, props.size, index)
}

function pathFrom(first, last) {
  const points = []
  for (let i = first; i < last; i += 1) points.push(toPoint(i))
  return points.length ? `M${points.join('L')}` : ''
}

const outline = computed(() => `${pathFrom(0, props.map.x.length)}Z`)

/**
 * Lap number -> a slot in the palette.
 *
 * Keyed on the sorted set of lap numbers rather than on the order blocks
 * happen to arrive in, so re-picking one block does not recolour the map.
 */
const lapSlots = computed(() => {
  const seen = [...new Set(props.blocks.map((b) => b.lap_number))].sort((a, b) => a - b)
  return Object.fromEntries(seen.map((lap, at) => [lap, at % 6]))
})

const blockPaths = computed(() =>
  props.blocks.map((block) => {
    const ranges = spanIndices(
      block.start_m, block.end_m, props.map.track_length_m, props.map.x.length,
    )
    const [first, last] = ranges[0]
    return {
      ...block,
      slot: lapSlots.value[block.lap_number] ?? 0,
      d: ranges.map(([a, b]) => pathFrom(a, b)).join(' '),
      // Placed in the first run. For the block holding the line that is the
      // run up to it, which is on the track rather than in the middle of the
      // box where a midpoint of the two runs would land.
      label: toPoint(Math.floor((first + last) / 2)).split(','),
    }
  }),
)

const badSeams = computed(() =>
  props.seams
    .filter((seam) => !seam.sound)
    .map((seam) => {
      const [[first]] = spanIndices(
        seam.at_m, seam.at_m, props.map.track_length_m, props.map.x.length,
      )
      return { ...seam, at: toPoint(first).split(',') }
    }),
)
</script>

<template>
  <svg
    :viewBox="`0 0 ${props.size} ${props.size}`"
    class="map"
    role="img"
    :aria-label="`${props.map.track} — ${props.blocks.length} blocks`"
  >
    <path :d="outline" class="outline" />

    <path
      v-for="block in blockPaths"
      :key="block.index"
      :d="block.d"
      class="block"
      :class="[`slot-${block.slot}`, { selected: block.index === props.selected }]"
      @mouseenter="emit('select', block)"
      @click="emit('select', block)"
    >
      <title>{{ block.name }} — lap {{ block.lap_number }}, {{ block.time_s.toFixed(3) }} s</title>
    </path>

    <text
      v-for="block in blockPaths"
      :key="`label-${block.index}`"
      :x="block.label[0]"
      :y="block.label[1]"
      class="label"
    >{{ block.lap_number }}</text>

    <circle
      v-for="(seam, at) in badSeams"
      :key="`seam-${at}`"
      :cx="seam.at[0]"
      :cy="seam.at[1]"
      r="6"
      class="seam-bad"
    >
      <title>
        the two laps were {{ seam.speed_spread_kmh.toFixed(1) }} km/h apart here
      </title>
    </circle>
  </svg>
</template>

<style scoped>
.map { width: 100%; height: auto; }
.outline { fill: none; stroke: var(--line); stroke-width: 1.5; }

.block {
  fill: none;
  stroke-width: 5;
  stroke-linecap: round;
  cursor: pointer;
  transition: stroke-width 0.12s ease;
}
.block.selected { stroke-width: 9; }

/* Grouping only - the lap number on the map is what actually says which. */
.slot-0 { stroke: #4c9be8; }
.slot-1 { stroke: #e8a33d; }
.slot-2 { stroke: #57c78a; }
.slot-3 { stroke: #b07fe0; }
.slot-4 { stroke: #e06c9f; }
.slot-5 { stroke: #46c4c4; }

.label {
  font-size: 0.72rem;
  font-weight: 700;
  fill: var(--ink);
  paint-order: stroke;
  stroke: var(--panel);
  stroke-width: 3;
  text-anchor: middle;
  dominant-baseline: middle;
  pointer-events: none;
}

.seam-bad { fill: none; stroke: var(--loss); stroke-width: 2.5; }
</style>
