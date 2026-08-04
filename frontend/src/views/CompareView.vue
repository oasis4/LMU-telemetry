<script setup>
/**
 * Two laps, one corner list.
 *
 * The corners come from the comparison response, so both drivers are measured
 * against the same definitions. The old view fetched `/api/corners/{session}`
 * once per side, which meant the two halves of every per-corner figure
 * answered different questions.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import CornerTable from '../components/CornerTable.vue'
import DeltaChart from '../components/DeltaChart.vue'
import LapPicker from '../components/LapPicker.vue'
import SpeedChart from '../components/SpeedChart.vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, comparison, loading, error, worstCorners } = storeToRefs(store)

const referenceLaps = ref([])
const otherLaps = ref([])
const selectedCorner = ref(null)
const fullResolution = ref(false)

const selection = computed(() => store.selection)

onMounted(() => store.loadSessions())

async function pickSession(side, name) {
  store.select({ [side]: name, [`${side}Lap`]: null })
  const laps = name ? await store.client.laps(name).catch(() => []) : []
  if (side === 'reference') referenceLaps.value = laps
  else otherLaps.value = laps
}

watch(
  () => [store.ready, fullResolution.value],
  ([ready]) => {
    if (ready) store.loadComparison({ full: fullResolution.value })
  },
)

function seconds(value) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)} s`
}
</script>

<template>
  <section class="compare">
    <header>
      <h1>Compare two laps</h1>
      <p class="lede">
        Both laps are measured on one distance grid and against one corner list,
        so every per-corner figure is between the same two questions.
      </p>
    </header>

    <div class="pickers">
      <LapPicker
        label="reference"
        :sessions="sessions"
        :laps="referenceLaps"
        :session="selection.reference"
        :lap="selection.referenceLap"
        @update:session="pickSession('reference', $event)"
        @update:lap="store.select({ referenceLap: $event })"
      />
      <LapPicker
        label="compared with"
        :sessions="sessions"
        :laps="otherLaps"
        :session="selection.other"
        :lap="selection.otherLap"
        @update:session="pickSession('other', $event)"
        @update:lap="store.select({ otherLap: $event })"
      />
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="quiet">reading…</p>

    <template v-if="comparison">
      <div class="summary">
        <div class="headline">
          <span class="figure" :class="{ loss: comparison.lap_delta_s > 0 }">
            {{ seconds(comparison.lap_delta_s) }}
          </span>
          <span class="quiet">over the lap</span>
        </div>
        <label class="resolution">
          <input v-model="fullResolution" type="checkbox" />
          full resolution ({{ comparison.samples }} points sent)
        </label>
      </div>

      <ol class="worst">
        <li v-for="corner in worstCorners" :key="corner.index">{{ corner.summary }}</li>
      </ol>

      <DeltaChart
        :distance="comparison.series.distance_m"
        :delta="comparison.series.delta_s"
        :corners="comparison.corners"
      />
      <SpeedChart
        :distance="comparison.series.distance_m"
        :reference="comparison.series.speed_reference_kmh"
        :other="comparison.series.speed_other_kmh"
        :reference-label="`lap ${comparison.reference.lap}`"
        :other-label="`lap ${comparison.other.lap}`"
      />

      <CornerTable
        :corners="comparison.corners"
        :selected="selectedCorner?.index ?? null"
        @select="selectedCorner = $event"
      />
    </template>
  </section>
</template>

<style scoped>
.compare { display: flex; flex-direction: column; gap: 1rem; }
.lede { color: var(--muted); margin: 0.2rem 0 0; max-width: 60ch; }
.pickers { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
.summary { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.figure { font-size: 2rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.figure.loss { color: var(--loss); }
.headline { display: flex; align-items: baseline; gap: 0.5rem; }
.worst { margin: 0; padding-left: 1.2rem; color: var(--text); }
.worst li { margin-bottom: 0.2rem; }
.error { color: var(--loss); font-weight: 600; }
.quiet { color: var(--muted); }
.resolution { font-size: 0.85rem; color: var(--muted); display: flex; align-items: center; gap: 0.4rem; }
@media (max-width: 800px) { .pickers { grid-template-columns: 1fr; } }
</style>
