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

const mountMap = (cornerProps) =>
  mount(CornerMap, { props: { map: squareMap(), corner: cornerProps, approachM: 150 } })

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
