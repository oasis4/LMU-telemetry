<script setup>
/**
 * One side of a comparison: which recording, and which of its laps.
 *
 * A native select with 78 options was what this replaced. Recordings are
 * grouped by circuit and filtered by typing, and the laps are a list of rows
 * showing their times - because the time is what you choose a lap by, and a
 * dropdown hides all of them but one.
 *
 * A lap the pipeline refuses stays in the list, greyed, with the reason it
 * gave. A lap that vanishes without explanation is indistinguishable from a
 * bug, which is the thing this rework exists to remove.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  sessions: { type: Array, default: () => [] },
  laps: { type: Array, default: () => [] },
  session: { type: String, default: null },
  lap: { type: Number, default: null },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:session', 'update:lap'])

const query = ref('')
const open = ref(false)

const chosen = computed(() =>
  props.sessions.find((s) => s.name === props.session) ?? null,
)

const groups = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const matches = props.sessions.filter(
    (s) =>
      !needle ||
      `${s.track} ${s.layout} ${s.car_class} ${s.session_type}`
        .toLowerCase()
        .includes(needle),
  )
  const byTrack = new Map()
  for (const s of matches) {
    if (!byTrack.has(s.track)) byTrack.set(s.track, [])
    byTrack.get(s.track).push(s)
  }
  return [...byTrack.entries()].map(([track, items]) => ({ track, items }))
})

const usable = computed(() => props.laps.filter((l) => l.clean))
const best = computed(() =>
  usable.value.reduce(
    (fastest, l) => (fastest === null || l.duration_s < fastest ? l.duration_s : fastest),
    null,
  ),
)

function lapTime(seconds) {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}

function choose(name) {
  emit('update:session', name)
  open.value = false
  query.value = ''
}
</script>

<template>
  <section class="card selector">
    <header>
      <h2>{{ props.label }}</h2>
      <span v-if="chosen" class="note num">{{ usable.length }} usable</span>
    </header>

    <button class="chosen" type="button" @click="open = !open">
      <template v-if="chosen">
        <span class="track">{{ chosen.track }}</span>
        <span class="meta muted">
          {{ chosen.layout !== chosen.track ? chosen.layout + ' · ' : ''
          }}{{ chosen.session_type }} · {{ chosen.car_class }}
        </span>
      </template>
      <span v-else class="muted">choose a recording…</span>
      <span class="chevron muted" aria-hidden="true">{{ open ? '▴' : '▾' }}</span>
    </button>

    <div v-if="open" class="picker">
      <input
        v-model="query"
        type="search"
        placeholder="filter by circuit, car or session"
        autocomplete="off"
      />
      <ul class="recordings">
        <li v-for="group in groups" :key="group.track" class="group">
          <p class="track-name">{{ group.track }}</p>
          <button
            v-for="item in group.items"
            :key="item.name"
            type="button"
            class="recording"
            :class="{ current: item.name === props.session }"
            @click="choose(item.name)"
          >
            <span>{{ item.session_type }} · {{ item.car_class }}</span>
            <span class="muted num">{{ item.clean_laps }} laps</span>
          </button>
        </li>
        <li v-if="!groups.length" class="muted empty">nothing matches</li>
      </ul>
    </div>

    <p v-if="props.loading" class="muted empty">reading laps…</p>

    <ol v-else-if="props.laps.length" class="laps">
      <li v-for="l in props.laps" :key="l.number">
        <button
          type="button"
          class="lap"
          :class="{ current: l.number === props.lap, refused: !l.clean }"
          :disabled="!l.clean"
          :title="l.reason ?? ''"
          @click="emit('update:lap', l.number)"
        >
          <span class="number muted num">{{ l.number }}</span>
          <span class="time num">{{ lapTime(l.duration_s) }}</span>
          <span v-if="l.clean && l.duration_s === best" class="tag">best</span>
          <span v-else-if="!l.clean" class="reason muted">{{ l.reason }}</span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.selector { display: flex; flex-direction: column; gap: 0.6rem; }

.chosen {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  width: 100%;
  min-width: 0;
  padding: 0.5rem 0.6rem;
  background: var(--surface-raised);
  border: 1px solid var(--line);
  border-radius: 6px;
  text-align: left;
}
.chosen:hover { background: var(--hover); }
.track { font-weight: 600; white-space: nowrap; }
.meta { font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.chevron { margin-left: auto; }

.picker { display: flex; flex-direction: column; gap: 0.5rem; }
.picker input { width: 100%; }
.recordings { list-style: none; max-height: 15rem; overflow-y: auto; }
.track-name {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-muted);
  padding: 0.4rem 0.3rem 0.15rem;
}
.recording {
  display: flex;
  justify-content: space-between;
  gap: 0.6rem;
  width: 100%;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  border-radius: 4px;
  font-size: 0.85rem;
  text-align: left;
}
.recording:hover { background: var(--hover); }
.recording.current { background: var(--selected); }

.laps { list-style: none; max-height: 18rem; overflow-y: auto; }
.lap {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  width: 100%;
  min-width: 0;
  padding: 0.28rem 0.5rem;
  border-radius: 4px;
  text-align: left;
}
.lap:hover:not(:disabled) { background: var(--hover); }
.lap.current { background: var(--selected); }
.lap.refused { cursor: default; opacity: 0.55; }
.number { min-width: 1.6rem; font-size: 0.78rem; }
.time { font-weight: 600; }
.tag {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--page);
  background: var(--accent);
  border-radius: 3px;
  padding: 0 0.3rem;
}
/* flex: 1 and min-width: 0 together are what make the ellipsis work. Without
 * min-width: 0 a flex item refuses to shrink below its content, so the text
 * never truncates - it pushes the button, the panel and the page wider
 * instead, and the whole layout scrolls sideways because of one long
 * rejection reason. */
.reason {
  flex: 1;
  min-width: 0;
  font-size: 0.72rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty { font-size: 0.82rem; padding: 0.3rem; }
</style>
