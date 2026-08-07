<script setup>
/**
 * Two laps, one corner list.
 *
 * The corners come from the comparison response, so both drivers are measured
 * against the same definitions. The old view fetched `/api/corners/{session}`
 * once per side, which meant the two halves of every per-corner figure
 * answered different questions.
 *
 * Layout: the board on top, then the one number the page exists for, then the
 * shape and the ranked losses side by side, then the corner overlay. The
 * whole-lap traces and the full corner table are still here but folded away -
 * they answer "where did the time go", which the map and the bars above
 * already answer, and leaving all of it open is what made this page a wall.
 */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'

import CornerFocus from '../components/CornerFocus.vue'
import CornerTable from '../components/CornerTable.vue'
import DeltaChart from '../components/DeltaChart.vue'
import LapBoard from '../components/LapBoard.vue'
import LapHeadline from '../components/LapHeadline.vue'
import TimeLossBars from '../components/TimeLossBars.vue'
import TraceChart from '../components/TraceChart.vue'
import TrackMap from '../components/TrackMap.vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, comparison, loading, error } = storeToRefs(store)

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

async function pick({ side, name, lap }) {
  const changedRecording = store.selection[side] !== name
  store.select({ [side]: name, [`${side}Lap`]: lap })
  focusIndex.value = null
  // The map belongs to the circuit, so it is fetched per recording rather
  // than per comparison, and only for the reference side - the board only
  // ever offers one circuit, and the server refuses a comparison across two.
  if (side === 'reference' && changedRecording) {
    trackMap.value = await store.client.map(name).catch(() => null)
    trackModel.value = await store.client.track(name).catch(() => null)
  }
}

// Watched on the selection itself, not on `store.ready`: that stays true when
// only the lap changes, and a computed that recomputes to the same value
// notifies nobody - so picking another lap of the same recording left the
// previous lap's numbers on screen under the new lap's name.
watch(
  () => [store.selectionKey, fullResolution.value],
  ([key]) => {
    if (key !== null) store.loadComparison({ full: fullResolution.value })
  },
)

/** The corner with the largest loss, so the overlay opens on something. */
watch(comparison, (found) => {
  if (!found || focusIndex.value !== null) return
  let worst = 0
  found.corners.forEach((c, at) => {
    if (c.lost_s > found.corners[worst].lost_s) worst = at
  })
  if (found.corners.length) focusIndex.value = worst
})
</script>

<template>
  <div class="compare">
    <LapBoard
      :sessions="sessions"
      :selection="selection"
      :load-laps="store.client.laps"
      @select="pick"
    />

    <main class="reading" :class="{ stale: loading && comparison }">
      <p v-if="error" class="card failure">{{ error }}</p>

      <section v-else-if="!comparison" class="card empty">
        <h1>Pick two laps</h1>
        <p class="muted">
          One circuit at a time, quickest usable lap first. Both laps are then
          measured on one distance grid and against one corner list, so every
          per-corner figure is between the same two questions.
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
              :braking="comparison.braking ?? null"
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

        <CornerFocus
          v-if="selectedCorner"
          :comparison="comparison"
          :map="trackMap"
          :index="focusIndex"
          @step="step"
        />

        <details class="card folded">
          <summary>
            <h2>The whole lap</h2>
            <span class="note">delta and speed, start to finish</span>
          </summary>
          <div class="folded-body">
            <label class="note resolution">
              <input v-model="fullResolution" type="checkbox" />
              full resolution ({{ comparison.samples }} points)
            </label>
            <DeltaChart
              :distance="comparison.series.distance_m"
              :delta="comparison.series.delta_s"
              :corners="comparison.corners"
              :selected="selectedCorner?.index ?? null"
            />
            <TraceChart
              :distance="comparison.series.distance_m"
              :reference="comparison.series.speed_reference_kmh"
              :other="comparison.series.speed_other_kmh"
              :reference-label="`lap ${comparison.reference.lap}`"
              :other-label="`lap ${comparison.other.lap}`"
              y-label="speed (km/h)"
            />
          </div>
        </details>

        <details class="card folded">
          <summary>
            <h2>Every corner</h2>
            <span class="note">in track order</span>
          </summary>
          <div class="folded-body">
            <CornerTable
              :corners="comparison.corners"
              :selected="selectedCorner?.index ?? null"
              @select="pickCorner"
            />
          </div>
        </details>
      </template>
    </main>
  </div>
</template>

<style scoped>
.compare { display: flex; flex-direction: column; gap: 1rem; }

.reading { display: flex; flex-direction: column; gap: 1rem; min-width: 0; }
/* Same reason as .card: a flex item will not shrink below its content, and a
 * chart canvas has a fixed pixel width. */
.reading > * { min-width: 0; }
.overview > * { min-width: 0; }

/* Hold the previous render while a new one loads, rather than flashing a
 * skeleton and jumping the layout. */
.reading.stale { opacity: 0.55; transition: opacity 0.15s ease; }

.overview { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; }

.folded summary {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  cursor: pointer;
  list-style: none;
}
.folded summary::-webkit-details-marker { display: none; }
.folded summary::before { content: '▸'; color: var(--ink-muted); font-size: 0.8rem; }
.folded[open] summary::before { content: '▾'; }
.folded-body { display: flex; flex-direction: column; gap: 0.8rem; margin-top: 0.8rem; min-width: 0; }

.empty { display: flex; flex-direction: column; gap: 0.5rem; }
.empty p { max-width: 55ch; }
.failure { color: var(--loss); font-weight: 600; }
.resolution { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }

@media (max-width: 1200px) {
  .overview { grid-template-columns: minmax(0, 1fr); }
}
</style>
