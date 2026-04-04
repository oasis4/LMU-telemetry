import { createRouter, createWebHistory } from 'vue-router'
import SessionLoader from './views/SessionLoader.vue'
import SessionDashboard from './views/SessionDashboard.vue'
import DriverCompare from './views/DriverCompare.vue'

const routes = [
  { path: '/', name: 'sessions', component: SessionLoader },
  { path: '/session/:sessionId', name: 'dashboard', component: SessionDashboard, props: true },
  { path: '/compare', name: 'compare', component: DriverCompare },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
