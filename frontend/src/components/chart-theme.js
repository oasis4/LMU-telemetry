/**
 * Shared uPlot chrome, so both charts read as one system.
 *
 * uPlot draws light by default. Everything here is one shade off the surface:
 * hairline gridlines, solid never dashed - dashing reads as "projection" when
 * it is only a grid.
 */

const INK_MUTED = '#7d858f'
const GRID = '#22262d'
const AXIS = '#333a44'

export const SERIES = {
  reference: '#898781',
  compared: '#3987e5',
  loss: '#e66767',
  gain: '#199e70',
}

function axis(label, values) {
  return {
    label,
    labelSize: 20,
    labelFont: '11px system-ui, sans-serif',
    font: '11px system-ui, sans-serif',
    stroke: INK_MUTED,
    grid: { stroke: GRID, width: 1 },
    ticks: { stroke: AXIS, width: 1, size: 4 },
    values,
  }
}

/** The options every chart here shares. */
export function baseOptions({ width, height, xLabel, yLabel, yValues }) {
  return {
    width,
    height,
    // A crosshair plus the legend readout is the hover layer; uPlot's legend
    // doubles as the tooltip, showing every series at the cursor's x.
    cursor: {
      drag: { x: true, y: false },
      x: true,
      y: false,
      points: { size: 7, width: 2 },
    },
    scales: { x: { time: false } },
    axes: [axis(xLabel), axis(yLabel, yValues)],
    legend: { live: true },
  }
}

/** A horizontal rule at y = 0, drawn beneath the data. */
export function zeroLine(u) {
  const { ctx } = u
  if (u.scales.y.min > 0 || u.scales.y.max < 0) return
  const y = u.valToPos(0, 'y', true)
  ctx.save()
  ctx.strokeStyle = AXIS
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(u.bbox.left, y)
  ctx.lineTo(u.bbox.left + u.bbox.width, y)
  ctx.stroke()
  ctx.restore()
}
