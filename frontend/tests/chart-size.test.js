import { describe, expect, it } from 'vitest'
import { defineComponent, h, ref, shallowRef } from 'vue'
import { mount } from '@vue/test-utils'

import { useChartSize } from '../src/components/useChartSize.js'

/** A stand-in for a uPlot instance: it only needs a width and setSize. */
function fakeChart(width) {
  return { width, height: 0, calls: 0, setSize({ width: w, height: h }) {
    this.width = w
    this.height = h
    this.calls += 1
  } }
}

/** A host whose available width the test controls, as a card would. */
function mountWith(available, chart, height = 200) {
  let fit
  const Component = defineComponent({
    setup() {
      const host = ref(null)
      const instance = shallowRef(chart)
      fit = useChartSize(host, instance, () => height)
      return () => h('div', { ref: host })
    },
  })
  const wrapper = mount(Component, { attachTo: document.body })
  const el = wrapper.element
  Object.defineProperty(el, 'clientWidth', { get: () => available(), configurable: true })
  return { wrapper, fit }
}

describe('keeping a chart the width of its host', () => {
  it('resizes the chart to the width its host is allowed', () => {
    const chart = fakeChart(982)
    let width = 309
    const { fit, wrapper } = mountWith(() => width, chart)
    fit()
    expect(chart.width).toBe(309)
    wrapper.unmount()
  })

  it('grows the chart again when the host does', () => {
    // The failure that prompted this: charts shrank on a narrow viewport and
    // stayed narrow when it widened, leaving a 293 px plot in a 982 px card.
    const chart = fakeChart(309)
    let width = 309
    const { fit, wrapper } = mountWith(() => width, chart)
    width = 982
    fit()
    expect(chart.width).toBe(982)
    wrapper.unmount()
  })

  it('does nothing when the width has not really changed', () => {
    // A one-pixel difference is a rounding artefact. Acting on it makes a
    // ResizeObserver fire again and never settle.
    const chart = fakeChart(500)
    const { fit, wrapper } = mountWith(() => 500.4, chart)
    const before = chart.calls
    fit()
    fit()
    expect(chart.calls).toBe(before)
    wrapper.unmount()
  })

  it('ignores a host with no width rather than collapsing the chart', () => {
    // A card that is hidden reports zero, and a chart resized to zero never
    // comes back on its own.
    const chart = fakeChart(800)
    const { fit, wrapper } = mountWith(() => 0, chart)
    fit()
    expect(chart.width).toBe(800)
    wrapper.unmount()
  })

  it('fits on a window resize', () => {
    const chart = fakeChart(982)
    let width = 400
    const { wrapper } = mountWith(() => width, chart)
    window.dispatchEvent(new Event('resize'))
    expect(chart.width).toBe(400)
    wrapper.unmount()
  })

  it('does not resize a chart whose component is gone', () => {
    const chart = fakeChart(982)
    const { wrapper } = mountWith(() => 400, chart)
    wrapper.unmount()
    const calls = chart.calls
    window.dispatchEvent(new Event('resize'))
    expect(chart.calls).toBe(calls)
  })

  it('removes its resize listener on unmount', () => {
    // The test above passes with or without the cleanup, because Vue nulls a
    // template ref on unmount and fit() bails on a missing host. It proves the
    // guard, not the cleanup - so the cleanup gets its own assertion, or a
    // listener leaks once per chart for the life of the page.
    const added = []
    const removed = []
    const realAdd = window.addEventListener.bind(window)
    const realRemove = window.removeEventListener.bind(window)
    window.addEventListener = (type, fn, ...rest) => {
      if (type === 'resize') added.push(fn)
      return realAdd(type, fn, ...rest)
    }
    window.removeEventListener = (type, fn, ...rest) => {
      if (type === 'resize') removed.push(fn)
      return realRemove(type, fn, ...rest)
    }
    try {
      const { wrapper } = mountWith(() => 400, fakeChart(982))
      expect(added).toHaveLength(1)
      wrapper.unmount()
      expect(removed).toEqual(added)
    } finally {
      window.addEventListener = realAdd
      window.removeEventListener = realRemove
    }
  })
})
