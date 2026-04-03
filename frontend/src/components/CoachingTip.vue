<script setup>
import { computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()

const tip = computed(() => {
  if (!store.activeCorner || !store.activeTelemetry || !store.refTelemetry || !store.delta) {
    return null
  }

  const corner = store.activeCorner
  const active = store.activeTelemetry
  const ref = store.refTelemetry
  const delta = store.delta

  // Find delta at corner apex
  const deltaIdx = delta.distance.findIndex(d => d >= corner.distance_apex)
  const deltaAtApex = deltaIdx >= 0 ? delta.delta[deltaIdx] : 0

  if (Math.abs(deltaAtApex) < 0.05) return null // within 50ms, no tip

  const tips = []

  // Braking point analysis
  const entryIdx = active.distance.findIndex(d => d >= corner.distance_start)
  const apexIdx = active.distance.findIndex(d => d >= corner.distance_apex)

  if (entryIdx >= 0 && apexIdx >= 0) {
    // Find where braking begins (brake > 0.1)
    let activeBrakeStart = null
    let refBrakeStart = null

    for (let i = entryIdx; i < apexIdx; i++) {
      if (active.brake[i] > 0.1 && activeBrakeStart === null) {
        activeBrakeStart = active.distance[i]
      }
    }
    const refEntryIdx = ref.distance.findIndex(d => d >= corner.distance_start)
    const refApexIdx = ref.distance.findIndex(d => d >= corner.distance_apex)
    if (refEntryIdx >= 0 && refApexIdx >= 0) {
      for (let i = refEntryIdx; i < refApexIdx; i++) {
        if (ref.brake[i] > 0.1 && refBrakeStart === null) {
          refBrakeStart = ref.distance[i]
        }
      }
    }

    if (activeBrakeStart != null && refBrakeStart != null) {
      const diff = activeBrakeStart - refBrakeStart
      if (diff < -5) {
        tips.push(`You are braking ${Math.abs(diff).toFixed(0)}m earlier than reference. Try carrying more speed into the apex.`)
      } else if (diff > 5) {
        tips.push(`You are braking ${diff.toFixed(0)}m later than reference. Watch for missed apexes.`)
      }
    }

    // Min speed comparison
    const activeApexSpeed = active.speed[apexIdx]
    const refApexSpeed = refApexIdx >= 0 ? ref.speed[refApexIdx] : null
    if (activeApexSpeed != null && refApexSpeed != null) {
      const speedDiff = activeApexSpeed - refApexSpeed
      if (speedDiff < -3) {
        tips.push(`Apex speed is ${Math.abs(speedDiff).toFixed(0)} km/h slower than reference. Work on corner entry speed.`)
      }
    }

    // Throttle pickup
    if (apexIdx < active.distance.length - 10) {
      let activeThrottleOn = null
      let refThrottleOn = null
      for (let i = apexIdx; i < Math.min(apexIdx + 100, active.throttle.length); i++) {
        if (active.throttle[i] > 0.5 && activeThrottleOn === null) {
          activeThrottleOn = active.distance[i]
        }
      }
      if (refApexIdx >= 0) {
        for (let i = refApexIdx; i < Math.min(refApexIdx + 100, ref.throttle.length); i++) {
          if (ref.throttle[i] > 0.5 && refThrottleOn === null) {
            refThrottleOn = ref.distance[i]
          }
        }
      }
      if (activeThrottleOn != null && refThrottleOn != null) {
        const diff = activeThrottleOn - refThrottleOn
        if (diff > 5) {
          tips.push(`Throttle pickup is ${diff.toFixed(0)}m later than reference. Commit to throttle earlier on exit.`)
        }
      }
    }
  }

  if (tips.length === 0) {
    return deltaAtApex > 0
      ? `Losing ${(deltaAtApex * 1000).toFixed(0)}ms through ${corner.name}. Review entry speed and line.`
      : `Gaining ${Math.abs(deltaAtApex * 1000).toFixed(0)}ms through ${corner.name}. Good work!`
  }

  return tips.join(' ')
})
</script>

<template>
  <div class="coaching-tip" v-if="tip">
    <div class="tip-icon">💡</div>
    <div class="tip-text">{{ tip }}</div>
  </div>
</template>

<style scoped>
.coaching-tip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.tip-icon {
  font-size: 14px;
  flex-shrink: 0;
  margin-top: 1px;
}
.tip-text {
  flex: 1;
}
</style>
