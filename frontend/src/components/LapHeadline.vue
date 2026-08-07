<script setup>
/**
 * The one number the page exists to show, and the two lap times behind it.
 *
 * A stat tile rather than a chart: the story is a single figure. Proportional
 * figures on it - tabular-nums makes a large standalone number read loose.
 * The two lap times below it are a column, so those do get tabular.
 */
import { computed } from 'vue'

const props = defineProps({
  comparison: { type: Object, required: true },
  track: { type: Object, default: null },
})

const delta = computed(() => props.comparison.lap_delta_s)
const tone = computed(() => (delta.value > 0.02 ? 'loss' : delta.value < -0.02 ? 'gain' : 'level'))

function lapTime(seconds) {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}
</script>

<template>
  <section class="card headline">
    <div class="figure-block">
      <p class="figure" :class="tone">
        {{ delta >= 0 ? '+' : '−' }}{{ Math.abs(delta).toFixed(3) }}<span class="unit">s</span>
      </p>
      <p class="caption muted">
        {{ delta >= 0 ? 'slower over the lap' : 'faster over the lap' }}
      </p>
    </div>

    <dl class="times">
      <div>
        <dt><span class="swatch reference" aria-hidden="true" />reference</dt>
        <dd class="num">{{ lapTime(props.comparison.reference.duration_s) }}</dd>
        <dd class="muted small">lap {{ props.comparison.reference.lap }}</dd>
      </div>
      <div>
        <dt><span class="swatch compared" aria-hidden="true" />compared</dt>
        <dd class="num">{{ lapTime(props.comparison.other.duration_s) }}</dd>
        <dd class="muted small">lap {{ props.comparison.other.lap }}</dd>
      </div>
    </dl>

    <div v-if="props.track" class="circuit">
      <p class="name">{{ props.track.track }}</p>
      <p class="muted small">
        {{ props.track.layout !== props.track.track ? props.track.layout + ' · ' : ''
        }}{{ (props.track.track_length_m / 1000).toFixed(3) }} km ·
        {{ props.track.corners.length }} corners
      </p>
      <p v-if="props.track.warning" class="warning">{{ props.track.warning }}</p>
    </div>
  </section>
</template>

<style scoped>
.headline {
  display: flex;
  align-items: flex-start;
  gap: 2rem;
  flex-wrap: wrap;
}

.figure {
  font-size: 2.6rem;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.02em;
}
.figure.loss { color: var(--loss); }
.figure.gain { color: var(--gain); }
.figure.level { color: var(--ink); }
.unit { font-size: 1.2rem; font-weight: 600; margin-left: 0.15rem; }
.caption { font-size: 0.8rem; margin-top: 0.25rem; }

.times { display: flex; gap: 1.75rem; }
.times dt {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-muted);
}
.times dd { font-size: 1.15rem; font-weight: 600; }
.swatch { width: 10px; height: 3px; border-radius: 2px; display: inline-block; }
.swatch.reference { background: var(--reference); }
.swatch.compared { background: var(--compared); }

.circuit { margin-left: auto; text-align: right; }
.circuit .name { font-weight: 600; }
.small { font-size: 0.78rem; }
.warning { color: var(--loss); font-size: 0.75rem; margin-top: 0.2rem; max-width: 22rem; }

@media (max-width: 900px) {
  .circuit { margin-left: 0; text-align: left; }
}
</style>
