import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CornerMap from '../src/components/CornerMap.vue'

/** A 400-point square circuit, 4000 m round, so positions are checkable. */
function squareMap() {
  const x = [], y = []
  for (let i = 0; i < 400; i += 1) {
    const t = i / 100
    if (t < 1) { x.push(t * 1000); y.push(0) }
    else if (t < 2) { x.push(1000); y.push((t - 1) * 1000) }
    else if (t < 3) { x.push(1000 - (t - 2) * 1000); y.push(1000) }
    else { x.push(0); y.push(1000 - (t - 3) * 1000) }
  }
  return { track_length_m: 4000, x: Float64Array.from(x), y: Float64Array.from(y) }
}

const corner = (patch = {}) => ({
  index: 2, name: 'T2', start_m: 900, apex_m: 1000, end_m: 1100, ...patch,
})

const mountMap = (cornerProps, extra = {}) =>
  mount(CornerMap, {
    props: { map: squareMap(), corner: cornerProps, approachM: 150, ...extra },
  })

/** A lap on the same 400-point grid, braking wherever `brakes` says so. */
function lap(brakes) {
  const map = squareMap()
  const brake = new Float64Array(400)
  for (const [first, last] of brakes) {
    for (let i = first; i < last; i += 1) brake[i] = 0.8
  }
  return { x: map.x, y: map.y, brake }
}

const attrs = (wrapper, selector) => wrapper.find(selector)

describe('the corner map', () => {
  it('marks the apex where the corner says it is', () => {
    const wrapper = mountMap(corner())
    const circle = attrs(wrapper, 'circle')
    expect(circle.exists()).toBe(true)
    expect(Number(circle.attributes('cx'))).toBeGreaterThan(0)
    expect(Number(circle.attributes('cy'))).not.toBeNaN()
  })

  it('draws no apex at all when the corner does not carry one', () => {
    // The comparison's corners had no `apex_m`, and dividing `undefined` by a
    // metres-per-point produced `<circle cx="NaN">` - which the browser
    // rejects and then ignores, so the marker vanished without a word.
    const wrapper = mountMap(corner({ apex_m: undefined }))
    expect(wrapper.find('circle').exists()).toBe(false)
    expect(wrapper.find('text').exists()).toBe(false)
  })

  it('never writes a non-number into the drawing', () => {
    for (const apex of [undefined, null, NaN, 'nope']) {
      const wrapper = mountMap(corner({ apex_m: apex }))
      for (const attribute of ['cx', 'cy', 'x', 'y', 'd']) {
        for (const node of wrapper.findAll(`[${attribute}]`)) {
          expect(node.attributes(attribute)).not.toContain('NaN')
        }
      }
    }
  })

  it('still draws the line when the apex is missing', () => {
    // The marker is one detail; losing it must not cost the shape.
    const wrapper = mountMap(corner({ apex_m: undefined }))
    expect(attrs(wrapper, 'path.reference-line').attributes('d')).toMatch(/^M[\d.]/)
  })
})

describe('where the car was braking', () => {
  // The corner sits at 900-1100 m of a 4000 m circuit on 400 points, so one
  // point is 10 m and the window (150 m either side) is points 75..125.
  const inWindow = [[80, 100]]

  it('draws the braking stretch on top of the lap it belongs to', () => {
    const wrapper = mountMap(corner(), { other: lap(inWindow) })
    const braking = wrapper.findAll('path.braking.other')
    expect(braking).toHaveLength(1)
    expect(braking[0].attributes('d')).toMatch(/^M[\d.]+,[\d.]+L/)
  })

  it('marks where the braking began', () => {
    const wrapper = mountMap(corner(), { other: lap(inWindow) })
    const dots = wrapper.findAll('circle.brake-start.other')
    expect(dots).toHaveLength(1)
    expect(Number(dots[0].attributes('cx'))).not.toBeNaN()
  })

  it('keeps two applications apart instead of joining them', () => {
    // A lift and a re-application inside one corner. Drawn as one path, the
    // line would run straight across the part where the driver was off the
    // pedal - which is the part worth seeing.
    const wrapper = mountMap(corner(), { other: lap([[80, 90], [100, 115]]) })
    expect(wrapper.findAll('path.braking.other')).toHaveLength(2)
    expect(wrapper.findAll('circle.brake-start.other')).toHaveLength(2)
  })

  it('draws nothing where the car was not braking', () => {
    const wrapper = mountMap(corner(), { other: lap([[10, 20]]) })  // far away
    expect(wrapper.findAll('path.braking.other')).toHaveLength(0)
    expect(wrapper.findAll('circle.brake-start.other')).toHaveLength(0)
  })

  it('uses the threshold it was given, not one of its own', () => {
    const gentle = { ...lap([]), brake: new Float64Array(400).fill(0.2) }
    const strict = mountMap(corner(), { other: gentle, brakeOn: 0.5 })
    const loose = mountMap(corner(), { other: gentle, brakeOn: 0.05 })
    expect(strict.findAll('path.braking.other')).toHaveLength(0)
    expect(loose.findAll('path.braking.other')).toHaveLength(1)
  })

  it('shows each lap its own braking', () => {
    const wrapper = mountMap(corner(), {
      reference: lap([[80, 95]]), other: lap([[85, 105]]),
    })
    expect(wrapper.findAll('path.braking.reference')).toHaveLength(1)
    expect(wrapper.findAll('path.braking.other')).toHaveLength(1)
    const at = (s) => wrapper.find(`circle.brake-start.${s}`).attributes('cx')
    expect(at('reference')).not.toBe(at('other'))
  })

  it('says nothing about braking for a lap that carries no brake channel', () => {
    const map = squareMap()
    const wrapper = mountMap(corner(), { other: { x: map.x, y: map.y } })
    expect(wrapper.findAll('path.braking')).toHaveLength(0)
  })

  it('ignores a single sample over the threshold', () => {
    // One sample is a dot, not a stretch, and `M x,y` with nothing after it
    // draws nothing while still claiming a brake point.
    const wrapper = mountMap(corner(), { other: lap([[90, 91]]) })
    expect(wrapper.findAll('path.braking.other')).toHaveLength(0)
    expect(wrapper.findAll('circle.brake-start.other')).toHaveLength(0)
  })
})
