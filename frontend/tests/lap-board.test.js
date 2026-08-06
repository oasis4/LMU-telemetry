import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import LapBoard from '../src/components/LapBoard.vue'

let counter = 0
function recording(patch = {}) {
  counter += 1
  return {
    name: `rec-${counter}.duckdb`,
    track: 'Monza',
    layout: 'Monza',
    car: 'Team WRT 2025 #46:LM',
    car_class: 'GT3',
    driver: 'Oasis Mueller',
    session_type: 'Qualify',
    clean_laps: 4,
    best_lap: 2,
    best_lap_s: 111.0,
    ...patch,
  }
}

const nothing = { reference: null, referenceLap: null, other: null, otherLap: null }

function board(sessions, selection = nothing, loadLaps = vi.fn()) {
  return mount(LapBoard, { props: { sessions, selection, loadLaps } })
}

const times = (wrapper) => wrapper.findAll('.row .time').map((n) => n.text())

describe('the lap board', () => {
  it('lists the quickest usable lap first', () => {
    const wrapper = board([
      recording({ best_lap_s: 113.5 }),
      recording({ best_lap_s: 111.0 }),
      recording({ best_lap_s: 112.25 }),
    ])
    expect(times(wrapper)).toEqual(['1:51.000', '1:52.250', '1:53.500'])
  })

  it('sorts a recording with no usable lap last, not first', () => {
    // `null` compares below every number, so the plain comparison puts the
    // recording that has nothing to offer at the top of the board.
    const wrapper = board([
      recording({ best_lap: null, best_lap_s: null }),
      recording({ best_lap_s: 111.0 }),
    ])
    expect(times(wrapper)).toEqual(['1:51.000', '—'])
  })

  it('says why a recording cannot be chosen instead of dropping it', () => {
    const wrapper = board([recording({ best_lap: null, best_lap_s: null })])
    expect(wrapper.text()).toContain('no usable lap')
    expect(wrapper.findAll('.side').every((b) => b.attributes('disabled') !== undefined))
      .toBe(true)
  })

  it('shows one circuit at a time, because a comparison across two is refused', () => {
    const wrapper = board([
      recording({ track: 'Monza', layout: 'Monza' }),
      recording({ track: 'Monza', layout: 'Monza' }),
      recording({ track: 'Spa', layout: 'Spa' }),
    ])
    expect(wrapper.findAll('.row')).toHaveLength(2)
    expect(wrapper.findAll('option')).toHaveLength(2)
  })

  it('opens on the circuit with the most to compare on', () => {
    const wrapper = board([
      recording({ track: 'Spa', layout: 'Spa' }),
      recording({ track: 'Monza', layout: 'Monza' }),
      recording({ track: 'Monza', layout: 'Monza' }),
    ])
    expect(wrapper.find('select').element.value).toBe('Monza|Monza')
  })

  it('chooses a lap without asking the server for one', async () => {
    // The listing already carries each recording's best usable lap and its
    // number, so the first pick is a click and not a round trip.
    const loadLaps = vi.fn()
    const one = recording({ best_lap: 3, best_lap_s: 110.5 })
    const wrapper = board([one], nothing, loadLaps)

    await wrapper.find('.side.reference').trigger('click')

    expect(loadLaps).not.toHaveBeenCalled()
    expect(wrapper.emitted('select')).toEqual([
      [{ side: 'reference', name: one.name, lap: 3 }],
    ])
  })

  it('reads a recording’s other laps only when it is opened', async () => {
    const loadLaps = vi.fn().mockResolvedValue([
      { number: 1, duration_s: 113.0, clean: true, reason: null },
      { number: 2, duration_s: 999.0, clean: false, reason: 'the lap touched the pit lane' },
    ])
    const wrapper = board([recording()], nothing, loadLaps)
    expect(loadLaps).not.toHaveBeenCalled()

    await wrapper.find('.expand').trigger('click')
    await new Promise((resolve) => setTimeout(resolve))

    expect(loadLaps).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.lap')).toHaveLength(2)
    expect(wrapper.find('.lap:disabled').text()).toContain('the lap touched the pit lane')
  })

  it('offers a class filter only when the circuit has more than one class', () => {
    const one = board([recording({ car_class: 'GT3' }), recording({ car_class: 'GT3' })])
    expect(one.findAll('.chip')).toHaveLength(0)

    const two = board([recording({ car_class: 'GT3' }), recording({ car_class: 'Hyper' })])
    expect(two.findAll('.chip').map((c) => c.text())).toEqual(['GT3', 'Hyper'])
  })

  it('narrows the board to a chosen class', async () => {
    const wrapper = board([
      recording({ car_class: 'Hyper', best_lap_s: 100.0 }),
      recording({ car_class: 'GT3', best_lap_s: 111.0 }),
    ])
    await wrapper.findAll('.chip').find((c) => c.text() === 'GT3').trigger('click')
    expect(times(wrapper)).toEqual(['1:51.000'])
  })

  it('shows the gap to the quickest lap on the board', () => {
    const wrapper = board([
      recording({ best_lap_s: 111.0 }),
      recording({ best_lap_s: 112.25 }),
    ])
    expect(wrapper.findAll('.row .behind').map((n) => n.text())).toEqual(['', '+1.250'])
  })

  it('names the entry as recorded and keeps its series apart from it', () => {
    // `CarName` is the entry, not the vehicle - the file has no field naming
    // the model, so none is shown.
    const wrapper = board([recording({ car: 'Team WRT 2025 #46:LM' })])
    expect(wrapper.find('.car').text()).toContain('Team WRT 2025 #46')
    expect(wrapper.find('.car .series').text()).toBe('LM')
  })

  it('folds itself away once there are two laps to look at', async () => {
    const wrapper = board([recording(), recording()])
    expect(wrapper.findAll('.row')).toHaveLength(2)

    await wrapper.setProps({
      selection: { reference: 'rec-1.duckdb', referenceLap: 2,
                   other: 'rec-2.duckdb', otherLap: 2 },
    })
    expect(wrapper.findAll('.row')).toHaveLength(0)
    expect(wrapper.find('.fold').text()).toBe('change laps')
  })

  it('stays open while only one side has been chosen', async () => {
    const wrapper = board([recording(), recording()])
    await wrapper.setProps({
      selection: { ...nothing, reference: 'rec-1.duckdb', referenceLap: 2 },
    })
    expect(wrapper.findAll('.row')).toHaveLength(2)
  })
})
