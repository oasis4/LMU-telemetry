<script setup>
/**
 * Every corner, what it cost, and what was measurably different in it.
 *
 * The differences come from the server with their own amounts and units, and
 * are rendered as given. Nothing here decides a cause: braking five metres
 * later can be the reason for a loss or the reason for a gain, and the
 * telemetry does not settle which.
 */
const props = defineProps({
  corners: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
})
defineEmits(['select'])

function seconds(value) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`
}

function amount(difference) {
  if (!difference.unit) return difference.what
  const sign = difference.amount >= 0 ? '+' : '−'
  return `${difference.what} ${sign}${Math.abs(difference.amount).toFixed(1)} ${difference.unit}`
}
</script>

<template>
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
        :class="{ selected: corner.index === props.selected, lost: corner.lost_s > 0.05 }"
        @click="$emit('select', corner)"
      >
        <td class="name">{{ corner.name }}</td>
        <td class="num strong">{{ seconds(corner.lost_s) }}</td>
        <td class="num">{{ corner.reference.min_speed_kmh.toFixed(0) }}</td>
        <td class="num">{{ corner.other.min_speed_kmh.toFixed(0) }}</td>
        <td class="num">
          {{ corner.reference.brake_point_m === null ? '—' : corner.reference.brake_point_m.toFixed(0) }}
        </td>
        <td class="num">
          {{ corner.other.brake_point_m === null ? '—' : corner.other.brake_point_m.toFixed(0) }}
        </td>
        <td class="differences">
          <span v-if="!corner.differences.length" class="quiet">nothing measurably different</span>
          <span v-for="difference in corner.differences" :key="difference.what" class="difference">
            {{ amount(difference) }}
          </span>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.corners {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
th, td {
  padding: 0.35rem 0.6rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }
.strong { font-weight: 600; }
.name { font-weight: 600; white-space: nowrap; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: var(--hover); }
tbody tr.selected { background: var(--selected); }
tbody tr.lost .strong { color: var(--loss); }
.difference {
  display: inline-block;
  margin-right: 0.5rem;
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
  background: var(--chip);
  white-space: nowrap;
}
.quiet { color: var(--muted); }
</style>
