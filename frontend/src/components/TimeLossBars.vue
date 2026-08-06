<script setup>
/**
 * Where the time went, corner by corner.
 *
 * A diverging bar chart: the data's job is polarity plus magnitude, and the
 * baseline is zero in the middle. Two hues that read as opposite, gray for a
 * corner where nothing measurable happened.
 *
 * Gain against loss sits inside the CVD band where colour alone is not enough,
 * so every bar carries its signed value as a direct label. The colour is the
 * quick read; the number is the actual one.
 *
 * Bars are sorted by time lost, which is the question being asked. Track order
 * is what the map and the table are for.
 */
import { computed } from 'vue'

const props = defineProps({
  corners: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  limit: { type: Number, default: 12 },
})
defineEmits(['select'])

const NOISE_S = 0.02

const rows = computed(() => {
  const sorted = [...props.corners].sort((a, b) => b.lost_s - a.lost_s)
  const shown = sorted.slice(0, props.limit)
  const widest = Math.max(...shown.map((c) => Math.abs(c.lost_s)), 0.001)
  return shown.map((corner) => ({
    corner,
    tone: corner.lost_s > NOISE_S ? 'loss' : corner.lost_s < -NOISE_S ? 'gain' : 'level',
    // Half the track on each side of the zero rule, so the two directions are
    // read against the same scale rather than against each other's maxima.
    width: (Math.abs(corner.lost_s) / widest) * 50,
  }))
})

const hidden = computed(() => Math.max(props.corners.length - props.limit, 0))

function seconds(value) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`
}
</script>

<template>
  <ol class="bars">
    <li
      v-for="row in rows"
      :key="row.corner.index"
      :class="{ selected: row.corner.index === props.selected }"
      @click="$emit('select', row.corner)"
    >
      <span class="name">{{ row.corner.name }}</span>
      <span class="track" aria-hidden="true">
        <span class="rule" />
        <span
          class="bar"
          :class="row.tone"
          :style="row.corner.lost_s >= 0
            ? { left: '50%', width: `${row.width}%` }
            : { right: '50%', width: `${row.width}%` }"
        />
      </span>
      <span class="value num" :class="row.tone">{{ seconds(row.corner.lost_s) }}</span>
    </li>
  </ol>
  <p v-if="hidden" class="muted hidden-note">
    {{ hidden }} further corner{{ hidden === 1 ? '' : 's' }} below these — the table
    has all of them
  </p>
</template>

<style scoped>
.bars { list-style: none; display: flex; flex-direction: column; gap: 2px; }

li {
  display: grid;
  grid-template-columns: minmax(6rem, 11rem) 1fr 4.5rem;
  align-items: center;
  gap: 0.6rem;
  padding: 0.2rem 0.35rem;
  border-radius: 4px;
  cursor: pointer;
  min-height: 24px;
}
li:hover { background: var(--hover); }
li.selected { background: var(--selected); }

.name {
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.track { position: relative; height: 12px; }
.rule {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--axis);
}
.bar {
  position: absolute;
  top: 1px;
  bottom: 1px;
  border-radius: 3px;
  min-width: 2px;
}
.bar.loss { background: var(--loss); }
.bar.gain { background: var(--gain); }
.bar.level { background: var(--level); }

.value { text-align: right; font-size: 0.82rem; font-weight: 600; }
.value.loss { color: var(--loss); }
.value.gain { color: var(--gain); }
.value.level { color: var(--ink-muted); }

.hidden-note { font-size: 0.75rem; margin-top: 0.5rem; }
</style>
