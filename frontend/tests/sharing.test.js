import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SharingView from '../src/views/SharingView.vue'
import { useTelemetryStore } from '../src/stores/telemetry.js'
import { createClient } from '../src/api/client.js'

const mounted = []
afterEach(() => { mounted.forEach(w => w.unmount()); mounted.length = 0; vi.restoreAllMocks() })
function view(patch = {}) {
  const pinia = createPinia(); setActivePinia(pinia)
  const store = useTelemetryStore()
  const state = {
    settings: { publish_dir: '/sharing', public_url: '' },
    published: [{ id: 'published', track: 'Monza', lap: 2, duration_s: 111, driver: 'Me' }],
    friends: [{ id: 'friend', name: 'Alex', last_success: null, error: 'Private folder: enable Anyone with the link' }],
    laps: [{ id: 'shared', friend_name: 'Alex', info: { driver: 'Alex Driver', track: 'Monza' }, duration_s: 112, sharing_status: 'no_longer_shared' }],
    running: false, queued: false, ...patch,
  }
  store.sessions = [{ name: 'local.duckdb', track: 'Monza', driver: 'Me' }, { name: 'shared-abc', shared: true }]
  store.loadSessions = vi.fn(async () => {})
  Object.assign(store.client, {
    sharing: vi.fn(async () => state),
    laps: vi.fn(async () => [{ number: 0, clean: false }, { number: 2, clean: true, duration_s: 111 }]),
    shareLap: vi.fn(async () => ({})), stopSharing: vi.fn(async () => ({})),
    saveSharing: vi.fn(async () => ({})), addFriend: vi.fn(async () => ({})),
    removeFriend: vi.fn(async () => ({})), syncFriends: vi.fn(async () => ({ started: true })),
  })
  const wrapper = mount(SharingView, { global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  mounted.push(wrapper)
  return { wrapper, store, state }
}
function button(wrapper, text) { return wrapper.findAll('button').find(b => b.text() === text) }

describe('shared lap folders', () => {
  it('publishes only usable local laps and shows sync errors and retained copies', async () => {
    const { wrapper, store } = view(); await flushPromises()
    expect(wrapper.text()).toContain('No longer shared')
    expect(wrapper.text()).toContain('Private folder')
    const selects = wrapper.findAll('select')
    expect(selects[0].findAll('option')).toHaveLength(2)
    await selects[0].setValue('local.duckdb'); await flushPromises()
    expect(selects[1].findAll('option')).toHaveLength(2)
    await selects[1].setValue(2)
    await wrapper.findAll('form')[1].trigger('submit'); await flushPromises()
    expect(store.client.shareLap).toHaveBeenCalledWith('local.duckdb', 2)
    expect(wrapper.text()).toContain('Lap written to your sharing folder')
    await button(wrapper, 'Stop sharing').trigger('click'); await flushPromises()
    expect(store.client.stopSharing).toHaveBeenCalledWith('published')
    expect(wrapper.text()).toContain('Friends may retain downloaded copies')
  })

  it('adds and removes friends, saves settings, and requests manual sync', async () => {
    const { wrapper, store } = view(); await flushPromises()
    const forms = wrapper.findAll('form')
    await forms[0].findAll('input')[0].setValue('/new-folder')
    await forms[0].trigger('submit'); await flushPromises()
    expect(store.client.saveSharing).toHaveBeenCalledWith({ publish_dir: '/new-folder', public_url: '' })
    const inputs = forms[2].findAll('input')
    await inputs[0].setValue('Pat'); await inputs[1].setValue('https://drive.google.com/drive/folders/pat')
    await forms[2].trigger('submit'); await flushPromises()
    expect(store.client.addFriend).toHaveBeenCalledWith({ name: 'Pat', url: 'https://drive.google.com/drive/folders/pat' })
    await button(wrapper, 'Sync friend').trigger('click'); await flushPromises()
    expect(store.client.syncFriends).toHaveBeenCalledWith('friend')
    await button(wrapper, 'Remove friend').trigger('click'); await flushPromises()
    expect(store.client.removeFriend).toHaveBeenCalledWith('friend')
    expect(wrapper.text()).toContain('Downloaded laps remain available')
  })

  it('prevents overlapping sync requests and surfaces write failures', async () => {
    const { wrapper, store } = view({ running: true, progress: '1/2: lap.lmulap' }); await flushPromises()
    expect(button(wrapper, 'Sync now').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('1/2: lap.lmulap')
    store.client.stopSharing.mockRejectedValue(new Error('File was modified'))
    await button(wrapper, 'Stop sharing').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('File was modified')
  })

  it('uses write methods and JSON bodies for sharing APIs', async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({}) }))
    const client = createClient({ base: 'http://localhost', fetcher })
    await client.saveSharing({ publish_dir: '/folder' })
    await client.shareLap('my lap.duckdb', 2)
    await client.stopSharing('id')
    expect(fetcher.mock.calls[0][1]).toEqual({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{"publish_dir":"/folder"}' })
    expect(fetcher.mock.calls[1][0]).toContain('my%20lap.duckdb/laps/2/share')
    expect(fetcher.mock.calls[1][1].method).toBe('POST')
    expect(fetcher.mock.calls[2][1].method).toBe('DELETE')
  })
})
