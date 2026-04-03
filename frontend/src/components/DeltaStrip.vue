<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'

const props = defineProps({
  distanceRange: { type: Object, default: null },
})

const store = useTelemetryStore()
const canvasRef = ref(null)
let observer = null

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const rect = canvas.getBoundingClientRect()
  const w = rect.width
  const h = 32
  canvas.width = w * devicePixelRatio
  canvas.height = h * devicePixelRatio
  canvas.style.width = w + 'px'
  canvas.style.height = h + 'px'
  ctx.scale(devicePixelRatio, devicePixelRatio)

  ctx.fillStyle = '#0d0d0f'
  ctx.fillRect(0, 0, w, h)

  const d = store.delta
  if (!d || !d.distance?.length) {
    ctx.fillStyle = '#333'
    ctx.font = '10px Inter'
    ctx.textAlign = 'center'
    ctx.fillText('No delta data', w / 2, h / 2 + 3)
    return
  }

  let dist = d.distance
  let delta = d.delta
  // Filter by distance range
  if (props.distanceRange) {
    const { min, max } = props.distanceRange
    const si = dist.findIndex(dd => dd >= min)
    const ei = dist.findIndex(dd => dd > max)
    const startI = Math.max(0, si)
    const endI = ei > 0 ? ei : dist.length
    dist = dist.slice(startI, endI)
    delta = delta.slice(startI, endI)
  }

  if (dist.length === 0) return

  const dMin = dist[0]
  const dMax = dist[dist.length - 1]
  const dRange = dMax - dMin || 1
  const maxDelta = Math.max(0.001, ...delta.map(Math.abs))

  for (let i = 0; i < dist.length - 1; i++) {
    const x = ((dist[i] - dMin) / dRange) * w
    const xNext = ((dist[i + 1] - dMin) / dRange) * w
    const val = delta[i]
    const barH = (Math.abs(val) / maxDelta) * (h / 2)

    if (val > 0) {
      ctx.fillStyle = 'rgba(239,68,68,0.7)' // losing = red
      ctx.fillRect(x, h / 2, xNext - x + 1, barH)
    } else {
      ctx.fillStyle = 'rgba(34,197,94,0.7)' // gaining = green
      ctx.fillRect(x, h / 2 - barH, xNext - x + 1, barH)
    }
  }

  // Center line
  ctx.strokeStyle = '#555'
  ctx.lineWidth = 0.5
  ctx.beginPath()
  ctx.moveTo(0, h / 2)
  ctx.lineTo(w, h / 2)
  ctx.stroke()
}

const deltaWatch = computed(() => [store.delta, props.distanceRange])
import { watch } from 'vue'
watch(deltaWatch, draw, { deep: true })

onMounted(() => {
  draw()
  observer = new ResizeObserver(draw)
  if (canvasRef.value) observer.observe(canvasRef.value)
})
onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="delta-strip">
    <canvas ref="canvasRef" class="delta-canvas"></canvas>
  </div>
</template>

<style scoped>
.delta-strip {
  height: 32px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.delta-canvas {
  display: block;
  width: 100%;
  height: 32px;
}
</style>
