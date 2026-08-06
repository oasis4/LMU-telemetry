<script setup>
/**
 * One corner, at full resolution.
 *
 * This is the only caller of `full=true`. An overview sends about 1500 points
 * because that is what a screen shows; a corner is a few hundred metres of it,
 * so at overview resolution it would be a handful of points. The whole trace
 * is fetched once and the corner sliced out, so moving between corners costs
 * nothing after the first.
 */
import { computed, ref, watch } from 'vue'

import TraceChart from './TraceChart.vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  corner: { type: Object, required: true },
  comparison: { type: Object, required: true },
  approachM: { type: Number, default: 250 },
})

const store = useTelemetryStore()
const detail = ref(null)
const loading = ref(false)
const failure = ref(null)

const slice = computed(() => {
  if (!detail.value) return null
  const s = detail.value.series
  const distance = s.distance_m
  const step = distance[1] - distance[0]
  const lapLength = distance[distance.length - 1] + step
  const index = (metres) => Math.round((((metres % lapLength) + lapLength) % lapLength) / step)

  const first = index(props.corner.start_m - props.approachM)
  const last = index(props.corner.end_m + props.approachM)
  const wraps = first > last

  const take = (values) =>
    wraps
      ? Float64Array.from([...values.slice(first, distance.length), ...values.slice(0, last)])
      : values.slice(first, last)

  // A wrapped window has to keep rising, or the chart folds back on itself.
  const axis = Float64Array.from(take(distance))
  for (let i = 1; i < axis.length; i += 1) {
    if (axis[i] < axis[i - 1]) axis[i] += lapLength
  }

  return {
    distance: axis,
    speedReference: take(s.speed_reference_kmh),
    speedOther: take(s.speed_other_kmh),
    brakeReference: take(s.brake_reference),
    brakeOther: take(s.brake_other),
  }
})

async function load() {
  loading.value = true
  failure.value = null
  try {
    detail.value = await store.client.compare({
      reference: props.comparison.reference.name,
      referenceLap: props.comparison.reference.lap,
      other: props.comparison.other.name,
      otherLap: props.comparison.other.lap,
      full: true,
    })
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

const rows = computed(() => {
  const r = props.corner.reference
  const o = props.corner.other
  const metres = (v) => (v === null || v === undefined ? null : `${v.toFixed(0)} m`)
  const kmh = (v) => `${v.toFixed(1)} km/h`
  const gap = (a, b, unit, digits) =>
    a === null || b === null || a === undefined || b === undefined
      ? null
      : `${b - a >= 0 ? '+' : '−'}${Math.abs(b - a).toFixed(digits)} ${unit}`
  return [
    { what: 'brake point', ref: metres(r.brake_point_m), other: metres(o.brake_point_m),
      gap: gap(r.brake_point_m, o.brake_point_m, 'm', 0), later: 'later' },
    { what: 'entry speed', ref: kmh(r.entry_speed_kmh), other: kmh(o.entry_speed_kmh),
      gap: gap(r.entry_speed_kmh, o.entry_speed_kmh, 'km/h', 1), faster: true },
    { what: 'minimum speed', ref: kmh(r.min_speed_kmh), other: kmh(o.min_speed_kmh),
      gap: gap(r.min_speed_kmh, o.min_speed_kmh, 'km/h', 1), faster: true },
    { what: 'throttle point', ref: metres(r.throttle_point_m), other: metres(o.throttle_point_m),
      gap: gap(r.throttle_point_m, o.throttle_point_m, 'm', 0), later: 'later' },
    { what: 'exit speed', ref: kmh(r.exit_speed_kmh), other: kmh(o.exit_speed_kmh),
      gap: gap(r.exit_speed_kmh, o.exit_speed_kmh, 'km/h', 1), faster: true },
  ]
})
</script>

<template>
  <section class="card detail">
    <header>
      <h2>{{ props.corner.name }}</h2>
      <span class="muted num">
        {{ props.corner.start_m.toFixed(0) }}–{{ props.corner.end_m.toFixed(0) }} m
      </span>
      <span class="cost num" :class="props.corner.lost_s > 0.02 ? 'loss' : 'gain'">
        {{ props.corner.lost_s >= 0 ? '+' : '−' }}{{ Math.abs(props.corner.lost_s).toFixed(3) }} s
      </span>
    </header>

    <p v-if="failure" class="failure">{{ failure }}</p>
    <p v-else-if="loading" class="muted">reading this corner at full resolution…</p>

    <template v-else-if="slice">
      <table class="numbers">
        <thead>
          <tr>
            <th></th>
            <th class="num">reference</th>
            <th class="num">compared</th>
            <th class="num">difference</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.what">
            <td>{{ row.what }}</td>
            <td class="num muted">{{ row.ref ?? '—' }}</td>
            <td class="num">{{ row.other ?? '—' }}</td>
            <td class="num gap">{{ row.gap ?? '—' }}</td>
          </tr>
        </tbody>
      </table>

      <TraceChart
        :distance="slice.distance"
        :reference="slice.speedReference"
        :other="slice.speedOther"
        :reference-label="`lap ${detail.reference.lap}`"
        :other-label="`lap ${detail.other.lap}`"
        y-label="speed (km/h)"
        :height="170"
      />
      <TraceChart
        :distance="slice.distance"
        :reference="slice.brakeReference"
        :other="slice.brakeOther"
        :reference-label="`lap ${detail.reference.lap}`"
        :other-label="`lap ${detail.other.lap}`"
        y-label="brake"
        :format="(v) => (v == null ? '--' : `${(v * 100).toFixed(0)} %`)"
        :height="120"
      />

      <p class="muted resolution">
        {{ slice.distance.length }} points over
        {{ (slice.distance[slice.distance.length - 1] - slice.distance[0]).toFixed(0) }} m,
        against {{ detail.samples }} for the whole lap
      </p>
    </template>
  </section>
</template>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 0.75rem; }
.detail > header { margin-bottom: 0; }
.cost { margin-left: auto; font-weight: 700; font-size: 1.05rem; }
.cost.loss { color: var(--loss); }
.cost.gain { color: var(--gain); }

.numbers { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.numbers th,
.numbers td { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--line); text-align: left; }
.numbers th { color: var(--ink-muted); font-weight: 500; font-size: 0.78rem; }
.numbers td.num,
.numbers th.num { text-align: right; }
.gap { font-weight: 600; }

.resolution { font-size: 0.75rem; }
.failure { color: var(--loss); }
</style>
