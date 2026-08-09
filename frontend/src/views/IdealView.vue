<script setup>
/**
 * What the best lap in one recording could have been.
 *
 * One recording, because that is what ideal_lap requires: two recordings mean
 * two fuel loads and two tyre states, and a block time from one is not
 * comparable to a block time from the other.
 *
 * Only recordings with two or more usable laps are offered. Of 60 recordings
 * sampled from the corpus, 26 have fewer - so offering all of them would be an
 * invitation into an error message more often than into an answer.
 */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'

import BlockMap from '../components/BlockMap.vue'
import { headlineFor } from '../components/ideal-headline.js'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, ideal, loading, error } = storeToRefs(store)

const chosen = ref(null)
const selected = ref(null)
const trackMap = shallowRef(null)

/** Only what can answer. A recording with one usable lap has nothing to
 *  choose between, and the server would refuse it. */
const usable = computed(() =>
  sessions.value.filter((s) => !s.error && (s.clean_laps ?? 0) >= 2),
)

const headline = computed(() => headlineFor(ideal.value))

function lapTime(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}

onMounted(() => store.loadSessions())

watch(chosen, async (name) => {
  // Cleared before the fetch, not after: left in place, the previous
  // recording's blocks sit under the new recording's name while it loads.
  selected.value = null
  trackMap.value = null
  ideal.value = null
  if (!name) return
  trackMap.value = await store.client.map(name).catch(() => null)
  await store.loadIdeal(name)
})
</script>

<template>
  <section class="ideal">
    <header class="picker">
      <h1>The lap you had in you</h1>
      <select v-model="chosen" aria-label="recording">
        <option :value="null">choose a recording…</option>
        <option v-for="s in usable" :key="s.name" :value="s.name">
          {{ s.track }} — {{ s.session_type }} — {{ s.recorded_at }}
          ({{ s.clean_laps }} usable)
        </option>
      </select>
    </header>

    <p v-if="error" class="card failure">{{ error }}</p>

    <section v-else-if="!chosen" class="card empty">
      <p class="quiet">
        Built from the usable laps of one recording, block by block. A block is
        a run of corners that has to be taken from one lap or not at all — a
        chicane is one act, and taking half of it from another lap would be a
        target nobody can drive. Only recordings with two or more usable laps
        are listed; the rest have nothing to choose between.
      </p>
    </section>

    <p v-else-if="loading || !ideal" class="card quiet">reading…</p>

    <template v-else>
      <section class="card headline" :class="{ qualified: headline.qualified }">
        <div class="figure">
          <span class="label">ideal</span>
          <strong>{{ lapTime(headline.idealS) }}</strong>
        </div>
        <div class="figure">
          <span class="label">best driven — lap {{ ideal.best_lap_number }}</span>
          <strong>{{ lapTime(headline.bestS) }}</strong>
        </div>
        <div v-if="!headline.qualified" class="figure gain">
          <span class="label">left on the table</span>
          <strong>{{ headline.gainS.toFixed(3) }} s</strong>
        </div>
        <p v-else class="doubt">
          <strong>These laps do not support this time.</strong>
          At {{ headline.worstSeam.at_m.toFixed(0) }} m the two laps being
          joined were {{ headline.worstSeam.speed_spread_kmh.toFixed(1) }} km/h
          apart — more than the {{ ideal.seam_limit_kmh }} km/h a join may
          differ by — so the block after it was driven from an entry this lap
          never delivers. The figure is {{ headline.gainS.toFixed(3) }} s. It is
          not a lap that was nearly driven.
        </p>
      </section>

      <div class="body">
        <section class="card">
          <header>
            <h2>Where each part came from</h2>
            <span class="note">coloured by lap, and labelled with it</span>
          </header>
          <BlockMap
            v-if="trackMap"
            :map="trackMap"
            :blocks="ideal.blocks"
            :seams="ideal.seams"
            :selected="selected"
            @select="(b) => (selected = b.index)"
          />
          <p v-else class="quiet">no reference line for this recording</p>
        </section>

        <section class="card">
          <header>
            <h2>Block by block</h2>
            <span class="note">driven order, from the start/finish line</span>
          </header>
          <table class="blocks">
            <thead>
              <tr>
                <th>block</th><th class="num">from lap</th>
                <th class="num">time</th><th class="num">gain</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="block in ideal.blocks"
                :key="block.index"
                :class="{ current: block.index === selected }"
                @mouseenter="selected = block.index"
              >
                <td>{{ block.name }}</td>
                <td class="num">{{ block.lap_number }}</td>
                <td class="num">{{ block.time_s.toFixed(3) }}</td>
                <td class="num" :class="{ gained: block.gain_s > 0 }">
                  {{ block.gain_s > 0 ? `−${block.gain_s.toFixed(3)}` : '—' }}
                </td>
              </tr>
            </tbody>
          </table>
          <p class="note built-from">
            From {{ ideal.laps_used.length }} usable laps:
            {{ ideal.laps_used.join(', ') }}.
          </p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ideal { display: flex; flex-direction: column; gap: 1rem; }
.picker { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.picker select { max-width: 34rem; }

.headline { display: flex; gap: 2.5rem; flex-wrap: wrap; align-items: baseline; }
.headline.qualified { border-left: 3px solid var(--loss); }
.figure { display: flex; flex-direction: column; gap: 0.15rem; }
.figure .label { color: var(--muted); font-size: 0.8rem; }
.figure strong { font-size: 1.6rem; font-variant-numeric: tabular-nums; }
.gain strong { color: var(--gain); }
.doubt { flex: 1 1 22rem; max-width: 62ch; color: var(--loss); margin: 0; font-size: 0.9rem; }

.body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; }
.body > * { min-width: 0; }

.blocks { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.blocks th, .blocks td { padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.gained { color: var(--gain); }
tr.current { background: var(--line); }
.built-from { margin-top: 0.7rem; }
.quiet { color: var(--muted); }
.failure { color: var(--loss); font-weight: 600; }
.empty p { max-width: 62ch; margin: 0; }

@media (max-width: 1200px) { .body { grid-template-columns: minmax(0, 1fr); } }
</style>
