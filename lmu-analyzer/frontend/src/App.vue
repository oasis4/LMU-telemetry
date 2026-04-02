<script setup>
import { useTelemetryStore } from './stores/telemetry.js'
const store = useTelemetryStore()
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="logo">LMU <span class="accent">Telemetry</span></div>
      <nav v-if="store.currentSession">
        <router-link :to="{ name: 'laps', params: { sessionId: store.sessionId } }">
          Laps
        </router-link>
        <router-link :to="{ name: 'analysis', params: { sessionId: store.sessionId } }">
          Analysis
        </router-link>
      </nav>
      <div class="session-info" v-if="store.currentSession">
        {{ store.currentSession.track }} &mdash; {{ store.currentSession.car }}
      </div>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  height: 48px;
  background: #111114;
  border-bottom: 1px solid #1e1e2e;
  flex-shrink: 0;
}
.logo {
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.5px;
  color: #e0e0e0;
}
.logo .accent {
  color: #3b82f6;
}
nav {
  display: flex;
  gap: 16px;
}
nav a {
  color: #888;
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: color 0.15s;
}
nav a:hover, nav a.router-link-active {
  color: #3b82f6;
}
.session-info {
  margin-left: auto;
  color: #666;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}
.app-main {
  flex: 1;
  overflow: hidden;
}
</style>
