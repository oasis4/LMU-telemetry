<script setup>
import { useTelemetryStore } from './stores/telemetry.js'
const store = useTelemetryStore()
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="logo">LMU <span class="accent">Telemetry</span></div>
      <nav>
        <router-link :to="{ name: 'sessions' }">
          Sessions
        </router-link>
        <router-link v-if="store.currentSession" :to="{ name: 'dashboard', params: { sessionId: store.sessionId } }">
          Dashboard
        </router-link>
      </nav>
      <div class="session-info" v-if="store.currentSession">
        {{ store.currentSession.track }} &mdash; {{ store.currentSession.car }}
      </div>
    </header>
    <main class="app-main">
      <!-- Global loading overlay -->
      <Transition name="fade">
        <div v-if="store.loading" class="loading-overlay-global">
          <div class="loading-card">
            <div class="loading-bar-track">
              <div class="loading-bar-fill" :style="{ width: store.loadingProgress + '%' }"></div>
            </div>
            <div class="loading-info">
              <span class="loading-msg">{{ store.loadingMessage || 'Loading…' }}</span>
              <span class="loading-pct">{{ store.loadingProgress }}%</span>
            </div>
          </div>
        </div>
      </Transition>
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
.app-main {
  flex: 1;
  overflow: hidden;
  position: relative;
}
.loading-overlay-global {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(10, 10, 14, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  pointer-events: all;
}
.loading-card {
  background: #18181b;
  border: 1px solid #2a2a3a;
  border-radius: 8px;
  padding: 24px 32px;
  min-width: 300px;
  text-align: center;
}
.loading-bar-track {
  width: 100%;
  height: 6px;
  background: #2a2a3a;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 12px;
}
.loading-bar-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.loading-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.loading-msg {
  color: #a1a1aa;
  font-size: 13px;
}
.loading-pct {
  color: #3b82f6;
  font-size: 14px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 24px;
  height: 48px;
  background: #111114;
  border-bottom: 1px solid #1e1e2e;
  flex-shrink: 0;
}
.logo {
  font-family: 'Inter', sans-serif;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.5px;
  color: #e0e0e0;
}
.logo .accent {
  color: #c8ff00;
}
nav {
  display: flex;
  gap: 20px;
}
nav a {
  color: #666;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  transition: color 0.15s;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
nav a:hover, nav a.router-link-active {
  color: #c8ff00;
}
.session-info {
  margin-left: auto;
  color: #777;
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
}
</style>
