<script setup>
/**
 * Two laps, one corner list.
 *
 * The corners come from the comparison response, so both drivers are measured
 * against the same definitions. The old view fetched `/api/corners/{session}`
 * once per side, which meant the two halves of every per-corner figure
 * answered different questions.
 *
 * Layout: choosing on the left, reading on the right. The one number the page
 * exists for sits at the top, then the map and the ranked losses side by side
 * - the shape and the amounts answering the same question two ways - then the
 * traces, then the corner detail once one is picked.
 */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'

import CornerFocus from '../components/CornerFocus.vue'
import CornerTable from '../components/CornerTable.vue'
import DeltaChart from '../components/DeltaChart.vue'
import LapHeadline from '../components/LapHeadline.vue'
import LapSelector from '../components/LapSelector.vue'
import TimeLossBars from '../components/TimeLossBars.vue'
import TraceChart from '../components/TraceChart.vue'
import TrackMap from '../components/TrackMap.vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, comparison, loading, error } = storeToRefs(store)

const referenceLaps = ref([])
const otherLaps = ref([])
const loadingLaps = ref({ reference: false, other: false })
const focusIndex = ref(null)
const fullResolution = ref(false)
const trackMap = shallowRef(null)
const trackModel = shallowRef(null)

const selection = computed(() => store.selection)

/** The corner in focus, derived rather than stored: a new comparison replaces
 *  the corner objects, and a stored one would go on pointing at the old. */
const selectedCorner = computed(() =>
  focusIndex.value === null
    ? null
    : comparison.value?.corners[focusIndex.value] ?? null,
)

/** Corner index -> seconds lost, so the map can colour each corner. */
const losses = computed(() =>
  Object.fromEntries((comparison.value?.corners ?? []).map((c) => [c.index, c.lost_s])),
)

function pickCorner(corner) {
  // The map and the bars hand back their own corner object; the position in
  // the comparison's own list is what the focus panel steps through.
  const at = (comparison.value?.corners ?? []).findIndex((c) => c.index === corner.index)
  focusIndex.value = at >= 0 ? at : null
}

function step(by) {
  const total = comparison.value?.corners.length ?? 0
  if (!total || focusIndex.value === null) return
  focusIndex.value = Math.min(Math.max(focusIndex.value + by, 0), total - 1)
}

onMounted(() => store.loadSessions())

async function pickSession(side, name) {
  store.select({ [side]: name, [`${side}Lap`]: null })
  focusIndex.value = null
  loadingLaps.value = { ...loadingLaps.value, [side]: true }
  try {
    const laps = name ? await store.client.laps(name).catch(() => []) : []
    if (side === 'reference') referenceLaps.value = laps
    else otherLaps.value = laps
    // The map belongs to the circuit, so it is fetched per recording rather
    // than per comparison, and only for the reference side - the server
    // refuses a comparison across two circuits anyway.
    if (side === 'reference') {
      trackMap.value = name ? await store.client.map(name).catch(() => null) : null
      trackModel.value = name ? await store.client.track(name).catch(() => null) : null
    }
  } finally {
    loadingLaps.value = { ...loadingLaps.value, [side]: false }
  }
}

watch(
  () => [store.ready, fullResolution.value],
  ([ready]) => {
    if (ready) store.loadComparison({ full: fullResolution.value })
  },
)
</script>

<template>
  <div class="compare">
    <aside class="choosing">
      <LapSelector
        label="reference"
        :sessions="sessions"
        :laps="referenceLaps"
        :session="selection.reference"
        :lap="selection.referenceLap"
        :loading="loadingLaps.reference"
        @update:session="pickSession('reference', $event)"
        @update:lap="store.select({ referenceLap: $event })"
      />
      <LapSelector
        label="compared with"
        :sessions="sessions"
        :laps="otherLaps"
        :session="selection.other"
        :lap="selection.otherLap"
        :loading="loadingLaps.other"
        @update:session="pickSession('other', $event)"
        @update:lap="store.select({ otherLap: $event })"
      />
    </aside>

    <main class="reading" :class="{ stale: loading && comparison }">
      <p v-if="error" class="card failure">{{ error }}</p>

      <section v-else-if="!comparison" class="card empty">
        <h1>Compare two laps</h1>
        <p class="muted">
          Pick a reference lap and one to compare it with. Both are measured on
          one distance grid and against one corner list, so every per-corner
          figure is between the same two questions.
        </p>
        <p v-if="loading" class="muted">reading…</p>
      </section>

      <template v-else>
        <LapHeadline :comparison="comparison" :track="trackModel" />

        <div class="overview">
          <section class="card">
            <header>
              <h2>Where the lap went</h2>
              <span class="note">{{ trackMap ? trackMap.samples : 0 }} measured points</span>
            </header>
            <TrackMap
              v-if="trackMap"
              :map="trackMap"
              :losses="losses"
              :selected="selectedCorner?.index ?? null"
              @select="pickCorner"
            />
            <p v-else class="muted">no reference line for this recording</p>
          </section>

          <section class="card">
            <header>
              <h2>Where the time went</h2>
              <span class="note">seconds, worst first</span>
            </header>
            <TimeLossBars
              :corners="comparison.corners"
              :selected="selectedCorner?.index ?? null"
              @select="pickCorner"
            />
          </section>
        </div>

        <section class="card">
          <header>
            <h2>Delta over the lap</h2>
            <label class="note resolution">
              <input v-model="fullResolution" type="checkbox" />
              full resolution ({{ comparison.samples }} points)
            </label>
          </header>
          <DeltaChart
            :distance="comparison.series.distance_m"
            :delta="comparison.series.delta_s"
            :corners="comparison.corners"
            :selected="selectedCorner?.index ?? null"
          />
        </section>

        <section class="card">
          <header><h2>Speed</h2></header>
          <TraceChart
            :distance="comparison.series.distance_m"
            :reference="comparison.series.speed_reference_kmh"
            :other="comparison.series.speed_other_kmh"
            :reference-label="`lap ${comparison.reference.lap}`"
            :other-label="`lap ${comparison.other.lap}`"
            y-label="speed (km/h)"
          />
        </section>

        <CornerFocus
          v-if="selectedCorner"
          :comparison="comparison"
          :map="trackMap"
          :index="focusIndex"
          @step="step"
        />

        <section class="card">
          <header>
            <h2>Every corner</h2>
            <span class="note">in track order</span>
          </header>
          <CornerTable
            :corners="comparison.corners"
            :selected="selectedCorner?.index ?? null"
            @select="pickCorner"
          />
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.compare {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

.choosing { display: flex; flex-direction: column; gap: 1rem; position: sticky; top: 1rem; }
.reading { display: flex; flex-direction: column; gap: 1rem; min-width: 0; }
/* Same reason as .card: a flex item will not shrink below its content, and a
 * chart canvas has a fixed pixel width. */
.reading > * { min-width: 0; }
.overview > * { min-width: 0; }

/* Hold the previous render while a new one loads, rather than flashing a
 * skeleton and jumping the layout. */
.reading.stale { opacity: 0.55; transition: opacity 0.15s ease; }

.overview { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; }

.empty { display: flex; flex-direction: column; gap: 0.5rem; }
.empty p { max-width: 55ch; }
.failure { color: var(--loss); font-weight: 600; }
.resolution { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }

@media (max-width: 1200px) {
  .overview { grid-template-columns: minmax(0, 1fr); }
}
/* minmax(0, 1fr), never a bare 1fr: `1fr` means `minmax(auto, 1fr)`, and the
 * auto minimum is the content's minimum - so one unbreakable string keeps the
 * column, and the page, wider than the viewport. */
@media (max-width: 900px) {
  .compare { grid-template-columns: minmax(0, 1fr); }
  .choosing { position: static; }
}
</style>
