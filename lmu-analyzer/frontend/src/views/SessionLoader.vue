<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const router = useRouter()

onMounted(() => {
  store.fetchSessions()
})

async function openSession(filename) {
  await store.loadSession(filename)
  if (store.sessionId) {
    router.push({ name: 'laps', params: { sessionId: store.sessionId } })
  }
}
</script>

<template>
  <div class="session-loader">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>Sessions</h2>
        <span class="text-muted">{{ store.sessions.length }} files</span>
      </div>
      <div class="session-list">
        <div v-if="store.loading" class="loading">Loading…</div>
        <div v-else-if="store.sessions.length === 0" class="empty">
          <p>No .duckdb files found.</p>
          <p class="text-muted">Set <code>TELEMETRY_DIR</code> env variable to your telemetry folder.</p>
        </div>
        <button
          v-for="s in store.sessions"
          :key="s.filename"
          class="session-item"
          @click="openSession(s.filename)"
        >
          <div class="session-name">{{ s.filename }}</div>
          <div class="session-meta">
            <span v-if="s.track">{{ s.track }}</span>
            <span v-if="s.date">{{ s.date }}</span>
          </div>
        </button>
      </div>
    </div>
    <div class="hero-area">
      <div class="hero-content">
        <h1>LMU <span class="text-blue">Telemetry</span> Analyzer</h1>
        <p class="text-muted">Select a session to begin analysis</p>
        <div class="features">
          <div class="feature">
            <div class="feature-icon">📊</div>
            <div>Corner-by-corner analysis</div>
          </div>
          <div class="feature">
            <div class="feature-icon">🏎️</div>
            <div>Dual-lap comparison</div>
          </div>
          <div class="feature">
            <div class="feature-icon">🗺️</div>
            <div>Track map with delta heatmap</div>
          </div>
          <div class="feature">
            <div class="feature-icon">⏱️</div>
            <div>Sector &amp; theoretical best</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-loader {
  display: flex;
  height: 100%;
}
.sidebar {
  width: 320px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-header {
  padding: 16px 20px;
  display: flex;
  align-items: baseline;
  gap: 8px;
  border-bottom: 1px solid var(--border);
}
.sidebar-header h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text-primary);
  font-family: var(--font-sans);
}
.session-item:hover {
  background: var(--bg-tertiary);
  border-color: var(--border);
}
.session-name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 4px;
}
.session-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
.empty {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
}
.empty code {
  background: var(--bg-tertiary);
  padding: 2px 6px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--accent-blue);
}
.hero-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.hero-content {
  text-align: center;
}
.hero-content h1 {
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin-bottom: 8px;
}
.hero-content > p {
  margin-bottom: 40px;
}
.features {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  text-align: left;
}
.feature {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  font-size: 13px;
}
.feature-icon {
  font-size: 18px;
}
</style>
