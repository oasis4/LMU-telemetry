import { createRouter, createWebHistory } from 'vue-router'
import SessionLoader from './views/SessionLoader.vue'
import LapOverview from './views/LapOverview.vue'
import CornerAnalysis from './views/CornerAnalysis.vue'

const routes = [
  { path: '/', name: 'sessions', component: SessionLoader },
  { path: '/session/:sessionId', name: 'laps', component: LapOverview, props: true },
  { path: '/session/:sessionId/analysis', name: 'analysis', component: CornerAnalysis, props: true },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
