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

describe('showing where the brakes went on', () => {
  const braking = {
    reference: [[900, 1100]],
    other: [[850, 1050], [1500, 1600]],
  }
  const withBraking = (extra = {}) =>
    mount(TrackMap, { props: { map: squareMap([corner(1, [[80, 120]])]), braking, ...extra } })

  it('offers the choice only when there is braking to show', () => {
    const without = mount(TrackMap, { props: { map: squareMap() } })
    expect(without.findAll('.modes button')).toHaveLength(0)
    expect(withBraking().findAll('.modes button').map((b) => b.text()))
      .toEqual(['time lost', 'braking'])
  })

  it('shows time lost until asked for braking', () => {
    const wrapper = withBraking()
    expect(wrapper.findAll('path.braking')).toHaveLength(0)
  })

  it('draws every zone of both laps once asked', async () => {
    const wrapper = withBraking()
    await wrapper.findAll('.modes button')[1].trigger('click')
    expect(wrapper.findAll('path.braking.reference')).toHaveLength(1)
    expect(wrapper.findAll('path.braking.other')).toHaveLength(2)
    expect(wrapper.findAll('circle.brake-start')).toHaveLength(3)
  })

  it('lays the reference down first, so the compared lap sits on top of it', async () => {
    // Both laps brake for the same corner, so the two zones overlap almost
    // exactly. Drawn in the other order - and at equal widths - the reference
    // disappeared underneath and the map showed one lap while claiming two.
    // The widths live in scoped CSS, which jsdom does not apply; what can be
    // asserted here is the paint order that makes those widths readable.
    const wrapper = withBraking()
    await wrapper.findAll('.modes button')[1].trigger('click')
    const drawn = [...wrapper.element.querySelectorAll('path.braking')]
      .map((p) => (p.getAttribute('class').includes('reference') ? 'reference' : 'other'))
    expect(drawn.indexOf('other')).toBeGreaterThan(drawn.lastIndexOf('reference'))
  })

  it('stops colouring corners by time while showing braking', async () => {
    // Two meanings on one stroke: the corner colouring already spends hue and
    // width on time lost, and braking over it would read as part of that.
    const wrapper = mount(TrackMap, {
      props: { map: squareMap([corner(1, [[80, 120]])]), braking, losses: { 1: 0.5 } },
    })
    expect(wrapper.find('path.corner').classes()).toContain('loss')
    await wrapper.findAll('.modes button')[1].trigger('click')
    expect(wrapper.find('path.corner').classes()).toContain('quiet')
    expect(wrapper.find('path.corner').classes()).not.toContain('loss')
  })

  it('says which lap braked where, and for how long', async () => {
    const wrapper = withBraking()
    await wrapper.findAll('.modes button')[1].trigger('click')
    const titles = wrapper.findAll('path.braking title').map((t) => t.text())
    expect(titles).toContain('reference — brakes at 900 m for 200 m')
    expect(titles).toContain('compared — brakes at 1500 m for 100 m')
  })

  it('draws a zone shorter than the map’s own spacing rather than nothing', async () => {
    // A 4000 m circuit on 400 points is 10 m per point, so a 2 m dab rounds
    // to one index at both ends - and `M x,y` with nothing after it draws
    // nothing at all, while the dot beside it still claims a brake point.
    const wrapper = mount(TrackMap, {
      props: { map: squareMap(), braking: { reference: [[1000, 1002]], other: [] } },
    })
    await wrapper.findAll('.modes button')[1].trigger('click')
    expect(wrapper.find('path.braking.reference').attributes('d')).toMatch(/L/)
  })
})
