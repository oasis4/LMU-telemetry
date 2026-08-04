<script setup>
/**
 * One side of a comparison: which recording, and which lap of it.
 *
 * A lap the pipeline refuses is still listed, with the reason it gave, rather
 * than filtered out - a lap that disappears without explanation is
 * indistinguishable from a bug, and that is what this rework is about.
 */
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  sessions: { type: Array, default: () => [] },
  laps: { type: Array, default: () => [] },
  session: { type: String, default: null },
  lap: { type: Number, default: null },
})
const emit = defineEmits(['update:session', 'update:lap'])

const usable = computed(() => props.laps.filter((l) => l.clean))
const refused = computed(() => props.laps.filter((l) => !l.clean))

function lapTime(seconds) {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}
</script>

<template>
  <div class="picker">
    <label class="side">{{ props.label }}</label>

    <select
      :value="props.session ?? ''"
      @change="emit('update:session', $event.target.value || null)"
    >
      <option value="">choose a recording…</option>
      <option v-for="s in props.sessions" :key="s.name" :value="s.name">
        {{ s.track }} · {{ s.session_type }} · {{ s.car_class }} ({{ s.clean_laps }} clean)
      </option>
    </select>

    <select
      :value="props.lap ?? ''"
      :disabled="!usable.length"
      @change="emit('update:lap', $event.target.value === '' ? null : Number($event.target.value))"
    >
      <option value="">choose a lap…</option>
      <option v-for="l in usable" :key="l.number" :value="l.number">
        lap {{ l.number }} — {{ lapTime(l.duration_s) }}
      </option>
    </select>

    <details v-if="refused.length" class="refused">
      <summary>{{ refused.length }} lap(s) not usable</summary>
      <ul>
        <li v-for="l in refused" :key="l.number">
          <strong>lap {{ l.number }}</strong> — {{ l.reason }}
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.picker { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.side { font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; color: var(--muted); }
select { padding: 0.4rem; background: var(--panel); color: inherit; border: 1px solid var(--line); border-radius: 4px; }
.refused { font-size: 0.8rem; color: var(--muted); }
.refused ul { margin: 0.3rem 0 0; padding-left: 1rem; }
.refused li { margin-bottom: 0.15rem; }
</style>
