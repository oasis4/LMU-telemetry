<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const router = useRouter()
const driverInput = ref('')
const dragging = ref(false)
const fileInput = ref(null)

onMounted(() => {
  store.fetchSessions()
  store.fetchLoadedSessions()
})

async function openSession(filename) {
  await store.loadSession(filename, driverInput.value.trim())
  if (store.sessionId) {
    router.push({ name: 'laps', params: { sessionId: store.sessionId } })
  }
}

function goToCompare() {
  router.push({ name: 'compare' })
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFiles(files) {
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith('.duckdb')) continue
    const result = await store.uploadFile(file, driverInput.value.trim())
    if (result) {
      router.push({ name: 'laps', params: { sessionId: result.session_id } })
      return
    }
  }
}

function onFileChange(e) {
  if (e.target.files?.length) handleFiles(e.target.files)
  e.target.value = ''
}

function onDrop(e) {
  dragging.value = false
  if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files)
}

function onDragOver(e) {
  e.preventDefault()
  dragging.value = true
}

function onDragLeave() {
  dragging.value = false
}
</script>

<template>
  <div class="session-loader">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>Sessions</h2>
        <span class="text-muted">{{ store.sessions.length }} files</span>
      </div>

      <!-- Driver name input -->
      <div class="driver-input-area">
        <label class="driver-label">Driver name</label>
        <input
          v-model="driverInput"
          class="driver-input"
          placeholder="Enter driver name…"
          @keydown.enter.prevent
        />
      </div>

      <div class="session-list">
        <div v-if="store.sessions.length === 0 && !store.loading" class="empty">
          <p>No sessions yet.</p>
          <p class="text-muted">Upload .duckdb files to get started.</p>
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

      <!-- Loaded sessions summary -->
      <div class="loaded-area" v-if="store.loadedSessions.length">
        <div class="loaded-header">
          <h3>Loaded ({{ store.loadedSessions.length }})</h3>
          <button class="btn-compare" @click="goToCompare" v-if="store.drivers.length >= 2">
            Compare Drivers →
          </button>
        </div>
        <div class="loaded-list">
          <div v-for="ls in store.loadedSessions" :key="ls.session_id" class="loaded-item">
            <span class="driver-badge">{{ ls.driver || 'Unknown' }}</span>
            <span class="loaded-name">{{ ls.filename }}</span>
            <span class="loaded-laps">{{ ls.lap_count }} laps</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Main area: upload zone -->
    <div
      class="hero-area"
      :class="{ 'drag-over': dragging }"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop.prevent="onDrop"
    >
      <!-- Loading state handled by global overlay in App.vue -->

      <div class="hero-content">
        <h1>LMU <span class="text-blue">Telemetry</span> Analyzer</h1>
        <p class="text-muted">Drop .duckdb files here or click to upload</p>

        <!-- Upload zone -->
        <div class="upload-zone" @click="triggerUpload">
          <input ref="fileInput" type="file" accept=".duckdb" multiple hidden @change="onFileChange" />
          <div class="upload-icon">📂</div>
          <div class="upload-label">Drop .duckdb files or <span class="text-blue">browse</span></div>
          <div class="upload-hint text-muted">Supports Le Mans Ultimate telemetry files</div>
        </div>

        <div v-if="store.error" class="error-msg">{{ store.error }}</div>

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
            <div class="feature-icon">👥</div>
            <div>Multi-driver corner comparison</div>
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
.driver-input-area {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.driver-label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.driver-input {
  width: 100%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 6px 10px;
  font-size: 13px;
  font-family: var(--font-sans);
  box-sizing: border-box;
}
.driver-input::placeholder {
  color: var(--text-muted);
}
.loaded-area {
  border-top: 1px solid var(--border);
  padding: 12px 16px;
  max-height: 220px;
  overflow-y: auto;
}
.loaded-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.loaded-header h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.btn-compare {
  background: var(--accent-blue);
  color: #fff;
  border: none;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-compare:hover {
  opacity: 0.85;
}
.loaded-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.loaded-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}
.driver-badge {
  background: var(--accent-blue);
  color: #fff;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}
.loaded-name {
  font-family: var(--font-mono);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.loaded-laps {
  white-space: nowrap;
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
.hero-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: background 0.2s;
}
.hero-area.drag-over {
  background: rgba(59, 130, 246, 0.06);
  outline: 2px dashed var(--accent-blue);
  outline-offset: -12px;
}
.hero-content {
  text-align: center;
  max-width: 520px;
}
.hero-content h1 {
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin-bottom: 8px;
}
.hero-content > p {
  margin-bottom: 24px;
}

/* Upload zone */
.upload-zone {
  border: 2px dashed var(--border);
  padding: 32px 24px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 24px;
}
.upload-zone:hover {
  border-color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.04);
}
.upload-icon {
  font-size: 32px;
  margin-bottom: 8px;
}
.upload-label {
  font-size: 14px;
  margin-bottom: 4px;
}
.upload-hint {
  font-size: 11px;
}

/* Error */
.error-msg {
  color: var(--negative);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 8px 12px;
  font-size: 12px;
  margin-bottom: 16px;
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
