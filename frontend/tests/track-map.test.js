import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import TrackMap from '../src/components/TrackMap.vue'

/** A square circuit, 400 points, so the geometry is checkable by hand. */
function squareMap(corners = []) {
  const x = [], y = []
  for (let i = 0; i < 400; i += 1) {
    const t = i / 100
    if (t < 1) { x.push(t * 1000); y.push(0) }
    else if (t < 2) { x.push(1000); y.push((t - 1) * 1000) }
    else if (t < 3) { x.push(1000 - (t - 2) * 1000); y.push(1000) }
    else { x.push(0); y.push(1000 - (t - 3) * 1000) }
  }
  return {
    track: 'Square', layout: 'Square', track_length_m: 4000, samples: 400,
    x: Float64Array.from(x), y: Float64Array.from(y), corners,
  }
}

const corner = (index, spans) => ({
  index, name: `T${index}`, direction: 'L', apex_m: index * 1000, spans,
})

describe('the track map', () => {
  it('draws one closed outline from the points it was given', () => {
    const wrapper = mount(TrackMap, { props: { map: squareMap() } })
    const d = wrapper.find('path.outline').attributes('d')
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d.split('L')).toHaveLength(400)
  })

  function drawnPoints(wrapper) {
    return wrapper.find('path.outline').attributes('d')
      .replace('M', '').replace('Z', '')
      .split('L').map((p) => p.split(',').map(Number))
  }

  it('keeps the circuit’s proportions instead of filling the box', () => {
    // A 2:1 circuit stretched to a square is no longer that circuit. Scaling
    // each axis to its own extent is the way that happens.
    const map = squareMap()
    for (let i = 0; i < map.y.length; i += 1) map.y[i] *= 0.5
    const points = drawnPoints(mount(TrackMap, { props: { map, size: 500 } }))

    const xs = points.map((p) => p[0])
    const ys = points.map((p) => p[1])
    const width = Math.max(...xs) - Math.min(...xs)
    const height = Math.max(...ys) - Math.min(...ys)
    expect(height / width).toBeCloseTo(0.5, 1)
  })

  it('stays inside its own box whichever way the circuit is longer', () => {
    // Scaling to the width alone keeps the proportions but overflows the
    // viewBox on a circuit that is taller than it is wide, and the top and
    // bottom of it are then simply not drawn.
    const map = squareMap()
    for (let i = 0; i < map.x.length; i += 1) map.x[i] *= 0.3
    const points = drawnPoints(mount(TrackMap, { props: { map, size: 500 } }))

    for (const [px, py] of points) {
      expect(px).toBeGreaterThanOrEqual(0)
      expect(px).toBeLessThanOrEqual(500)
      expect(py).toBeGreaterThanOrEqual(0)
      expect(py).toBeLessThanOrEqual(500)
    }
  })

  it('draws the circuit the right way up', () => {
    // SVG's y grows downward. Drawn without flipping, every circuit is
    // mirrored - which is subtle enough to ship unnoticed.
    const wrapper = mount(TrackMap, { props: { map: squareMap(), size: 500 } })
    const points = wrapper.find('path.outline').attributes('d')
      .replace('M', '').replace('Z', '').split('L').map((p) => p.split(',').map(Number))

    // Sample 0 is at y=0 (the bottom), sample 150 at y=1000 (the top).
    expect(points[0][1]).toBeGreaterThan(points[150][1])
  })

  it('draws a corner as a slice of the same line', () => {
    const wrapper = mount(TrackMap, {
      props: { map: squareMap([corner(1, [[100, 141]])]) },
    })
    const d = wrapper.find('path.corner').attributes('d')
    expect(d.split('L')).toHaveLength(41)
  })

  it('draws a corner over the start/finish line as two pieces', () => {
    // Its two spans are at opposite ends of the array. Joined into one path
    // the line would be drawn straight across the whole circuit.
    const wrapper = mount(TrackMap, {
      props: { map: squareMap([corner(1, [[380, 400], [0, 20]])]) },
    })
    const d = wrapper.find('path.corner').attributes('d')
    expect(d.match(/M/g)).toHaveLength(2)
  })

  it('colours a corner by whether it cost time', () => {
    const wrapper = mount(TrackMap, {
      props: {
        map: squareMap([corner(1, [[0, 50]]), corner(2, [[100, 150]])]),
        losses: { 1: 0.4, 2: -0.3 },
      },
    })
    const classes = wrapper.findAll('path.corner').map((p) => p.classes())
    expect(classes[0]).toContain('loss')
    expect(classes[1]).toContain('gain')
  })

  it('leaves a corner uncoloured when no comparison has been made', () => {
    const wrapper = mount(TrackMap, {
      props: { map: squareMap([corner(1, [[0, 50]])]) },
    })
    expect(wrapper.find('path.corner').classes()).toContain('neutral')
  })

  it('reports which corner was clicked', async () => {
    const wrapper = mount(TrackMap, {
      props: { map: squareMap([corner(3, [[0, 50]])]) },
    })
    await wrapper.find('path.corner').trigger('click')
    expect(wrapper.emitted('select')[0][0].index).toBe(3)
  })

  it('marks where the lap starts', () => {
    const wrapper = mount(TrackMap, { props: { map: squareMap() } })
    expect(wrapper.find('circle.start').exists()).toBe(true)
  })
})
