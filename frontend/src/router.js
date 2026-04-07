import { createRouter, createWebHistory } from 'vue-router'
import SessionLoader from './views/SessionLoader.vue'
import SessionDashboard from './views/SessionDashboard.vue'
import CornerDetail from './views/CornerDetail.vue'

const routes = [
  { path: '/', name: 'sessions', component: SessionLoader },
  { path: '/session/:sessionId', name: 'dashboard', component: SessionDashboard, props: true },
  { path: '/session/:sessionId/corner/:cornerId', name: 'corner', component: CornerDetail, props: true },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
