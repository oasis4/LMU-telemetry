<script setup>
/**
 * One corner, at full resolution.
 *
 * This is the only place that asks for `full=true`. An overview sends about
 * 1500 points because that is what a screen can show; a corner is a few
 * hundred metres of it, so at overview resolution it would be a handful of
 * points. Here the whole trace is fetched once and the corner sliced out of
 * it, which is also why zooming between corners costs nothing.
 */
import { computed, ref, watch } from 'vue'

import SpeedChart from './SpeedChart.vue'
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

/** Indices of the full-resolution trace covering the corner and its approach. */
const window = computed(() => {
  if (!detail.value) return null
  const distance = detail.value.series.distance_m
  const lapLength = distance[distance.length - 1] + (distance[1] - distance[0])
  const from = props.corner.start_m - props.approachM
  const to = props.corner.end_m + props.approachM

  // A corner over the start/finish line, or an approach that reaches back past
  // it, is two pieces of the array. Drawing them as one range would run
  // backwards through the whole lap.
  const wraps = props.corner.start_m > props.corner.end_m || from < 0 || to > lapLength
  const index = (metres) => {
    const wrapped = ((metres % lapLength) + lapLength) % lapLength
    return Math.round(wrapped / (distance[1] - distance[0]))
  }
  return { wraps, first: index(from), last: index(to), samples: distance.length }
})

const slice = computed(() => {
  if (!detail.value || !window.value) return null
  const { first, last, wraps, samples } = window.value
  const take = (values) =>
    wraps && first > last
      ? Float64Array.from([...values.slice(first, samples), ...values.slice(0, last)])
      : values.slice(first, last)

  const s = detail.value.series
  const distance = take(s.distance_m)
  // A wrapped window has to keep rising or the chart folds back on itself.
  const axis = Float64Array.from(distance)
  for (let i = 1; i < axis.length; i += 1) {
    if (axis[i] < axis[i - 1]) axis[i] += detail.value.series.distance_m.length *
      (s.distance_m[1] - s.distance_m[0])
  }
  return {
    distance: axis,
    delta: take(s.delta_s),
    speedReference: take(s.speed_reference_kmh),
    speedOther: take(s.speed_other_kmh),
    brakeReference: take(s.brake_reference),
    brakeOther: take(s.brake_other),
  }
})

async function load() {
  if (detail.value) return
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

function metres(value) {
  return value === null || value === undefined ? '—' : `${value.toFixed(0)} m`
}
function kmh(value) {
  return `${value.toFixed(1)} km/h`
}
</script>

<template>
  <section class="detail">
    <header>
      <h2>{{ props.corner.name }}</h2>
      <span class="span">
        {{ props.corner.start_m.toFixed(0) }}–{{ props.corner.end_m.toFixed(0) }} m
      </span>
      <span class="cost" :class="{ loss: props.corner.lost_s > 0 }">
        {{ props.corner.lost_s >= 0 ? '+' : '−' }}{{ Math.abs(props.corner.lost_s).toFixed(3) }} s
      </span>
    </header>

    <p v-if="failure" class="error">{{ failure }}</p>
    <p v-else-if="loading" class="quiet">reading the corner at full resolution…</p>

    <template v-else-if="slice">
      <p class="resolution quiet">
        {{ slice.distance.length }} points over
        {{ (slice.distance[slice.distance.length - 1] - slice.distance[0]).toFixed(0) }} m,
        against {{ detail.samples }} for the whole lap
      </p>

      <table class="numbers">
        <thead>
          <tr><th></th><th class="num">reference</th><th class="num">compared</th><th class="num">difference</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>brake point</td>
            <td class="num">{{ metres(props.corner.reference.brake_point_m) }}</td>
            <td class="num">{{ metres(props.corner.other.brake_point_m) }}</td>
            <td class="num">
              {{ props.corner.reference.brake_point_m === null || props.corner.other.brake_point_m === null
                ? '—'
                : `${(props.corner.other.brake_point_m - props.corner.reference.brake_point_m).toFixed(0)} m` }}
            </td>
          </tr>
          <tr>
            <td>entry speed</td>
            <td class="num">{{ kmh(props.corner.reference.entry_speed_kmh) }}</td>
            <td class="num">{{ kmh(props.corner.other.entry_speed_kmh) }}</td>
            <td class="num">{{ (props.corner.other.entry_speed_kmh - props.corner.reference.entry_speed_kmh).toFixed(1) }}</td>
          </tr>
          <tr>
            <td>minimum speed</td>
            <td class="num">{{ kmh(props.corner.reference.min_speed_kmh) }}</td>
            <td class="num">{{ kmh(props.corner.other.min_speed_kmh) }}</td>
            <td class="num">{{ (props.corner.other.min_speed_kmh - props.corner.reference.min_speed_kmh).toFixed(1) }}</td>
          </tr>
          <tr>
            <td>throttle point</td>
            <td class="num">{{ metres(props.corner.reference.throttle_point_m) }}</td>
            <td class="num">{{ metres(props.corner.other.throttle_point_m) }}</td>
            <td class="num">
              {{ props.corner.reference.throttle_point_m === null || props.corner.other.throttle_point_m === null
                ? '—'
                : `${(props.corner.other.throttle_point_m - props.corner.reference.throttle_point_m).toFixed(0)} m` }}
            </td>
          </tr>
          <tr>
            <td>exit speed</td>
            <td class="num">{{ kmh(props.corner.reference.exit_speed_kmh) }}</td>
            <td class="num">{{ kmh(props.corner.other.exit_speed_kmh) }}</td>
            <td class="num">{{ (props.corner.other.exit_speed_kmh - props.corner.reference.exit_speed_kmh).toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>

      <SpeedChart
        :distance="slice.distance"
        :reference="slice.speedReference"
        :other="slice.speedOther"
        :reference-label="`lap ${detail.reference.lap}`"
        :other-label="`lap ${detail.other.lap}`"
        :height="180"
      />
      <SpeedChart
        :distance="slice.distance"
        :reference="slice.brakeReference"
        :other="slice.brakeOther"
        reference-label="brake ref"
        other-label="brake"
        :height="120"
      />
    </template>
  </section>
</template>

<style scoped>
.detail { border: 1px solid var(--line); border-radius: 6px; padding: 1rem; }
header { display: flex; align-items: baseline; gap: 0.8rem; margin-bottom: 0.6rem; }
h2 { font-size: 1.05rem; margin: 0; }
.span { color: var(--muted); font-size: 0.85rem; }
.cost { margin-left: auto; font-weight: 700; font-variant-numeric: tabular-nums; }
.cost.loss { color: var(--loss); }
.numbers { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-bottom: 0.8rem; }
.numbers th, .numbers td { padding: 0.25rem 0.5rem; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.resolution { font-size: 0.8rem; margin-bottom: 0.6rem; }
.quiet { color: var(--muted); }
.error { color: var(--loss); }
</style>
