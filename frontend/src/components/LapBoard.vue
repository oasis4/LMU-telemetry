<script setup>
/**
 * Which two laps to compare, chosen the way a lap is actually chosen.
 *
 * The old picker asked for a *recording* per side: two dropdowns of 78 files
 * labelled by session type. But nobody looks for "the qualifying session on
 * the 20th" - they look for a time, on a circuit, in a car, by a driver. So
 * this is a board of laps: one circuit, every recording's best usable lap on
 * it, quickest first, with the class, the entry and the driver on the row.
 * Session type is not shown at all; whether a lap was set in practice or in a
 * race says nothing about the lap.
 *
 * Choosing costs no request. The listing already carries each recording's
 * best usable lap and its number, so a row is selectable as it stands; the
 * lap list underneath is fetched only when a row is opened to pick a
 * different one.
 *
 * One circuit at a time, because a comparison across two circuits is refused
 * by the server. Restricting the board to one is what makes that error
 * unreachable rather than something to report afterwards.
 */
import { computed, ref, watch } from 'vue'

import { carEntry, gap, lapTime } from '../format.js'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  selection: { type: Object, required: true },
  /** Fetches one recording's laps; injected so the board can be tested. */
  loadLaps: { type: Function, required: true },
})
const emit = defineEmits(['select'])

const circuit = ref(null)
const openRow = ref(null)
const lapsByName = ref({})
const loadingLaps = ref(null)
const collapsed = ref(false)
const drivers = ref(new Set())
const classes = ref(new Set())

/** Circuits present, with how many recordings each has. */
const circuits = computed(() => {
  const found = new Map()
  for (const s of props.sessions) {
    if (s.error) continue
    const key = `${s.track}|${s.layout}`
    if (!found.has(key)) {
      found.set(key, { key, track: s.track, layout: s.layout, count: 0, best: null })
    }
    const entry = found.get(key)
    entry.count += 1
    if (s.best_lap_s !== null && (entry.best === null || s.best_lap_s < entry.best)) {
      entry.best = s.best_lap_s
    }
  }
  return [...found.values()].sort((a, b) => a.track.localeCompare(b.track))
})

/** The chosen circuit's recordings, quickest usable lap first. */
const board = computed(() => {
  const rows = props.sessions.filter(
    (s) => !s.error && `${s.track}|${s.layout}` === circuit.value,
  )
  return rows.sort((a, b) => {
    // A recording with no usable lap sorts last rather than first: null is
    // not a quick time, it is the absence of one.
    if (a.best_lap_s === null) return b.best_lap_s === null ? 0 : 1
    if (b.best_lap_s === null) return -1
    return a.best_lap_s - b.best_lap_s
  })
})

const filtered = computed(() =>
  board.value.filter(
    (s) =>
      (!drivers.value.size || drivers.value.has(s.driver)) &&
      (!classes.value.size || classes.value.has(s.car_class)),
  ),
)

/** A filter is only worth offering when the circuit has more than one value:
 *  a chip that every row matches is a control that does nothing. */
function options(field) {
  const found = [...new Set(board.value.map((s) => s[field]))].sort()
  return found.length > 1 ? found : []
}
const driverOptions = computed(() => options('driver'))
const classOptions = computed(() => options('car_class'))

const quickest = computed(() => filtered.value.find((s) => s.best_lap_s !== null)?.best_lap_s ?? null)

const picked = computed(() => ({
  reference: props.selection.reference,
  other: props.selection.other,
}))

function sideOf(name) {
  if (picked.value.reference === name) return 'reference'
  if (picked.value.other === name) return 'other'
  return null
}

/** Pick this recording's lap *number* for *side*. */
function choose(side, session, lapNumber) {
  const lap = lapNumber ?? session.best_lap
  if (lap === null || lap === undefined) return
  emit('select', { side, name: session.name, lap })
}

async function toggleRow(session) {
  if (openRow.value === session.name) {
    openRow.value = null
    return
  }
  openRow.value = session.name
  if (lapsByName.value[session.name]) return
  loadingLaps.value = session.name
  try {
    const laps = await props.loadLaps(session.name)
    lapsByName.value = { ...lapsByName.value, [session.name]: laps }
  } catch {
    lapsByName.value = { ...lapsByName.value, [session.name]: [] }
  } finally {
    loadingLaps.value = null
  }
}

/** Toggle one value of a filter. The refs are named rather than passed in:
 *  a template unwraps a ref before it reaches an argument, so a function
 *  taking one would be handed the Set and would write to a copy. */
function toggleFilter(which, value) {
  const set = which === 'driver' ? drivers : classes
  const next = new Set(set.value)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  set.value = next
}

/** Land on a circuit rather than on an empty board. */
watch(
  circuits,
  (found) => {
    if (circuit.value !== null || !found.length) return
    // The one already chosen if the store was restored, else the circuit with
    // the most recordings - the one there is most to compare on.
    const current = props.sessions.find((s) => s.name === props.selection.reference)
    circuit.value = current
      ? `${current.track}|${current.layout}`
      : [...found].sort((a, b) => b.count - a.count)[0].key
  },
  { immediate: true },
)

watch(circuit, () => {
  openRow.value = null
  drivers.value = new Set()
  classes.value = new Set()
})

const chosenCircuit = computed(() => circuits.value.find((c) => c.key === circuit.value) ?? null)
const bothPicked = computed(() => Boolean(picked.value.reference && picked.value.other))

watch(bothPicked, (both, before) => {
  // Fold away once there is something to look at, but never fold back open:
  // a user who opened it to change a lap is not finished after one click.
  if (both && !before) collapsed.value = true
})

function summaryOf(name) {
  return props.sessions.find((s) => s.name === name) ?? null
}
function lapOf(side) {
  return side === 'reference' ? props.selection.referenceLap : props.selection.otherLap
}
</script>

<template>
  <section class="card board">
    <header class="bar">
      <h2>Laps</h2>

      <label class="circuit">
        <span class="sr-only">circuit</span>
        <select v-model="circuit">
          <option v-for="c in circuits" :key="c.key" :value="c.key">
            {{ c.track }}{{ c.layout !== c.track ? ` — ${c.layout}` : '' }}
            ({{ c.count }})
          </option>
        </select>
      </label>

      <button type="button" class="fold" @click="collapsed = !collapsed">
        {{ collapsed ? 'change laps' : 'done' }}
      </button>
    </header>

    <p v-if="collapsed" class="chosen">
      <span v-for="side in ['reference', 'other']" :key="side" class="pick" :class="side">
        <span class="swatch" :class="side" aria-hidden="true" />
        <template v-if="summaryOf(picked[side])">
          <span class="num time">{{
            lapTime(
              (lapsByName[picked[side]] ?? []).find((l) => l.number === lapOf(side))?.duration_s
                ?? summaryOf(picked[side]).best_lap_s,
            )
          }}</span>
          <span class="muted">
            {{ summaryOf(picked[side]).car_class }} ·
            {{ carEntry(summaryOf(picked[side]).car).entry }} ·
            {{ summaryOf(picked[side]).driver }} · lap {{ lapOf(side) }}
          </span>
        </template>
        <span v-else class="muted">not chosen</span>
      </span>
    </p>

    <template v-else>
      <div v-if="classOptions.length || driverOptions.length" class="filters">
        <button
          v-for="value in classOptions"
          :key="`class-${value}`"
          type="button"
          class="chip"
          :class="{ on: classes.has(value) }"
          @click="toggleFilter('class', value)"
        >{{ value }}</button>
        <button
          v-for="value in driverOptions"
          :key="`driver-${value}`"
          type="button"
          class="chip"
          :class="{ on: drivers.has(value) }"
          @click="toggleFilter('driver', value)"
        >{{ value }}</button>
      </div>

      <ol class="rows">
        <li v-for="session in filtered" :key="session.name">
          <div class="row" :class="[sideOf(session.name) ?? '', { none: session.best_lap === null }]">
            <span class="sides">
              <button
                v-for="side in ['reference', 'other']"
                :key="side"
                type="button"
                class="side"
                :class="[side, { on: sideOf(session.name) === side }]"
                :disabled="session.best_lap === null"
                :title="side === 'reference' ? 'use as reference' : 'compare against the reference'"
                @click="choose(side, session)"
              >{{ side === 'reference' ? 'A' : 'B' }}</button>
            </span>

            <span class="num time">{{ lapTime(session.best_lap_s) }}</span>
            <span class="num behind muted">{{
              session.best_lap_s !== null && quickest !== null && session.best_lap_s !== quickest
                ? gap(session.best_lap_s - quickest)
                : ''
            }}</span>

            <span class="tag">{{ session.car_class }}</span>
            <span class="car">
              {{ carEntry(session.car).entry
              }}<span v-if="carEntry(session.car).series" class="muted series">
                {{ carEntry(session.car).series }}</span>
            </span>
            <span class="driver">{{ session.driver }}</span>

            <span class="muted count num">
              {{ session.best_lap === null ? 'no usable lap' : `${session.clean_laps} usable` }}
            </span>

            <button
              type="button"
              class="expand"
              :disabled="session.best_lap === null"
              :aria-expanded="openRow === session.name"
              :aria-label="`other laps of ${session.name}`"
              @click="toggleRow(session)"
            >{{ openRow === session.name ? '▴' : '▾' }}</button>
          </div>

          <div v-if="openRow === session.name" class="laps">
            <p v-if="loadingLaps === session.name" class="muted small">reading laps…</p>
            <button
              v-for="l in lapsByName[session.name] ?? []"
              :key="l.number"
              type="button"
              class="lap"
              :class="{
                current:
                  (picked.reference === session.name && selection.referenceLap === l.number) ||
                  (picked.other === session.name && selection.otherLap === l.number),
              }"
              :disabled="!l.clean"
              :title="l.reason ?? ''"
              @click="choose(sideOf(session.name) ?? 'other', session, l.number)"
            >
              <span class="muted num small">{{ l.number }}</span>
              <span class="num">{{ lapTime(l.duration_s) }}</span>
              <span v-if="!l.clean" class="muted small reason">{{ l.reason }}</span>
            </button>
          </div>
        </li>
        <li v-if="!filtered.length" class="muted small empty">
          nothing on this circuit matches the filters
        </li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.board { display: flex; flex-direction: column; gap: 0.6rem; }

.bar { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0; }
.circuit select { max-width: 26rem; }
.fold { margin-left: auto; font-size: 0.78rem; color: var(--ink-secondary); }
.fold:hover { color: var(--ink); }

.chosen { display: flex; flex-wrap: wrap; gap: 1.5rem; font-size: 0.85rem; }
.pick { display: flex; align-items: baseline; gap: 0.45rem; min-width: 0; }
.swatch { width: 10px; height: 3px; border-radius: 2px; align-self: center; }
.swatch.reference { background: var(--reference); }
.swatch.other { background: var(--compared); }
.time { font-weight: 650; }

.filters { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip {
  padding: 0.15rem 0.55rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 0.75rem;
  color: var(--ink-secondary);
}
.chip:hover { background: var(--hover); }
.chip.on { background: var(--selected); color: var(--ink); border-color: var(--compared); }

.rows { list-style: none; max-height: 22rem; overflow-y: auto; }

/* Fixed columns rather than flex, so the times, classes and drivers of
 * different rows line up and the board can be read down a column. minmax(0,…)
 * on the text columns keeps a long entry name from widening the page. */
.row {
  display: grid;
  grid-template-columns:
    auto 5.5rem 4rem auto minmax(0, 1fr) minmax(0, 11rem) 6rem auto;
  align-items: center;
  gap: 0.7rem;
  padding: 0.28rem 0.4rem;
  border-radius: 5px;
  font-size: 0.86rem;
}
.row:hover { background: var(--hover); }
.row.reference { background: var(--surface-raised); box-shadow: inset 3px 0 0 var(--reference); }
.row.other { background: var(--selected); box-shadow: inset 3px 0 0 var(--compared); }
.row.none { opacity: 0.5; }

.sides { display: flex; gap: 0.2rem; }
.side {
  width: 22px; height: 22px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--ink-muted);
}
.side:hover:not(:disabled) { background: var(--hover); color: var(--ink); }
.side:disabled { opacity: 0.35; cursor: default; }
.side.reference.on { background: var(--reference); color: var(--page); border-color: var(--reference); }
.side.other.on { background: var(--compared); color: var(--page); border-color: var(--compared); }

.behind { font-size: 0.76rem; }
.tag {
  justify-self: start;
  font-size: 0.68rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 0 0.3rem;
  color: var(--ink-secondary);
}
.car, .driver { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
/* The gap is set here rather than written as a space in the template: Vue
 * condenses whitespace that contains a newline, so the indentation an
 * interpolation sits on is not a separator. */
.series { font-size: 0.72rem; margin-left: 0.35rem; }
.count { font-size: 0.75rem; }
.expand { color: var(--ink-muted); padding: 0 0.2rem; }
.expand:disabled { opacity: 0.3; cursor: default; }

.laps {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  padding: 0.3rem 0.4rem 0.6rem 3.2rem;
}
.lap {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  padding: 0.15rem 0.5rem;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 0.8rem;
}
.lap:hover:not(:disabled) { background: var(--hover); }
.lap.current { background: var(--selected); border-color: var(--compared); }
.lap:disabled { opacity: 0.45; cursor: default; }
.reason { max-width: 12rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: 0.74rem; }
.empty { padding: 0.5rem 0.4rem; }

.sr-only {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap;
}

@media (max-width: 1000px) {
  .row { grid-template-columns: auto 5.5rem 4rem auto minmax(0, 1fr) auto; }
  .row .driver, .row .count { display: none; }
}
</style>
