<script setup>
/**
 * Every corner in track order — the table view of everything the charts show.
 *
 * The differences come from the server with their own amounts and units and
 * are rendered as given. Nothing here decides a cause: braking five metres
 * later can be the reason for a loss or the reason for a gain, and the
 * telemetry does not settle which.
 */
const props = defineProps({
  corners: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
})
defineEmits(['select'])

const NOISE_S = 0.02

function seconds(value) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`
}

function tone(value) {
  return value > NOISE_S ? 'loss' : value < -NOISE_S ? 'gain' : 'level'
}

function amount(difference) {
  if (!difference.unit) return difference.what
  const sign = difference.amount >= 0 ? '+' : '−'
  return `${difference.what} ${sign}${Math.abs(difference.amount).toFixed(1)} ${difference.unit}`
}

function metres(value) {
  return value === null || value === undefined ? '—' : value.toFixed(0)
}
</script>

<template>
  <div class="scroller">
    <table class="corners">
      <thead>
        <tr>
          <th>corner</th>
          <th class="num">lost</th>
          <th class="num">v<sub>min</sub> ref</th>
          <th class="num">v<sub>min</sub></th>
          <th class="num">brake ref</th>
          <th class="num">brake</th>
          <th>what differed</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="corner in props.corners"
          :key="corner.index"
          :class="{ selected: corner.index === props.selected }"
          @click="$emit('select', corner)"
        >
          <td class="name">
            <span class="dot" :class="tone(corner.lost_s)" aria-hidden="true" />
            {{ corner.name }}
          </td>
          <td class="num strong" :class="tone(corner.lost_s)">{{ seconds(corner.lost_s) }}</td>
          <td class="num muted">{{ corner.reference.min_speed_kmh.toFixed(0) }}</td>
          <td class="num">{{ corner.other.min_speed_kmh.toFixed(0) }}</td>
          <td class="num muted">{{ metres(corner.reference.brake_point_m) }}</td>
          <td class="num">{{ metres(corner.other.brake_point_m) }}</td>
          <td class="differences">
            <span v-if="!corner.differences.length" class="muted">
              nothing measurably different
            </span>
            <span
              v-for="difference in corner.differences"
              :key="difference.what"
              class="chip"
            >{{ amount(difference) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.scroller { overflow-x: auto; }
.corners { width: 100%; border-collapse: collapse; font-size: 0.84rem; }

th,
td {
  padding: 0.35rem 0.55rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
  white-space: nowrap;
}
th {
  color: var(--ink-muted);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }
.strong { font-weight: 650; }
.strong.loss { color: var(--loss); }
.strong.gain { color: var(--gain); }
.strong.level { color: var(--ink-muted); }

.name { font-weight: 600; }
/* The dot repeats the polarity as a mark beside the name, so the row is
 * readable when the coloured figure is not. */
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 0.45rem;
}
.dot.loss { background: var(--loss); }
.dot.gain { background: var(--gain); }
.dot.level { background: var(--level); }

tbody tr { cursor: pointer; }
tbody tr:hover { background: var(--hover); }
tbody tr.selected { background: var(--selected); }

.differences { white-space: normal; }
.chip {
  display: inline-block;
  margin: 1px 0.3rem 1px 0;
  padding: 0.05rem 0.4rem;
  border-radius: 3px;
  background: var(--surface-raised);
  border: 1px solid var(--line);
  font-size: 0.78rem;
  white-space: nowrap;
}
</style>
