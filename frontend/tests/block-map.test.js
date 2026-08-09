import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import BlockMap from '../src/components/BlockMap.vue'

/** A square circuit, 400 points over 4000 m, so 10 m to a point. */
function squareMap() {
  const x = [], y = []
  for (let i = 0; i < 400; i += 1) {
    const t = i / 100
    if (t < 1) { x.push(t * 1000); y.push(0) }
    else if (t < 2) { x.push(1000); y.push((t - 1) * 1000) }
    else if (t < 3) { x.push(1000 - (t - 2) * 1000); y.push(1000) }
    else { x.push(0); y.push(1000 - (t - 3) * 1000) }
  }
  return {
    track: 'Square', track_length_m: 4000, samples: 400,
    x: Float64Array.from(x), y: Float64Array.from(y),
  }
}

const block = (index, startM, endM, lap) => ({
  index, name: `block ${index}`, corners: [index], lap_number: lap,
  start_m: startM, end_m: endM, wraps: startM > endM,
  time_s: 20 + index, gain_s: 0,
})

const BLOCKS = [
  block(1, 3600, 800, 2),   // holds the start/finish line
  block(2, 800, 2000, 3),
  block(3, 2000, 3600, 2),
]

const SEAMS = [
  { at_m: 3600, speed_spread_kmh: 1.2, sound: true },
  { at_m: 800, speed_spread_kmh: 18.0, sound: false },
  { at_m: 2000, speed_spread_kmh: 2.0, sound: true },
]

function draw(props = {}) {
  return mount(BlockMap, {
    props: { map: squareMap(), blocks: BLOCKS, seams: SEAMS, ...props },
  })
}

describe('the block map', () => {
  it('draws one stroke per block', () => {
    expect(draw().findAll('path.block')).toHaveLength(3)
  })

  it('splits the block holding the start/finish line into two runs', () => {
    // Read as one range it is empty, and the block would vanish from the map
    // with nothing saying so.
    const d = draw().findAll('path.block')[0].attributes('d')
    expect(d.match(/M/g)).toHaveLength(2)
  })

  it('labels every block with the lap it came from', () => {
    // Colour alone would fail a CVD reader. The number is the answer; the
    // colour only groups.
    const labels = draw().findAll('text.label').map((t) => t.text())
    expect(labels).toEqual(['2', '3', '2'])
  })

  it('gives two blocks from one lap the same colour, and a third its own', () => {
    const classes = draw().findAll('path.block').map((p) => p.attributes('class'))
    const slot = (c) => c.match(/slot-\d/)[0]
    expect(slot(classes[0])).toBe(slot(classes[2]))
    expect(slot(classes[0])).not.toBe(slot(classes[1]))
  })

  it('keeps a lap on its colour however the blocks are ordered', () => {
    // Slots come from the sorted set of lap numbers, not from first
    // appearance, so re-picking one block does not recolour the whole map.
    const first = draw().findAll('path.block').map((p) => p.attributes('class'))
    const shuffled = draw({ blocks: [BLOCKS[1], BLOCKS[0], BLOCKS[2]] })
      .findAll('path.block').map((p) => p.attributes('class'))
    const slot = (c) => c.match(/slot-\d/)[0]
    expect(slot(shuffled[1])).toBe(slot(first[0]))
  })

  it('marks only the joins that do not hold', () => {
    // A mark on every join would make the mark mean "join" rather than
    // "look at this one".
    expect(draw().findAll('circle.seam-bad')).toHaveLength(1)
  })

  it('says how far apart the laps were at a join that does not hold', () => {
    expect(draw().find('circle.seam-bad title').text()).toContain('18.0 km/h')
  })

  it('draws nothing about seams when every join holds', () => {
    const sound = SEAMS.map((s) => ({ ...s, sound: true }))
    expect(draw({ seams: sound }).findAll('circle.seam-bad')).toHaveLength(0)
  })

  it('reports which block was picked', async () => {
    const wrapper = draw()
    await wrapper.findAll('path.block')[1].trigger('click')
    expect(wrapper.emitted('select')[0][0].index).toBe(2)
  })

  it('marks the selected block so the table and the map agree', () => {
    const wrapper = draw({ selected: 2 })
    const classes = wrapper.findAll('path.block').map((p) => p.attributes('class'))
    expect(classes[1]).toContain('selected')
    expect(classes[0]).not.toContain('selected')
  })

  it('names the block and its lap where a pointer rests', () => {
    const title = draw().findAll('path.block title')[1].text()
    expect(title).toContain('block 2')
    expect(title).toContain('lap 3')
  })
})
