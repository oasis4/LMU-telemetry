<script setup>
/**
 * One corner at a time: step through them, see only that one.
 *
 * The whole-lap view answers "where did the time go". This answers "what
 * happened here", which is a different question and deserves its own screen
 * rather than a row in a table.
 *
 * The traces are stacked on one distance axis rather than tabbed. A corner is
 * one event - brake, minimum speed, throttle, and the delta that follows from
 * them - and reading it as one event means the rows have to share an x and a
 * crosshair. Tabs made each channel a separate look and hid exactly the
 * relationship the page is about.
 *
 * Each lap's brake point is drawn as a rule through every row, in that lap's
 * own colour. It is the first thing to look at in a corner, so it is drawn
 * rather than only listed.
 */
import { computed, ref, watch } from 'vue'

import CornerMap from './CornerMap.vue'
import OverlayChart from './OverlayChart.vue'
import { SERIES } from './chart-theme.js'
import { cornerWindow } from './corner-window.js'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  comparison: { type: Object, required: true },
  map: { type: Object, default: null },
  index: { type: Number, required: true },
  approachM: { type: Number, default: 200 },
})
const emit = defineEmits(['step'])

const store = useTelemetryStore()
const detail = ref(null)
const paths = ref({ reference: null, other: null })
const loading = ref(false)
const failure = ref(null)

const SYNC = 'corner-overlay'

const corner = computed(() => props.comparison.corners[props.index] ?? null)
const advice = computed(() =>
  (props.comparison.advice ?? []).filter((a) => a.corner === corner.value?.index),
)
const labels = computed(() => ({
  reference: `lap ${props.comparison.reference.lap}`,
  other: `lap ${props.comparison.other.lap}`,
}))

/** The full-resolution trace over this corner plus its run-up and run-off. */
const slice = computed(() => {
  if (!detail.value || !corner.value) return null
  const series = detail.value.series
  return {
    ...cornerWindow(
      series.distance_m, corner.value.start_m, corner.value.end_m, props.approachM,
    ),
    series,
  }
})

/** The corner itself, as a band on the unwrapped axis. */
const bands = computed(() => {
  if (!slice.value || !corner.value) return []
  return [{
    from: slice.value.unwrap(corner.value.start_m),
    to: slice.value.unwrap(corner.value.end_m),
  }]
})

function rules(metric) {
  if (!slice.value || !corner.value) return []
  return [
    { at: slice.value.unwrap(corner.value.reference[metric]), stroke: SERIES.reference },
    { at: slice.value.unwrap(corner.value.other[metric]), stroke: SERIES.compared },
  ]
}
const brakeRules = computed(() => rules('brake_point_m'))
const throttleRules = computed(() => rules('throttle_point_m'))

const speed = (v) => (v == null ? '--' : `${v.toFixed(1)} km/h`)
const pedal = (v) => (v == null ? '--' : `${(v * 100).toFixed(0)} %`)
const deltaValue = (v) =>
  v == null ? '--' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(3)} s`

/** The four rows of the overlay, in the order a corner happens. */
const rows = computed(() => {
  if (!slice.value) return []
  const s = slice.value.series
  const take = slice.value.take
  const pair = (referenceKey, otherKey, format) => [
    { values: take(s[referenceKey]), label: labels.value.reference,
      stroke: SERIES.reference, width: 1.5, format },
    { values: take(s[otherKey]), label: labels.value.other,
      stroke: SERIES.compared, width: 2, format },
  ]
  return [
    {
      key: 'delta',
      yLabel: 'delta (s)',
      height: 120,
      zero: true,
      markers: brakeRules.value,
      series: [{ values: take(s.delta_s), label: 'delta', stroke: '#d7dbe2',
                 width: 1.75, format: deltaValue }],
    },
    {
      key: 'speed',
      yLabel: 'speed (km/h)',
      height: 180,
      markers: brakeRules.value,
      series: pair('speed_reference_kmh', 'speed_other_kmh', speed),
    },
    {
      key: 'brake',
      yLabel: 'brake',
      height: 110,
      yRange: [0, 1],
      markers: brakeRules.value,
      series: pair('brake_reference', 'brake_other', pedal),
    },
    {
      key: 'throttle',
      yLabel: 'throttle',
      height: 110,
      yRange: [0, 1],
      markers: throttleRules.value,
      series: pair('throttle_reference', 'throttle_other', pedal),
    },
  // A row whose channel the server did not send is dropped, not drawn empty:
  // an axis with no line on it says the lap had none.
  ].filter((row) => row.series.every((s) => s.values))
})

/** Only the bottom row spends the height on naming the shared x-axis. */
const rowsWithAxis = computed(() =>
  rows.value.map((row, at) => ({ ...row, axis: at === rows.value.length - 1 })),
)

async function load() {
  loading.value = true
  failure.value = null
  try {
    const { reference, other } = props.comparison
    const [full, referencePath, otherPath] = await Promise.all([
      store.client.compare({
        reference: reference.name, referenceLap: reference.lap,
        other: other.name, otherLap: other.lap, full: true,
      }),
      store.client.trace(reference.name, reference.lap, { full: true }),
      store.client.trace(other.name, other.lap, { full: true }),
    ])
    detail.value = full
    paths.value = {
      reference: referencePath.series.x
        ? { x: referencePath.series.x, y: referencePath.series.y }
        : null,
      other: otherPath.series.x
        ? { x: otherPath.series.x, y: otherPath.series.y }
        : null,
    }
  } catch (cause) {
    failure.value = cause.message ?? String(cause)
  } finally {
    loading.value = false
  }
}

watch(
  () => [
    props.comparison.reference.name, props.comparison.reference.lap,
    props.comparison.other.name, props.comparison.other.lap,
  ],
  () => {
    detail.value = null
    load()
  },
  { immediate: true },
)

function metres(value) {
  return value === null || value === undefined ? '—' : `${value.toFixed(0)} m`
}
function difference(a, b, unit, digits) {
  if (a === null || b === null || a === undefined || b === undefined) return '—'
  return `${b - a >= 0 ? '+' : '−'}${Math.abs(b - a).toFixed(digits)} ${unit}`
}

const numbers = computed(() => {
  if (!corner.value) return []
  const r = corner.value.reference
  const o = corner.value.other
  return [
    ['brake point', metres(r.brake_point_m), metres(o.brake_point_m),
      difference(r.brake_point_m, o.brake_point_m, 'm', 0)],
    ['entry speed', `${r.entry_speed_kmh.toFixed(1)} km/h`, `${o.entry_speed_kmh.toFixed(1)} km/h`,
      difference(r.entry_speed_kmh, o.entry_speed_kmh, 'km/h', 1)],
    ['minimum speed', `${r.min_speed_kmh.toFixed(1)} km/h`, `${o.min_speed_kmh.toFixed(1)} km/h`,
      difference(r.min_speed_kmh, o.min_speed_kmh, 'km/h', 1)],
    ['throttle point', metres(r.throttle_point_m), metres(o.throttle_point_m),
      difference(r.throttle_point_m, o.throttle_point_m, 'm', 0)],
    ['exit speed', `${r.exit_speed_kmh.toFixed(1)} km/h`, `${o.exit_speed_kmh.toFixed(1)} km/h`,
      difference(r.exit_speed_kmh, o.exit_speed_kmh, 'km/h', 1)],
  ]
})
</script>

<template>
  <section v-if="corner" class="card focus">
    <header class="stepper">
      <button type="button" class="step" :disabled="props.index === 0"
              aria-label="previous corner" @click="emit('step', -1)">‹</button>
      <div class="title">
        <h2>{{ corner.name }}</h2>
        <p class="muted num">
          corner {{ props.index + 1 }} of {{ props.comparison.corners.length }} ·
          {{ corner.start_m.toFixed(0) }}–{{ corner.end_m.toFixed(0) }} m
        </p>
      </div>
      <p class="cost num" :class="corner.lost_s > 0.02 ? 'loss' : corner.lost_s < -0.02 ? 'gain' : ''">
        {{ corner.lost_s >= 0 ? '+' : '−' }}{{ Math.abs(corner.lost_s).toFixed(3) }} s
      </p>
      <button type="button" class="step"
              :disabled="props.index >= props.comparison.corners.length - 1"
              aria-label="next corner" @click="emit('step', 1)">›</button>
    </header>

    <p v-if="failure" class="failure">{{ failure }}</p>

    <div class="body">
      <div class="left">
        <CornerMap
          v-if="props.map && slice"
          :map="props.map"
          :corner="corner"
          :reference="paths.reference"
          :other="paths.other"
          :approach-m="props.approachM"
        />
        <p v-else-if="loading" class="muted">reading this corner…</p>

        <table class="numbers">
          <thead>
            <tr><th></th><th class="num">reference</th><th class="num">compared</th><th class="num">difference</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in numbers" :key="row[0]">
              <td>{{ row[0] }}</td>
              <td class="num muted">{{ row[1] }}</td>
              <td class="num">{{ row[2] }}</td>
              <td class="num strong">{{ row[3] }}</td>
            </tr>
          </tbody>
        </table>

        <ul v-if="advice.length" class="advice">
          <li v-for="tip in advice" :key="tip.headline">
            <p class="headline">{{ tip.headline }}</p>
            <p class="detail muted">{{ tip.detail }}</p>
            <p class="because num">{{ tip.because }}</p>
          </li>
        </ul>
        <p v-else-if="!loading" class="muted no-advice">
          The measurements here do not agree on one story, so there is no tip —
          the numbers above are what this corner actually says.
        </p>
      </div>

      <div class="right">
        <div v-if="slice" class="stack">
          <OverlayChart
            v-for="row in rowsWithAxis"
            :key="row.key"
            :distance="slice.axis"
            :series="row.series"
            :bands="bands"
            :markers="row.markers"
            :y-label="row.yLabel"
            :y-range="row.yRange ?? null"
            :zero="row.zero ?? false"
            :height="row.height"
            :show-axis="row.axis ?? false"
            :sync-key="SYNC"
          />
        </div>
        <p v-else class="muted">reading this corner…</p>

        <p v-if="slice" class="muted resolution">
          Shaded: the corner. Vertical rules: each lap's brake point, and on
          the throttle row where it picked the power up. {{ slice.axis.length }}
          points over
          {{ (slice.axis[slice.axis.length - 1] - slice.axis[0]).toFixed(0) }} m.
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.focus { display: flex; flex-direction: column; gap: 0.9rem; }

.stepper { display: flex; align-items: center; gap: 0.9rem; margin-bottom: 0; }
.step {
  width: 32px; height: 32px;
  border: 1px solid var(--line);
  border-radius: 6px;
  font-size: 1.1rem;
  line-height: 1;
  color: var(--ink-secondary);
  flex-shrink: 0;
}
.step:hover:not(:disabled) { background: var(--hover); color: var(--ink); }
.step:disabled { opacity: 0.35; cursor: default; }
.title { min-width: 0; }
.title h2 { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.title p { font-size: 0.78rem; }
.cost { margin-left: auto; font-size: 1.3rem; font-weight: 700; }
.cost.loss { color: var(--loss); }
.cost.gain { color: var(--gain); }

.body { display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 1.2rem; }
.left, .right { min-width: 0; display: flex; flex-direction: column; gap: 0.7rem; }

/* The rows are one picture, so they sit against each other rather than as
 * four cards with air between them. */
.stack { display: flex; flex-direction: column; }

.advice { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }
.advice li {
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 0.5rem 0.7rem;
  background: var(--surface-raised);
}
.headline { font-weight: 650; }
.detail { font-size: 0.82rem; margin: 0.15rem 0 0.3rem; }
.because { font-size: 0.78rem; color: var(--ink-secondary); }
.no-advice { font-size: 0.82rem; max-width: 42ch; }

.numbers { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.numbers th, .numbers td {
  padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--line); text-align: left;
}
.numbers th { color: var(--ink-muted); font-weight: 500; font-size: 0.76rem; }
.numbers .num { text-align: right; }
.strong { font-weight: 650; }

.resolution { font-size: 0.75rem; max-width: 60ch; }
.failure { color: var(--loss); }

@media (max-width: 1100px) {
  .body { grid-template-columns: minmax(0, 1fr); }
}
</style>
