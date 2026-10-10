<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry.js'
import { lapTime } from '../format.js'

const store = useTelemetryStore()
const state = ref(null)
const publishDir = ref('')
const publicUrl = ref('')
const friendName = ref('')
const friendUrl = ref('')
const recording = ref('')
const lapNumber = ref('')
const laps = ref([])
const busy = ref(false)
const error = ref('')
const message = ref('')
const local = computed(() => store.sessions.filter(s => !s.shared && !s.error))
let timer
let disposed = false
let polling = false
let lapRequest = 0

async function refresh() {
  if (polling) return
  polling = true
  try {
    const next = await store.client.sharing()
    if (!disposed) state.value = next
  } finally { polling = false }
}

async function act(action, success) {
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await action()
    message.value = success
    await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

watch(recording, async (name) => {
  const request = ++lapRequest
  laps.value = []
  lapNumber.value = ''
  if (!name) return
  try {
    const values = await store.client.laps(name)
    if (request === lapRequest) laps.value = values.filter(l => l.clean)
  } catch (err) { error.value = err.message }
})

onMounted(async () => {
  try {
    await Promise.all([refresh(), store.loadSessions()])
    if (disposed) return
    publishDir.value = state.value.settings.publish_dir
    publicUrl.value = state.value.settings.public_url
    timer = setInterval(() => refresh().catch(err => { error.value = err.message }), 2000)
  } catch (err) { error.value = err.message }
})
onUnmounted(() => { disposed = true; clearInterval(timer) })

function addFriend() {
  return act(async () => {
    await store.client.addFriend({ name: friendName.value, url: friendUrl.value })
    friendName.value = ''; friendUrl.value = ''
  }, 'Friend added. Sync will start when the current job finishes or at the next automatic sync.')
}
async function sync(id) {
  await act(async () => {
    const result = await store.client.syncFriends(id)
    if (!result.started) throw new Error('A sync is already queued or running.')
  }, 'Sync queued.')
}
function statusLabel(value) {
  return value === 'no_longer_shared' ? 'No longer shared' : value === 'friend_removed' ? 'Friend removed · local copy retained' : 'Shared'
}
function date(value) { return value ? new Date(value).toLocaleString() : 'Never' }
</script>

<template>
  <section class="sharing">
    <h1>Shared laps</h1>
    <p class="quiet">Publish selected laps to your Google Drive Desktop folder. Friends’ laps sync on startup and every five minutes while the analyzer runs.</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <form @submit.prevent="act(() => store.client.saveSharing({ publish_dir: publishDir, public_url: publicUrl }), 'Sharing folder saved.')">
      <h2>Your sharing folder</h2>
      <p>Choose a dedicated local folder synced by Google Drive Desktop. In Google Drive, set that folder to “Anyone with the link” with Viewer access.</p>
      <label>Local folder path <input v-model="publishDir" required placeholder="C:\Users\you\Google Drive\LMU shared laps" /></label>
      <label>Public Google Drive folder URL (optional) <input v-model="publicUrl" type="url" placeholder="https://drive.google.com/drive/folders/…" /></label>
      <div class="actions"><button :disabled="busy">Save folder</button>
        <button v-if="state?.settings.public_url" type="button" :disabled="busy" @click="act(() => navigator.clipboard.writeText(state.settings.public_url), 'Folder URL copied.')">Copy folder URL</button></div>
      <p class="quiet">Publishing writes a local lap file. Google Drive Desktop controls when it reaches Drive. Driver, car, circuit, lap time and telemetry are included.</p>
    </form>
    <form @submit.prevent="act(() => store.client.shareLap(recording, lapNumber), 'Lap written to your sharing folder.')">
      <h2>Publish a lap</h2>
      <label>Recording <select v-model="recording" required><option value="">Choose a recording</option><option v-for="s in local" :key="s.name" :value="s.name">{{ s.track }} · {{ s.driver }} · {{ s.recorded_at }} · {{ s.car }}</option></select></label>
      <label>Usable lap <select v-model="lapNumber" required><option value="">Choose a lap</option><option v-for="lap in laps" :key="lap.number" :value="lap.number">Lap {{ lap.number }} · {{ lapTime(lap.duration_s) }}</option></select></label>
      <button :disabled="busy || !lapNumber || !state?.settings.publish_dir">Share lap</button>
      <ul><li v-for="lap in state?.published ?? []" :key="lap.id">{{ lap.track }} · lap {{ lap.lap }} · {{ lapTime(lap.duration_s) }} · {{ lap.driver }}
        <button :disabled="busy" @click="act(() => store.client.stopSharing(lap.id), 'Stopped sharing. Friends may retain downloaded copies.')" type="button">Stop sharing</button></li></ul>
      <p v-if="state && !state.published.length" class="quiet">No published laps yet.</p>
    </form>
    <form @submit.prevent="addFriend">
      <h2>Friends’ folders</h2>
      <label>Friend name <input v-model="friendName" required maxlength="100" /></label>
      <label>Public Google Drive folder URL <input v-model="friendUrl" type="url" required placeholder="https://drive.google.com/drive/folders/…" /></label>
      <button :disabled="busy">Add friend</button>
    </form>
    <div class="actions"><button :disabled="busy || state?.running || state?.queued" @click="sync()">Sync now</button><span v-if="state?.running || state?.queued" role="status">Syncing… {{ state.progress }}</span></div>
    <ul><li v-for="friend in state?.friends ?? []" :key="friend.id">
      <strong>{{ friend.name }}</strong> · Last successful sync: {{ date(friend.last_success) }}
      <div class="actions"><button :disabled="busy || state.running || state.queued" @click="sync(friend.id)">Sync friend</button><button :disabled="busy" @click="act(() => store.client.removeFriend(friend.id), 'Friend removed. Downloaded laps remain available.')">Remove friend</button></div>
      <p v-if="friend.error" class="error">{{ friend.error }}</p>
    </li></ul>
    <h2>Downloaded laps</h2>
    <p class="quiet">Available offline in both Compare selectors. Removing a friend or a shared file keeps your downloaded copy.</p>
    <ul><li v-for="lap in state?.laps ?? []" :key="lap.id">{{ lap.friend_name }} · {{ lap.info.driver }} · {{ lap.info.track }} · {{ lapTime(lap.duration_s) }} · {{ statusLabel(lap.sharing_status) }}</li></ul>
    <p v-if="state && !state.laps.length" class="quiet">No downloaded laps yet.</p>
    <router-link :to="{ name: 'compare' }">Compare laps</router-link>
  </section>
</template>

<style scoped>
.sharing { max-width: 850px; display: grid; gap: 1rem; }
form { display: grid; gap: 0.7rem; padding: 1rem; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
h2 { font-size: 1.1rem; }
label { display: grid; gap: 0.3rem; }
input, select { width: 100%; padding: 0.5rem; background: var(--page); color: var(--ink); border: 1px solid var(--line); border-radius: 4px; }
button { padding: 0.4rem 0.7rem; border: 1px solid var(--line); border-radius: 4px; justify-self: start; }
button:disabled { opacity: 0.5; }
ul { display: grid; gap: 0.8rem; list-style: none; }
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.quiet { color: var(--muted); font-size: 0.9rem; }
.error { color: var(--loss); overflow-wrap: anywhere; }
</style>
