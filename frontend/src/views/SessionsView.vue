<script setup>
/** Every recording found, and how much of each one is usable. */
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, loading, error } = storeToRefs(store)

onMounted(() => store.loadSessions())

function lapTime(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}
</script>

<template>
  <section>
    <h1>Recordings</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="quiet">reading…</p>

    <table v-else class="sessions">
      <thead>
        <tr>
          <th>track</th>
          <th>layout</th>
          <th>car</th>
          <th>session</th>
          <th>recorded</th>
          <th class="num">laps</th>
          <th class="num">usable</th>
          <th class="num">best usable</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="session in sessions" :key="session.name">
          <template v-if="session.error">
            <td>{{ session.name }}</td>
            <td colspan="7" class="error">{{ session.error }}</td>
          </template>
          <template v-else>
            <td>{{ session.track }}</td>
            <td class="quiet">{{ session.layout }}</td>
            <td>{{ session.car_class }}</td>
            <td>{{ session.session_type }}</td>
            <td class="quiet">{{ session.recorded_at }}</td>
            <td class="num">{{ session.laps }}</td>
            <td class="num">{{ session.clean_laps }}</td>
            <td class="num">{{ lapTime(session.best_lap_s) }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.sessions { width: 100%; border-collapse: collapse; font-size: 0.9rem; margin-top: 0.8rem; }
th, td { padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.quiet { color: var(--muted); }
.error { color: var(--loss); }
</style>
