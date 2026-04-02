<script setup>
import { computed, ref } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'
import TrackMap from '../components/TrackMap.vue'
import TelemetryChart from '../components/TelemetryChart.vue'
import CornerList from '../components/CornerList.vue'
import DeltaStrip from '../components/DeltaStrip.vue'
import CoachingTip from '../components/CoachingTip.vue'

const props = defineProps({ sessionId: String })
const store = useTelemetryStore()

const activeTab = ref('speed')
const tabs = ['speed', 'throttle', 'brake', 'steering', 'gear', 'rpm']

const distanceRange = computed(() => {
  if (store.activeCorner) {
    return {
      min: store.activeCorner.distance_start - 50,
      max: store.activeCorner.distance_end + 50,
    }
  }
  return null
})
</script>

<template>
  <div class="analysis-layout">
    <!-- Track Map (top) -->
    <div class="track-map-area">
      <TrackMap :distance-range="distanceRange" />
    </div>

    <!-- Bottom area: corner list + charts -->
    <div class="bottom-area">
      <!-- Corner sidebar -->
      <div class="corner-sidebar">
        <CornerList />
      </div>

      <!-- Main chart area -->
      <div class="chart-area">
        <div class="tab-bar">
          <button
            v-for="t in tabs"
            :key="t"
            :class="{ active: activeTab === t }"
            @click="activeTab = t"
          >
            {{ t }}
          </button>
        </div>

        <div class="chart-container">
          <TelemetryChart :channel="activeTab" :distance-range="distanceRange" />
        </div>

        <!-- Delta strip -->
        <DeltaStrip :distance-range="distanceRange" />

        <!-- Coaching tips -->
        <CoachingTip />
      </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-layout {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.track-map-area {
  height: 30%;
  min-height: 180px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.bottom-area {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.corner-sidebar {
  width: 200px;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
}
.chart-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chart-container {
  flex: 1;
  overflow: hidden;
  position: relative;
}
</style>
