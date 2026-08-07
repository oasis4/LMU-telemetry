<script setup>
import { storeToRefs } from 'pinia'

import { useTelemetryStore } from './stores/telemetry.js'

const store = useTelemetryStore()
const { comparison } = storeToRefs(store)
</script>

<template>
  <div class="shell">
    <header>
      <div class="logo">LMU <span class="accent">Telemetry</span></div>
      <nav>
        <router-link :to="{ name: 'compare' }">Compare</router-link>
        <router-link :to="{ name: 'sessions' }">Recordings</router-link>
      </nav>
      <div v-if="comparison" class="context">
        {{ comparison.reference.name }} · lap {{ comparison.reference.lap }}
        vs lap {{ comparison.other.lap }}
      </div>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; min-height: 100vh; }
header {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0 1.5rem;
  height: 3rem;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.logo { font-weight: 800; letter-spacing: 0.03em; }
.logo .accent { color: var(--accent); }
nav { display: flex; gap: 1.2rem; }
nav a {
  color: var(--muted);
  text-decoration: none;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
nav a:hover, nav a.router-link-active { color: var(--accent); }
/* Truncates rather than pushing the header wider. A recording name is long
 * and unbreakable, and without min-width: 0 it stretched the page 61 px past
 * the viewport on a phone - the header being the only thing that overflowed. */
.context {
  margin-left: auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}
main { flex: 1; padding: 1.5rem; max-width: 1400px; width: 100%; margin: 0 auto; }

/* Below this the same information is in the headline card, and the header has
 * no room for it. */
@media (max-width: 700px) {
  .context { display: none; }
  header { padding: 0 1rem; gap: 1rem; }
  main { padding: 1rem; }
}
</style>
