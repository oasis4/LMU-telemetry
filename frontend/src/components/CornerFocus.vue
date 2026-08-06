<script setup>
/**
 * One corner at a time: step through them, see only that one.
 *
 * The whole-lap view answers "where did the time go". This answers "what
 * happened here", which is a different question and deserves its own screen
 * rather than a row in a table.
 *
 * The traces are tabbed rather than stacked: a corner is a few hundred metres,
 * and four charts of it side by side is four small pictures instead of one
 * readable one.
 */
import { computed, ref, watch } from 'vue'

import CornerMap from './CornerMap.vue'
import TraceChart from './TraceChart.vue'
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
const channel = ref('speed')

const CHANNELS = [
  { key: 'speed', label: 'Speed', unit: 'speed (km/h)',
    pick: (s) => [s.speed_reference_kmh, s.speed_other_kmh],
    format: (v) => (v == null ? '--' : `${v.toFixed(1)} km/h`) },
  { key: 'delta', label: 'Delta', unit: 'delta (s)',
    pick: (s) => [null, s.delta_s],
    format: (v) => (v == null ? '--' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(3)} s`) },
  { key: 'brake', label: 'Braking', unit: 'brake',
    pick: (s) => [s.brake_reference, s.brake_other],
    format: (v) => (v == null ? '--' : `${(v * 100).toFixed(0)} %`) },
]

const corner = computed(() => props.comparison.corners[props.index] ?? null)
const advice = computed(() =>
  (props.comparison.advice ?? []).filter((a) => a.corner === corner.value?.index),
)

/** The indices of the full-resolution trace covering this corner plus run-up. */
const slice = computed(() => {
  if (!detail.value || !corner.value) return null
  const s = detail.value.series
  const distance = s.distance_m
  const step = distance[1] - distance[0]
  const lapLength = distance[distance.length - 1] + step
  const index = (m) => Math.round((((m % lapLength) + lapLength) % lapLength) / step)

  const first = index(corner.value.start_m - props.approachM)
  const last = index(corner.value.end_m + props.approachM)
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
  return { axis, take, series: s }
})

const chart = computed(() => {
  if (!slice.value) return null
  const spec = CHANNELS.find((c) => c.key === channel.value)
  const [reference, other] = spec.pick(slice.value.series)
  return {
    spec,
    distance: slice.value.axis,
    // A single-series channel is drawn with the reference doubled up: uPlot
    // needs two arrays, and the legend then names them honestly.
    reference: slice.value.take(reference ?? other),
    other: slice.value.take(other),
    single: reference === null,
  }
})

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
  () => [props.comparison.reference.lap, props.comparison.other.lap],
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

const rows = computed(() => {
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

        <ul v-if="advice.length" class="advice">
          <li v-for="tip in advice" :key="tip.headline">
            <p class="headline">{{ tip.headline }}</p>
            <p class="detail muted">{{ tip.detail }}</p>
            <p class="because num">{{ tip.because }}</p>
          </li>
        </ul>
        <p v-else-if="!loading" class="muted no-advice">
          The measurements here do not agree on one story, so there is no tip —
          the numbers below are what this corner actually says.
        </p>
      </div>

      <div class="right">
        <table class="numbers">
          <thead>
            <tr><th></th><th class="num">reference</th><th class="num">compared</th><th class="num">difference</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row[0]">
              <td>{{ row[0] }}</td>
              <td class="num muted">{{ row[1] }}</td>
              <td class="num">{{ row[2] }}</td>
              <td class="num strong">{{ row[3] }}</td>
            </tr>
          </tbody>
        </table>

        <div class="tabs" role="tablist">
          <button
            v-for="c in CHANNELS"
            :key="c.key"
            type="button"
            role="tab"
            :aria-selected="channel === c.key"
            :class="{ current: channel === c.key }"
            @click="channel = c.key"
          >{{ c.label }}</button>
        </div>

        <TraceChart
          v-if="chart"
          :distance="chart.distance"
          :reference="chart.reference"
          :other="chart.other"
          :reference-label="chart.single ? 'delta' : `lap ${props.comparison.reference.lap}`"
          :other-label="chart.single ? 'delta' : `lap ${props.comparison.other.lap}`"
          :y-label="chart.spec.unit"
          :format="chart.spec.format"
          :height="190"
        />
        <p v-if="slice" class="muted resolution">
          {{ slice.axis.length }} points over
          {{ (slice.axis[slice.axis.length - 1] - slice.axis[0]).toFixed(0) }} m,
          against {{ detail.samples }} for the whole lap
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

.body { display: grid; grid-template-columns: minmax(0, 420px) minmax(0, 1fr); gap: 1.2rem; }
.left, .right { min-width: 0; display: flex; flex-direction: column; gap: 0.7rem; }

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

.tabs { display: flex; gap: 0.3rem; }
.tabs button {
  padding: 0.25rem 0.7rem;
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 0.8rem;
  color: var(--ink-secondary);
}
.tabs button:hover { background: var(--hover); }
.tabs button.current { background: var(--selected); color: var(--ink); border-color: var(--compared); }

.resolution { font-size: 0.75rem; }
.failure { color: var(--loss); }

@media (max-width: 1100px) {
  .body { grid-template-columns: minmax(0, 1fr); }
}
</style>
